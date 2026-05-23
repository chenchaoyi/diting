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

from .ble import load_ouis_layered, lookup_oui_vendor
from .events import (
    LANHostDHCPRotationEvent,
    LANHostLeftEvent,
    LANHostSeenEvent,
)
from .lan_classify import classify as _classify_device
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
    # Raw IEEE registry string before _normalize_vendor() ran. Kept so
    # the detail modal can surface both forms — the row gets the short
    # normalized name, the modal lets the user reconcile odd cases.
    vendor_raw: str | None = None
    # Active-discovery enrichments. All None when the active-probe
    # phase did not run for this host (scene-gated, or the host
    # didn't reply). The fields default to None so existing test
    # fixtures + JSONL consumers stay valid.
    nbns_name: str | None = None
    upnp_server: str | None = None
    upnp_friendly_name: str | None = None
    upnp_model: str | None = None
    # Raw IP TTL from the most recent successful ICMP echo, plus
    # a coarse class derived via `ttl_class_for`: "unix" / "windows"
    # / "router" / None. Presentational only — never affects events
    # or analyzer aggregation.
    ttl: int | None = None
    ttl_class: str | None = None
    # Output of the device-class inference rules in
    # `src/diting/lan_classify.py`. One of `phone | laptop |
    # desktop | tv | camera | smart-home | printer | nas | gaming
    # | speaker | router`, or None when no rule fires. Presentational
    # only.
    device_class: str | None = None


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


def _is_multicast_dest_mac(mac: str) -> bool:
    """Return True for IPv4 / IPv6 multicast destination MACs.

    The kernel ARP cache occasionally carries these as a side
    effect of any process (including diting's own SSDP M-SEARCH)
    sending to a multicast group. They are NOT real LAN hosts —
    they're destination MACs for multicast groups and have no
    associated device.

    Filtered ranges:
    - ``01:00:5e:00:00:00`` – ``01:00:5e:7f:ff:ff``: IPv4 multicast
      (224.0.0.0/4) per RFC 1112 §6.4.
    - ``33:33:00:00:00:00`` – ``33:33:ff:ff:ff:ff``: IPv6 multicast
      per RFC 2464 §7.
    """
    # Pad each octet to 2 chars so stripped-zero arp output still
    # matches (``1:0:5e:*`` → ``01:00:5e:*``).
    parts = mac.lower().split(":")
    if len(parts) != 6:
        return False
    try:
        padded = [p.zfill(2) for p in parts]
    except Exception:
        return False
    if padded[0] == "01" and padded[1] == "00" and padded[2] == "5e":
        return True
    if padded[0] == "33" and padded[1] == "33":
        return True
    return False

# macOS `ping -c 1` writes a single sample line containing
# `time=X.XXX ms` (decimal varies; some locales use `,` decimal
# separator but macOS pings always print `.`). This regex pulls the
# RTT in milliseconds.
_PING_RTT_RE = re.compile(r"time=([\d.]+)\s*ms", flags=re.IGNORECASE)

# macOS `ping -c 1` also reports `ttl=N` in the same sample line.
# Used by the device-class heuristics to discriminate Linux / Mac /
# iOS / Android (TTL ≈ 64) vs Windows (≈ 128) vs legacy routers
# (≈ 255). Same packet — no additional traffic.
_PING_TTL_RE = re.compile(r"ttl=(\d+)", flags=re.IGNORECASE)


def ttl_class_for(ttl: int | None) -> str | None:
    """Map a raw IP TTL value to a coarse OS-family class.

    The IETF-canonical initial TTLs are 64 (Unix-family: Linux,
    macOS, iOS, Android, BSDs) and 128 (Windows). Some legacy
    routers advertise 255. We absorb single-digit hop decrements
    by accepting a small range below each canonical anchor.

    Returns ``None`` for values outside any recognised band or
    when ``ttl`` is None — the field is presentational, never
    load-bearing.
    """
    if ttl is None:
        return None
    if 50 <= ttl <= 64:
        return "unix"
    if 100 <= ttl <= 128:
        return "windows"
    if 200 <= ttl <= 255:
        return "router"
    return None


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


# Tokens stripped from the trailing end of an IEEE registry string.
# Order matters: longer multi-word tokens go first so they match
# before their substrings.
_TRAILING_NOISE_TOKENS: tuple[str, ...] = (
    "CO., LTD.",
    "CO.,LTD.",
    "CO., LTD",
    "CO.,LTD",
    "CO. LTD",
    "CO LTD",
    "CO.,",
    "CO.",
    "CO",
    "CORPORATION",
    "CORP.",
    "CORP",
    "LIMITED",
    "LTD.",
    "LTD",
    "INC.",
    "INC",
    "GMBH",
    "LLC",
    "B.V.",
    "BV",
    "S.A.",
    "SA",
    "COMPANY",
    "TECHNOLOGIES",
    "TECHNOLOGY",
    "ELECTRONICS",
    "ELECTRONIC",
)

# Geographic prefixes stripped from the leading end. Chinese city
# names bloat the column without identifying the company; the actual
# brand follows.
_LEADING_NOISE_TOKENS: tuple[str, ...] = (
    "SHENZHEN",
    "HANGZHOU",
    "BEIJING",
    "SHANGHAI",
    "GUANGZHOU",
    "DONGGUAN",
    "CHENGDU",
    "NANJING",
    "SUZHOU",
    "TIANJIN",
)

# Acronyms / brand names that must NOT be titlecased. Keyed by the
# titlecased form Python would produce so the lookup is cheap.
_ACRONYM_OVERRIDES: dict[str, str] = {
    "Hp": "HP",
    "Ibm": "IBM",
    "Asus": "ASUS",
    "Asrock": "ASRock",
    "Lg": "LG",
    "H3C": "H3C",
    "Tp-Link": "TP-Link",
    "D-Link": "D-Link",
    "Zte": "ZTE",
    "Tcl": "TCL",
    "Lge": "LGE",
    "Mtk": "MTK",
    "Hkc": "HKC",
    "Vmware": "VMware",
    "Ipad": "iPad",
    "Iphone": "iPhone",
    "Imac": "iMac",
    "Iot": "IoT",
}

_VENDOR_DISPLAY_WIDTH = 16


def _normalize_vendor(name: str | None) -> str | None:
    """Return a short, readable display form of an IEEE vendor string.

    Drops trailing corporate-form noise (``CO., LTD``, ``CORPORATION``,
    ``LTD``, ``INC``, ``TECHNOLOGIES`` …), drops leading Chinese-city
    prefixes (``SHENZHEN``, ``HANGZHOU`` …), titlecases the remainder
    while preserving registered acronyms via ``_ACRONYM_OVERRIDES``,
    and truncates to ``_VENDOR_DISPLAY_WIDTH`` characters with an
    ellipsis when the result is still too long.

    Returns ``None`` when input is ``None`` or empty. Idempotent: a
    name that already passed through normalization is unchanged.
    """
    if not name:
        return None

    s = name.strip()
    if not s:
        return None

    # Strip leading geographic prefixes, repeating in case the
    # registry packs more than one (rare but defensive).
    changed = True
    while changed:
        changed = False
        upper = s.upper()
        for prefix in _LEADING_NOISE_TOKENS:
            if upper.startswith(prefix + " "):
                s = s[len(prefix) + 1 :].lstrip()
                changed = True
                break

    # Strip trailing corporate-form noise, repeating so e.g.
    # "FOO TECHNOLOGIES CO., LTD" peels both tokens.
    changed = True
    while changed:
        changed = False
        # Strip trailing comma / whitespace so token comparison lands
        # cleanly.
        s = s.rstrip(" ,.;")
        upper = s.upper()
        for tok in _TRAILING_NOISE_TOKENS:
            if upper.endswith(" " + tok) or upper == tok:
                s = s[: len(s) - len(tok)].rstrip(" ,.;")
                changed = True
                break

    s = s.strip(" ,.;")
    if not s:
        return None

    # Titlecase while preserving acronyms. Python's str.title() is
    # naive — "H3C" becomes "H3C" (digits split the word so the C
    # stays upper) but other registered tokens like "ASUS" become
    # "Asus" so we map them back.
    out_tokens: list[str] = []
    for raw in s.split():
        tc = raw.title()
        out_tokens.append(_ACRONYM_OVERRIDES.get(tc, tc))
    out = " ".join(out_tokens)

    # Truncate to display width with an ellipsis. ``str`` len here is
    # fine — the OUI registry is ASCII; CJK glyphs are translated by
    # i18n.t() at the render site, not at the OUI layer.
    if len(out) > _VENDOR_DISPLAY_WIDTH:
        out = out[: _VENDOR_DISPLAY_WIDTH - 1].rstrip() + "…"
    return out


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
) -> tuple[bool, float | None, int | None]:
    """Send one ICMP echo via unprivileged ``ping``.

    Returns ``(reachable, rtt_ms, ttl)``:
    - ``(True, <rtt>, <ttl>)`` when ``ping`` exits 0 and stdout
      contains both parseable ``time=X.XXX ms`` and ``ttl=N`` segments
    - ``(True, <rtt>, None)`` when RTT parses but TTL doesn't (rare)
    - ``(True, None, <ttl>)`` when TTL parses but RTT doesn't (rare)
    - ``(True, None, None)`` when neither parses
    - ``(False, None, None)`` when ``ping`` exits non-zero or the
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
        return False, None, None
    if rc != 0:
        return False, None, None
    text = stdout_bytes.decode("ascii", errors="replace")
    rtt_match = _PING_RTT_RE.search(text)
    ttl_match = _PING_TTL_RE.search(text)
    rtt_ms: float | None = None
    if rtt_match:
        try:
            rtt_ms = float(rtt_match.group(1))
        except ValueError:
            rtt_ms = None
    ttl: int | None = None
    if ttl_match:
        try:
            ttl = int(ttl_match.group(1))
        except ValueError:
            ttl = None
    return True, rtt_ms, ttl


async def _sweep(
    hosts: list[str],
    *,
    concurrency: int = _PING_CONCURRENCY,
    timeout_ms: int = _PING_TIMEOUT_MS,
) -> dict[str, tuple[bool, float | None, int | None]]:
    """Ping every IP in ``hosts`` with bounded concurrency.

    Returns ``{ip: (reachable, rtt_ms, ttl)}``. The side-effect we
    ALSO care about is the populated kernel ARP cache; the merge
    step in ``LANInventoryPoller`` reads ``arp -an`` after the
    sweep completes.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(ip: str) -> tuple[str, tuple[bool, float | None, int | None]]:
        async with sem:
            result = await _ping_one(ip, timeout_ms=timeout_ms)
            return ip, result

    pairs = await asyncio.gather(
        *[_one(ip) for ip in hosts], return_exceptions=True,
    )
    out: dict[str, tuple[bool, float | None, int | None]] = {}
    for p in pairs:
        if isinstance(p, tuple) and len(p) == 2:
            ip, result = p
            out[ip] = result
    return out


def _unpack_sweep_entry(
    entry,
) -> tuple[bool, float | None, int | None]:
    """Normalise a sweep-result tuple into the 3-element shape.

    Tolerates both the new (reachable, rtt, ttl) form and the legacy
    (reachable, rtt) form so existing tests that build synthetic
    sweep_results dicts keep working without migration.
    """
    if entry is None:
        return False, None, None
    if not isinstance(entry, tuple):
        return False, None, None
    if len(entry) >= 3:
        return entry[0], entry[1], entry[2]
    if len(entry) == 2:
        return entry[0], entry[1], None
    if len(entry) == 1:
        return entry[0], None, None
    return False, None, None


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
        # Skip multicast destination MACs — these are not real LAN
        # hosts; they leak into `arp -an` whenever any process sends
        # to a multicast group (diting's own SSDP M-SEARCH triggers
        # `01:00:5e:7f:ff:fa`, mDNS triggers `01:00:5e:00:00:fb`).
        if _is_multicast_dest_mac(mac):
            continue
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
        active_probe_enabled: bool = False,
        upnp_fetch_enabled: bool = True,
    ) -> None:
        # ``connection_provider`` is a no-arg callable returning a
        # ``Connection`` (or None) — usually ``backend.get_connection``.
        # We re-read on every sweep so DHCP / gateway changes are
        # picked up.
        self._connection_provider = connection_provider
        self._bonjour_poller = bonjour_poller
        self._sweep_interval_s = sweep_interval_s
        self._ping_timeout_ms = ping_timeout_ms
        # Active-discovery layer gating. Scene + env resolved at app
        # startup; the poller sees the final boolean. False keeps the
        # passive-only behaviour from previous versions.
        self._active_probe_enabled = active_probe_enabled
        self._upnp_fetch_enabled = upnp_fetch_enabled
        # Public-scene one-shot consent override: when True, the
        # next sweep runs the active-discovery phase once and clears
        # the flag. Set from the LANProbeConsentScreen modal in
        # tui.py; this poller never sets it itself.
        self._one_shot_probe_armed: bool = False

        self._stopped = False
        # Wall-clock instant the poller was constructed. The TUI's
        # `[new]` chip uses this as a grace anchor: hosts whose
        # first_seen falls within `_NEW_CHIP_GRACE_S` of this timestamp
        # are treated as "this session's baseline" rather than "newly
        # appeared", since the LAN poller is lazy-constructed on first
        # `n`-cycle and would otherwise stamp every existing host
        # with first_seen=now, making the chip universal noise.
        self._constructed_at: datetime = datetime.now(timezone.utc)
        self._state: dict[str, LANHost] = {}
        self._queue: asyncio.Queue[LANInventoryUpdate] = asyncio.Queue()
        # Transition events (LANHostSeenEvent / LANHostLeftEvent /
        # LANHostDHCPRotationEvent) accumulated during each sweep.
        # Drained via ``drain_transitions()`` so `events()` stays
        # mono-typed (snapshots only) and existing tests keep working.
        self._pending_transitions: list[Any] = []
        self._sweep_wakeup: asyncio.Event | None = None
        # Three-tier OUI registry. None until the first sweep loads it;
        # subsequent sweeps reuse the same dicts. The tuple shape is
        # (ma_l, ma_m, ma_s) per `load_ouis_layered`'s contract.
        self._oui_layers: tuple[
            dict[str, str], dict[str, str], dict[str, str]
        ] | None = None

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

        # Active-discovery phase. Runs when the scene/env has the
        # capability enabled OR when the public-scene one-shot
        # override has armed the next sweep. Probe enrichments are
        # merged into the per-host state via _apply_probe_results.
        probe_armed = (
            self._active_probe_enabled or self._one_shot_probe_armed
        )
        if probe_armed:
            await self._run_active_probes(conn=conn)
            # One-shot consumes itself — subsequent sweeps revert to
            # scene/env default. Cleared whether or not any host
            # actually responded; the user already paid the consent
            # cost for this single tick.
            self._one_shot_probe_armed = False

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
        sweep_results: dict | None = None,
    ) -> None:
        if self._oui_layers is None:
            self._oui_layers = load_ouis_layered()
        ma_l, ma_m, ma_s = self._oui_layers

        def _resolve_vendor(mac_lc: str, randomised: bool) -> tuple[
            str | None, str | None,
        ]:
            """Return (normalized display vendor, raw IEEE vendor).

            Randomised MACs are not in the registry by construction;
            short-circuit both forms to None so the caller still records
            `is_randomised_mac` truthfully without paying the lookup.
            """
            if randomised:
                return None, None
            raw = lookup_oui_vendor(
                mac_lc, ma_l=ma_l, ma_m=ma_m, ma_s=ma_s,
            )
            return _normalize_vendor(raw), raw

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
            """Return (last_rtt_ms, last_reachable_at, ttl) for this tick.

            Pulls from the sweep result if the host responded; falls
            back to the existing entry's values when the host was
            silent this sweep (so a temporarily-quiet host's
            last-known RTT stays visible in the modal). Returns
            (None, None, None) for never-reached hosts.
            """
            reachable, rtt_ms, ttl = _unpack_sweep_entry(
                sweep_results.get(ip_addr),
            )
            if reachable:
                # Inherit prior TTL only when this sweep didn't see
                # one — a sweep that returned with no ttl segment
                # (rare locale quirk) shouldn't blank a known value.
                if ttl is None and existing_entry is not None:
                    ttl = existing_entry.ttl
                return rtt_ms, now, ttl
            # Sweep got no reply this tick — preserve existing
            # last-known values if we have them.
            if existing_entry is not None:
                return (
                    existing_entry.last_rtt_ms,
                    existing_entry.last_reachable_at,
                    existing_entry.ttl,
                )
            return None, None, None

        # Snapshot self too: we don't appear in our own ARP cache,
        # but the user wants to see "this Mac" pinned at the top.
        if iface_mac_lc and conn.ip_address:
            self_entry = self._state.get(iface_mac_lc)
            # We don't ping our own IP in the sweep (sweep targets
            # /24 around iface_ip, which includes our IP, but ping to
            # self on macOS is trivially ~0.1 ms and informative).
            # If the sweep happens to have a result for our IP, use
            # it; otherwise mark self as reachable=now with no RTT.
            self_reachable, self_rtt_from_sweep, self_ttl_from_sweep = (
                _unpack_sweep_entry(sweep_results.get(conn.ip_address))
            )
            if self_reachable:
                self_rtt, self_reach = self_rtt_from_sweep, now
                self_ttl = (
                    self_ttl_from_sweep
                    if self_ttl_from_sweep is not None
                    else (self_entry.ttl if self_entry else None)
                )
            else:
                self_rtt = self_entry.last_rtt_ms if self_entry else None
                self_reach = (
                    now if self_entry is None else self_entry.last_reachable_at
                )
                self_ttl = self_entry.ttl if self_entry else None
            self_randomised = _is_randomised_mac(iface_mac_lc)
            self_vendor, self_vendor_raw = _resolve_vendor(
                iface_mac_lc, self_randomised,
            )
            self_host = LANHost(
                mac=iface_mac_lc,
                ip=conn.ip_address,
                vendor=self_vendor,
                hostname=(self_entry.hostname if self_entry else None),
                bonjour_name=None,
                bonjour_services=(),
                first_seen=self_entry.first_seen if self_entry else now,
                last_seen=now,
                is_gateway=False,
                is_self=True,
                is_randomised_mac=self_randomised,
                last_rtt_ms=self_rtt,
                last_reachable_at=self_reach,
                vendor_raw=self_vendor_raw,
                ttl=self_ttl,
                ttl_class=ttl_class_for(self_ttl),
            )
            self._state[iface_mac_lc] = replace(
                self_host, device_class=_classify_device(self_host),
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
            vendor, vendor_raw = _resolve_vendor(mac_lc, randomised)
            bonjour_host, bonjour_cats = bonjour_index.get(ip, (None, ()))
            hostname = rdns_results.get(ip, existing.hostname if existing else None)
            last_rtt_ms, last_reachable_at, ttl = _rtt_for(existing, ip)
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
                vendor_raw=vendor_raw,
                ttl=ttl,
                ttl_class=ttl_class_for(ttl),
            )
            host_entry = replace(
                host_entry, device_class=_classify_device(host_entry),
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

    async def _run_active_probes(self, *, conn: Connection) -> None:
        """Three-phase active discovery, gated upstream by scene/env.

        Phase A — NBNS Status Query (unicast UDP 137) to every silent
        host (no Bonjour name, no reverse-DNS hostname).
        Phase B — SSDP M-SEARCH multicast (UDP 1900) once; replies
        merged into per-host upnp_* fields.
        Phase C — active mDNS browse-query via the BonjourPoller (the
        passive listener already captures responses).

        Phases A + B + C run concurrently via ``asyncio.gather``;
        the SSDP listen window (~3 s) is the wall-clock floor. Any
        single phase failure is swallowed — enrichments are best-
        effort.
        """
        from . import lan_probes as _lp  # local to keep top-level deps thin

        # Candidate hosts for NBNS: those with no friendly name yet.
        # Self / gateway are NOT excluded — Windows-flavoured gateways
        # (some H3C / TP-Link / Mikrotik) do reply to NBNS.
        nbns_targets: list[str] = []
        for mac_lc, h in self._state.items():
            if h.is_self:
                continue
            if h.bonjour_name or h.hostname:
                continue
            nbns_targets.append(h.ip)

        async def _nbns_phase() -> dict[str, str | None]:
            try:
                return await _lp.probe_nbns(nbns_targets)
            except Exception:
                return {ip: None for ip in nbns_targets}

        async def _ssdp_phase() -> dict[str, _lp.SSDPResponse]:
            try:
                results = await _lp.probe_ssdp()
            except Exception:
                return {}
            if not self._upnp_fetch_enabled:
                return results
            # Enrich each response with friendlyName + modelName
            # via the LOCATION fetch. Concurrent, fail-soft.
            async def _enrich(ip: str, r: _lp.SSDPResponse) -> tuple[
                str, _lp.SSDPResponse,
            ]:
                friendly, model = await _lp.fetch_upnp_location(r.location)
                from dataclasses import replace as _replace
                return ip, _replace(r, friendly_name=friendly, model_name=model)
            try:
                enriched = await asyncio.gather(
                    *[_enrich(ip, r) for ip, r in results.items()],
                    return_exceptions=True,
                )
            except Exception:
                return results
            out: dict[str, _lp.SSDPResponse] = dict(results)
            for entry in enriched:
                if isinstance(entry, tuple) and len(entry) == 2:
                    ip, r = entry
                    out[ip] = r
            return out

        async def _mdns_phase() -> None:
            if self._bonjour_poller is None:
                return
            try:
                self._bonjour_poller.send_meta_query()
            except Exception:
                pass

        nbns_results, ssdp_results, _ = await asyncio.gather(
            _nbns_phase(), _ssdp_phase(), _mdns_phase(),
            return_exceptions=False,
        )

        # Merge enrichments into the existing state entries. Look up
        # by IP since that's what the probes give us back.
        if nbns_results or ssdp_results:
            self._apply_probe_results(nbns_results, ssdp_results)

    def _apply_probe_results(
        self,
        nbns_results: dict[str, str | None],
        ssdp_results: dict[str, "_lp.SSDPResponse | None"],  # type: ignore[name-defined]
    ) -> None:
        """Merge probe enrichments into ``self._state``.

        Keyed by IP. Hosts that don't appear in either probe map are
        left untouched. Replaces the LANHost entry with an updated
        copy via ``dataclasses.replace`` to preserve immutability.
        """
        from dataclasses import replace
        # Build an IP → mac_lc lookup once.
        by_ip: dict[str, str] = {h.ip: mac_lc for mac_lc, h in self._state.items()}
        ips_touched: set[str] = set(nbns_results.keys()) | set(ssdp_results.keys())
        for ip in ips_touched:
            mac_lc = by_ip.get(ip)
            if mac_lc is None:
                continue
            host = self._state[mac_lc]
            nbns_name = nbns_results.get(ip)
            ssdp = ssdp_results.get(ip)
            new = replace(
                host,
                nbns_name=nbns_name if nbns_name else host.nbns_name,
                upnp_server=(
                    ssdp.server if ssdp and ssdp.server else host.upnp_server
                ),
                upnp_friendly_name=(
                    ssdp.friendly_name
                    if ssdp and ssdp.friendly_name
                    else host.upnp_friendly_name
                ),
                upnp_model=(
                    ssdp.model_name
                    if ssdp and ssdp.model_name
                    else host.upnp_model
                ),
            )
            # Re-classify now that the probe fields are populated —
            # rules like "Hikvision server header → camera" rely on
            # upnp_server / nbns_name that didn't exist at first-merge
            # time.
            self._state[mac_lc] = replace(
                new, device_class=_classify_device(new),
            )


def _sort_key(h: LANHost) -> tuple[int, int, tuple[int, ...]]:
    """Self → gateway → IP ascending."""
    rank = 0 if h.is_self else (1 if h.is_gateway else 2)
    try:
        ip_tuple = tuple(int(p) for p in h.ip.split("."))
    except ValueError:
        ip_tuple = (0, 0, 0, 0)
    return (rank, 0, ip_tuple)
