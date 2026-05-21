"""LAN inventory — discover hosts on the local IPv4 subnet.

ARP-based "who's on my Wi-Fi" discovery. Each tick:

1. ICMP ping sweep against every IP in the local subnet (concurrency
   bounded at 30 via ``asyncio.Semaphore``; per-host timeout 200 ms).
   Sweeping populates the kernel ARP cache; we never read raw sockets.
2. ``arp -an`` subprocess parsed for ``(ip, mac, iface)`` triples.
3. Each MAC enriched with vendor (OUI lookup reused from
   ``diting.ble``), reverse-DNS hostname (``socket.gethostbyaddr``),
   and a Bonjour cross-reference from the live ``BonjourPoller``
   state — yielding the friendly name when one is available on the
   same IP.
4. ``LANInventoryUpdate`` yielded over the async iterator.

The poller is **enabled by default** and the TUI constructs it lazily
on first entry to the LAN view (third ``n`` press). Subnet derivation
caps the sweep at /24 around ``iface_ip``; ``DITING_LAN_INVENTORY_WIDE=1``
relaxes the cap to /22 for users on wider home subnets.

Out of scope (explicitly): port scanning, SSDP / UPnP probing, NetBIOS
queries, TCP banner grabs, raw-socket ARP injection. The poller only
ever invokes ``ping`` and ``arp`` subprocesses.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from typing import Any

from .ble import load_ouis, lookup_oui_vendor
from .events import (
    LANHostDHCPRotationEvent,
    LANHostLeftEvent,
    LANHostSeenEvent,
)
from .mdns import BonjourPoller
from .models import Connection


@dataclass(frozen=True, slots=True)
class LANHost:
    """One host on the local LAN.

    Keyed by ``mac`` (lowercase). ``first_seen`` is preserved across
    DHCP IP rotation; ``last_seen`` updates on every observation.

    ``last_rtt_ms`` and ``last_reachable_at`` track ICMP-reachability
    separately from ARP-observation (``last_seen``). A host that's
    still in the kernel ARP cache but has gone offline will have a
    fresh ``last_seen`` but a stale ``last_reachable_at`` — the
    detail modal surfaces both so the user can spot the gap.
    """

    mac: str
    ip: str
    vendor: str | None
    hostname: str | None
    bonjour_name: str | None
    bonjour_services: tuple[str, ...]
    first_seen: datetime
    last_seen: datetime
    is_gateway: bool
    is_self: bool
    is_randomised_mac: bool
    last_rtt_ms: float | None = None
    last_reachable_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LANInventoryUpdate:
    """Snapshot emitted per sweep tick."""

    hosts: tuple[LANHost, ...]
    subnet: str  # CIDR, e.g. "192.168.1.0/24"
    subnet_capped: bool
    cap_prefix: int  # 24 by default, 22 when DITING_LAN_INVENTORY_WIDE=1
    last_sweep_at: datetime
    next_sweep_at: datetime


# Hard ceilings: default 256 IPs / tick (/24), 1024 IPs / tick (/22).
_DEFAULT_CAP_PREFIX = 24
_WIDE_CAP_PREFIX = 22
_PING_CONCURRENCY = 30
_PING_TIMEOUT_MS = 200
_REVERSE_DNS_TIMEOUT_S = 0.5
# Window after which a host that's no longer in the ARP cache AND
# whose `last_reachable_at` is older than this is considered
# departed. Generates a `LANHostLeftEvent`; the entry is then
# removed from `_state` so a re-appearance fires a fresh seen.
_HOST_LEFT_TIMEOUT_S = 300.0

_ARP_LINE_RE = re.compile(
    r"\(([\d.]+)\)\s+at\s+([0-9a-f:]+)\s+on\s+(\w+)",
    flags=re.IGNORECASE,
)

# macOS `ping -c 1` writes a single sample line containing
# `time=X.XXX ms` (decimal varies; some locales use `,` decimal
# separator but macOS pings always print `.`). This regex pulls the
# RTT in milliseconds.
_PING_RTT_RE = re.compile(r"time=([\d.]+)\s*ms", flags=re.IGNORECASE)


def _ip_in_network(ip: str, network: ipaddress.IPv4Network) -> bool:
    """Return True iff ``ip`` is a usable host in ``network``.

    Excludes the network and broadcast addresses so stale ARP entries
    for either don't leak into the LAN panel.
    """
    try:
        addr = ipaddress.IPv4Address(ip)
    except (ipaddress.AddressValueError, ValueError):
        return False
    if addr == network.network_address or addr == network.broadcast_address:
        return False
    return addr in network


def _is_randomised_mac(mac: str) -> bool:
    """Return True when bit 0x02 of the first octet is set.

    The IEEE "locally administered" bit — set means the MAC was
    self-assigned (random MAC) rather than burned-in by the vendor.
    """
    try:
        first_octet = int(mac.split(":", 1)[0], 16)
    except (ValueError, IndexError):
        return False
    return bool(first_octet & 0x02)


def _effective_cap_prefix() -> int:
    """Return 22 when DITING_LAN_INVENTORY_WIDE=1, else 24."""
    if os.environ.get("DITING_LAN_INVENTORY_WIDE") == "1":
        return _WIDE_CAP_PREFIX
    return _DEFAULT_CAP_PREFIX


def _parse_ifconfig_netmask(ifconfig_out: str, iface_ip: str) -> int | None:
    """Return prefix length for the inet block carrying ``iface_ip``.

    macOS ``ifconfig`` prints netmask as a hex word like ``0xffffff00``
    on the inet line. We find the block matching the user's IP and
    convert the netmask to a prefix length.
    """
    for line in ifconfig_out.splitlines():
        m = re.match(
            r"\s*inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+0x([0-9a-fA-F]+)",
            line,
        )
        if m and m.group(1) == iface_ip:
            mask_int = int(m.group(2), 16)
            return bin(mask_int).count("1")
    return None


def _detect_subnet(
    iface_ip: str,
    *,
    ifconfig_runner=None,
    cap_prefix: int | None = None,
) -> tuple[list[str], str, int, bool]:
    """Derive the sweep list, CIDR, cap, and capped-flag.

    Returns ``(hosts_to_probe, cidr, cap_prefix, was_capped)``.
    ``hosts_to_probe`` excludes the network and broadcast addresses.
    ``was_capped`` is True when the netmask was wider than ``cap_prefix``
    so the sweep was narrowed.
    """
    if cap_prefix is None:
        cap_prefix = _effective_cap_prefix()

    if ifconfig_runner is None:
        def ifconfig_runner() -> str:
            return subprocess.run(
                ["/sbin/ifconfig"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout

    netmask_prefix: int | None = None
    try:
        netmask_prefix = _parse_ifconfig_netmask(ifconfig_runner(), iface_ip)
    except Exception:
        netmask_prefix = None

    # Default to /24 when we can't read the netmask — safe and matches
    # the cap.
    if netmask_prefix is None:
        netmask_prefix = 24

    effective_prefix = max(netmask_prefix, cap_prefix)
    was_capped = effective_prefix > netmask_prefix

    network = ipaddress.IPv4Network(f"{iface_ip}/{effective_prefix}", strict=False)
    hosts = [str(h) for h in network.hosts()]
    return hosts, str(network), cap_prefix, was_capped


async def _ping_one(
    ip: str, *, timeout_ms: int = _PING_TIMEOUT_MS,
) -> tuple[bool, float | None]:
    """Send one ICMP echo via unprivileged ``ping``.

    Returns ``(reachable, rtt_ms)``:
    - ``(True, <rtt>)`` when ``ping`` exits 0 and stdout contains a
      parseable ``time=X.XXX ms`` segment
    - ``(True, None)`` when ``ping`` exits 0 but stdout is
      unparseable (locale quirk, weird build)
    - ``(False, None)`` when ``ping`` exits non-zero or the
      subprocess errors out
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "/sbin/ping",
            "-c",
            "1",
            "-W",
            str(timeout_ms),
            ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout_bytes, _ = await proc.communicate()
        rc = proc.returncode
    except (OSError, asyncio.CancelledError):
        return False, None
    if rc != 0:
        return False, None
    text = stdout_bytes.decode("ascii", errors="replace")
    m = _PING_RTT_RE.search(text)
    if not m:
        return True, None
    try:
        return True, float(m.group(1))
    except ValueError:
        return True, None


async def _sweep(
    hosts: list[str],
    *,
    concurrency: int = _PING_CONCURRENCY,
    timeout_ms: int = _PING_TIMEOUT_MS,
) -> dict[str, tuple[bool, float | None]]:
    """Ping every IP in ``hosts`` with bounded concurrency.

    Returns ``{ip: (reachable, rtt_ms)}``. The side-effect we ALSO
    care about is the populated kernel ARP cache; the merge step in
    ``LANInventoryPoller`` reads ``arp -an`` after the sweep
    completes.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(ip: str) -> tuple[str, tuple[bool, float | None]]:
        async with sem:
            result = await _ping_one(ip, timeout_ms=timeout_ms)
            return ip, result

    pairs = await asyncio.gather(
        *[_one(ip) for ip in hosts], return_exceptions=True,
    )
    out: dict[str, tuple[bool, float | None]] = {}
    for p in pairs:
        if isinstance(p, tuple) and len(p) == 2:
            ip, result = p
            out[ip] = result
    return out


def _read_arp_cache(*, runner=None) -> list[tuple[str, str, str]]:
    """Return ``(ip, mac, iface)`` triples from ``arp -an``.

    Skips lines whose MAC is ``<incomplete>`` — those are sweep
    attempts that got no ARP reply.
    """
    if runner is None:
        def runner() -> str:
            return subprocess.run(
                ["/usr/sbin/arp", "-an"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout

    try:
        out = runner()
    except (subprocess.SubprocessError, OSError):
        return []

    result: list[tuple[str, str, str]] = []
    for line in out.splitlines():
        m = _ARP_LINE_RE.search(line)
        if not m:
            continue
        ip, mac, iface = m.group(1), m.group(2).lower(), m.group(3)
        result.append((ip, mac, iface))
    return result


async def _reverse_dns(ip: str, *, timeout_s: float = _REVERSE_DNS_TIMEOUT_S) -> str | None:
    """Return ``socket.gethostbyaddr(ip)[0]`` or None on timeout / fail."""
    try:
        host, _aliases, _addrs = await asyncio.wait_for(
            asyncio.to_thread(socket.gethostbyaddr, ip),
            timeout=timeout_s,
        )
    except (asyncio.TimeoutError, OSError):
        return None
    return host


def _strip_local_suffix(host: str | None) -> str | None:
    """Drop trailing ``.local.`` / ``.local`` like the Bonjour panel does."""
    if not host:
        return None
    h = host.rstrip(".")
    if h.endswith(".local"):
        h = h[: -len(".local")]
    return h or None


def _build_bonjour_index(
    bonjour_poller: BonjourPoller | None,
) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """Walk ``BonjourPoller._state`` once, return ``{ip: (host, services)}``.

    ``services`` is a tuple of unique ``category`` strings across every
    Bonjour entry whose ``addresses`` contains the IP. The LAN poller
    does NOT mutate Bonjour state.
    """
    if bonjour_poller is None:
        return {}

    by_ip: dict[str, tuple[str | None, list[str]]] = {}
    for dev in bonjour_poller._state.values():
        host = _strip_local_suffix(dev.host)
        for ip in dev.addresses:
            entry = by_ip.setdefault(ip, (host, []))
            cur_host, cats = entry
            # First match wins for host name (rare virtual-host case).
            if cur_host is None and host is not None:
                cur_host = host
            if dev.category and dev.category not in cats:
                cats.append(dev.category)
            by_ip[ip] = (cur_host, cats)

    return {ip: (host, tuple(cats)) for ip, (host, cats) in by_ip.items()}


class LANInventoryPoller:
    """Async iterator over ``LANInventoryUpdate`` snapshots.

    Mirrors ``BonjourPoller``'s shape:

    * ``__init__`` configures cadence; does no I/O.
    * ``events()`` async-iterates ``LANInventoryUpdate`` values; the
      first iteration starts the sweep loop.
    * ``stop()`` flips ``_stopped`` so the loop exits at the next
      wait point.
    """

    def __init__(
        self,
        *,
        connection_provider,
        bonjour_poller: BonjourPoller | None = None,
        sweep_interval_s: float = 60.0,
        ping_timeout_ms: int = _PING_TIMEOUT_MS,
    ) -> None:
        # ``connection_provider`` is a no-arg callable returning a
        # ``Connection`` (or None) — usually ``backend.get_connection``.
        # We re-read on every sweep so DHCP / gateway changes are
        # picked up.
        self._connection_provider = connection_provider
        self._bonjour_poller = bonjour_poller
        self._sweep_interval_s = sweep_interval_s
        self._ping_timeout_ms = ping_timeout_ms

        self._stopped = False
        self._state: dict[str, LANHost] = {}
        self._queue: asyncio.Queue[LANInventoryUpdate] = asyncio.Queue()
        # Transition events (LANHostSeenEvent / LANHostLeftEvent /
        # LANHostDHCPRotationEvent) accumulated during each sweep.
        # Drained via ``drain_transitions()`` so `events()` stays
        # mono-typed (snapshots only) and existing tests keep working.
        self._pending_transitions: list[Any] = []
        self._sweep_wakeup: asyncio.Event | None = None
        self._ouis: dict[str, str] | None = None

    def drain_transitions(self) -> list[Any]:
        """Pop transition events accumulated during recent sweep
        ticks. Consumer calls this after each `LANInventoryUpdate`."""
        out = self._pending_transitions
        self._pending_transitions = []
        return out

    async def events(self) -> AsyncIterator[LANInventoryUpdate]:
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._sweep_loop(), name="lan-inventory")
        try:
            while True:
                yield await self._queue.get()
        finally:
            self._stopped = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def force_now(self) -> None:
        """Wake the sweep loop to run an immediate sweep."""
        if self._sweep_wakeup is not None:
            self._sweep_wakeup.set()

    def stop(self) -> None:
        self._stopped = True
        if self._sweep_wakeup is not None:
            self._sweep_wakeup.set()

    async def _sweep_loop(self) -> None:
        self._sweep_wakeup = asyncio.Event()
        while not self._stopped:
            try:
                await self._do_sweep_and_emit()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed sweep must not kill the loop — wait the
                # interval and try again.
                pass
            try:
                await asyncio.wait_for(
                    self._sweep_wakeup.wait(),
                    timeout=self._sweep_interval_s,
                )
            except asyncio.TimeoutError:
                pass
            self._sweep_wakeup.clear()

    async def _do_sweep_and_emit(self) -> None:
        conn = self._connection_provider()
        if conn is None or not conn.ip_address:
            return

        hosts_to_probe, cidr, cap_prefix, was_capped = _detect_subnet(conn.ip_address)
        # Always include the gateway IP, even when it falls outside
        # the /24 cap. Corporate networks frequently put the gateway
        # in a different /24 from clients ("management subnet"
        # convention); excluding it would drop the most useful row
        # from the panel.
        if conn.router_ip and conn.router_ip not in hosts_to_probe:
            hosts_to_probe.append(conn.router_ip)

        sweep_results = await _sweep(
            hosts_to_probe, timeout_ms=self._ping_timeout_ms,
        )

        # Filter ARP cache entries down to the sweep's network. The
        # kernel ARP cache also holds entries from outside our /24 (or
        # /22 with WIDE flag) — e.g. on a corporate /16 VLAN the cache
        # accumulates whatever the OS has talked to today. Without the
        # filter those stale, out-of-range entries pollute the panel
        # and confuse the user into thinking diting swept further than
        # it did. The gateway IP gets an unconditional exemption so
        # cross-subnet gateways still show up.
        try:
            network = ipaddress.IPv4Network(cidr, strict=False)
        except ValueError:
            network = None
        all_triples = _read_arp_cache()
        if network is not None:
            triples = [
                (ip, mac, iface)
                for (ip, mac, iface) in all_triples
                if _ip_in_network(ip, network) or ip == conn.router_ip
            ]
        else:
            triples = all_triples

        now = datetime.now(timezone.utc)
        await self._merge_arp_into_state(
            triples, conn=conn, now=now, sweep_results=sweep_results,
        )

        update = LANInventoryUpdate(
            hosts=tuple(sorted(self._state.values(), key=_sort_key)),
            subnet=cidr,
            subnet_capped=was_capped,
            cap_prefix=cap_prefix,
            last_sweep_at=now,
            next_sweep_at=datetime.fromtimestamp(
                now.timestamp() + self._sweep_interval_s,
                tz=timezone.utc,
            ),
        )
        await self._queue.put(update)

    async def _merge_arp_into_state(
        self,
        triples: list[tuple[str, str, str]],
        *,
        conn: Connection,
        now: datetime,
        sweep_results: dict[str, tuple[bool, float | None]] | None = None,
    ) -> None:
        if self._ouis is None:
            self._ouis = load_ouis()

        bonjour_index = _build_bonjour_index(self._bonjour_poller)

        # Reverse-DNS lookups in parallel, capped at the sweep
        # concurrency.
        sem = asyncio.Semaphore(_PING_CONCURRENCY)

        async def _rdns(ip: str) -> tuple[str, str | None]:
            async with sem:
                return ip, await _reverse_dns(ip)

        rdns_results: dict[str, str | None] = {}
        if triples:
            rdns_pairs = await asyncio.gather(
                *[_rdns(ip) for ip, _mac, _iface in triples],
                return_exceptions=True,
            )
            for pair in rdns_pairs:
                if isinstance(pair, tuple):
                    ip, host = pair
                    rdns_results[ip] = host

        iface_mac_lc = (conn.interface_mac or "").lower()
        router_ip = conn.router_ip
        sweep_results = sweep_results or {}

        def _rtt_for(existing_entry, ip_addr):
            """Return (last_rtt_ms, last_reachable_at) for this tick.

            Pulls from the sweep result if the host responded; falls
            back to the existing entry's values when the host was
            silent this sweep (so a temporarily-quiet host's
            last-known RTT stays visible in the modal). Returns
            (None, None) for never-reached hosts.
            """
            sweep_entry = sweep_results.get(ip_addr)
            if sweep_entry is not None:
                reachable, rtt_ms = sweep_entry
                if reachable:
                    return rtt_ms, now
            # Sweep got no reply this tick — preserve existing
            # last-known values if we have them.
            if existing_entry is not None:
                return existing_entry.last_rtt_ms, existing_entry.last_reachable_at
            return None, None

        # Snapshot self too: we don't appear in our own ARP cache,
        # but the user wants to see "this Mac" pinned at the top.
        if iface_mac_lc and conn.ip_address:
            self_entry = self._state.get(iface_mac_lc)
            # We don't ping our own IP in the sweep (sweep targets
            # /24 around iface_ip, which includes our IP, but ping to
            # self on macOS is trivially ~0.1 ms and informative).
            # If the sweep happens to have a result for our IP, use
            # it; otherwise mark self as reachable=now with no RTT.
            self_sweep = sweep_results.get(conn.ip_address)
            if self_sweep is not None and self_sweep[0]:
                self_rtt, self_reach = self_sweep[1], now
            else:
                self_rtt = self_entry.last_rtt_ms if self_entry else None
                self_reach = (
                    now if self_entry is None else self_entry.last_reachable_at
                )
            self._state[iface_mac_lc] = LANHost(
                mac=iface_mac_lc,
                ip=conn.ip_address,
                vendor=(
                    lookup_oui_vendor(iface_mac_lc, self._ouis)
                    if not _is_randomised_mac(iface_mac_lc)
                    else None
                ),
                hostname=(self_entry.hostname if self_entry else None),
                bonjour_name=None,
                bonjour_services=(),
                first_seen=self_entry.first_seen if self_entry else now,
                last_seen=now,
                is_gateway=False,
                is_self=True,
                is_randomised_mac=_is_randomised_mac(iface_mac_lc),
                last_rtt_ms=self_rtt,
                last_reachable_at=self_reach,
            )

        # Track MACs we observed this tick so we can detect departures
        # after the loop. Self injection above also goes into this set
        # so we don't accidentally emit a "left" event for ourselves.
        observed_macs: set[str] = set()
        if iface_mac_lc:
            observed_macs.add(iface_mac_lc)

        for ip, mac, _iface in triples:
            mac_lc = mac.lower()
            observed_macs.add(mac_lc)
            existing = self._state.get(mac_lc)
            randomised = _is_randomised_mac(mac_lc)
            vendor = (
                lookup_oui_vendor(mac_lc, self._ouis)
                if not randomised
                else None
            )
            bonjour_host, bonjour_cats = bonjour_index.get(ip, (None, ()))
            hostname = rdns_results.get(ip, existing.hostname if existing else None)
            last_rtt_ms, last_reachable_at = _rtt_for(existing, ip)
            is_gateway_now = (router_ip is not None and ip == router_ip)
            is_self_now = (mac_lc == iface_mac_lc)
            host_entry = LANHost(
                mac=mac_lc,
                ip=ip,
                vendor=vendor,
                hostname=hostname,
                bonjour_name=bonjour_host,
                bonjour_services=bonjour_cats,
                first_seen=existing.first_seen if existing else now,
                last_seen=now,
                is_gateway=is_gateway_now,
                is_self=is_self_now,
                is_randomised_mac=randomised,
                last_rtt_ms=last_rtt_ms,
                last_reachable_at=last_reachable_at,
            )
            # Special-case: self may also appear in ARP (rare; mostly
            # not, since we ARP others). If it does, merge — keep
            # is_self pinned True.
            if host_entry.is_self and iface_mac_lc:
                existing_self = self._state.get(iface_mac_lc)
                if existing_self is not None:
                    self._state[iface_mac_lc] = replace(
                        existing_self,
                        ip=ip,
                        last_seen=now,
                        hostname=hostname or existing_self.hostname,
                        last_rtt_ms=last_rtt_ms or existing_self.last_rtt_ms,
                        last_reachable_at=(
                            last_reachable_at or existing_self.last_reachable_at
                        ),
                    )
                continue
            # Transition-event emission. Self / gateway are excluded
            # from `seen` events per the spec (they would otherwise fire
            # on every diting launch and pollute downstream analysis).
            if existing is None and not is_self_now and not is_gateway_now:
                self._pending_transitions.append(LANHostSeenEvent(
                    timestamp=now,
                    mac=mac_lc,
                    ip=ip,
                    vendor=vendor,
                    hostname=hostname,
                    bonjour_name=bonjour_host,
                    is_randomised_mac=randomised,
                ))
            elif existing is not None and existing.ip != ip:
                # DHCP rotation: same MAC, new IP. Event fires BEFORE
                # the state entry's `ip` field gets the new value.
                self._pending_transitions.append(LANHostDHCPRotationEvent(
                    timestamp=now,
                    mac=mac_lc,
                    previous_ip=existing.ip,
                    new_ip=ip,
                    vendor=vendor,
                    hostname=hostname,
                    bonjour_name=bonjour_host,
                ))
            self._state[mac_lc] = host_entry

        # Sweep over `_state` for hosts that have gone silent past
        # `_HOST_LEFT_TIMEOUT_S` AND are absent from the latest ARP
        # triples. Emit a single `LANHostLeftEvent` per departure and
        # drop the entry so a re-appearance fires a fresh seen.
        # Self + gateway are skipped — they're always observed.
        for mac_lc, dev in list(self._state.items()):
            if mac_lc in observed_macs:
                continue
            if dev.is_self:
                continue
            # Use last_reachable_at when known; fall back to last_seen
            # so a never-reached host can still depart cleanly.
            age_anchor = dev.last_reachable_at or dev.last_seen
            age_s = (now - age_anchor).total_seconds()
            if age_s < _HOST_LEFT_TIMEOUT_S:
                continue
            self._pending_transitions.append(LANHostLeftEvent(
                timestamp=now,
                mac=mac_lc,
                ip=dev.ip,
                vendor=dev.vendor,
                hostname=dev.hostname,
                bonjour_name=dev.bonjour_name,
                is_randomised_mac=dev.is_randomised_mac,
                seen_for_seconds=(dev.last_seen - dev.first_seen).total_seconds(),
                last_reachable_ago_seconds=(
                    (now - dev.last_reachable_at).total_seconds()
                    if dev.last_reachable_at else None
                ),
            ))
            self._state.pop(mac_lc, None)


def _sort_key(h: LANHost) -> tuple[int, int, tuple[int, ...]]:
    """Self → gateway → IP ascending."""
    rank = 0 if h.is_self else (1 if h.is_gateway else 2)
    try:
        ip_tuple = tuple(int(p) for p in h.ip.split("."))
    except ValueError:
        ip_tuple = (0, 0, 0, 0)
    return (rank, 0, ip_tuple)
