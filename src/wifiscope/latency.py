"""ICMP latency / loss probe + WAN-anchor auto-detection.

The probe answers a question that RSSI alone cannot: *is the link
actually working*? RSSI of -55 dBm is meaningless if the AP is
queueing packets, the gateway is wedged, or DNS / upstream is broken.
We probe two targets at 1 Hz with the system ``/sbin/ping`` binary —
no raw socket, no sudo, no PyObjC — and surface a rolling-window
aggregate (median / loss% / jitter) for the Diagnostics panel along
with raw samples for the events pipeline's spike detector.

Targets
-------

The two probe targets are:

1. **Gateway** — the user's default-route IP, exposed by the
   :class:`WiFiBackend` as ``Connection.router_ip``. This catches
   AP / wired-uplink hangs.

2. **WAN anchor** — the system's currently-configured DNS server,
   auto-detected via ``SCDynamicStoreCopyValue("State:/Network/Global/DNS")``
   or read straight from ``scutil --dns`` as a subprocess fallback.
   The DNS server is the operationally-meaningful upstream test:
   it is the one IP the OS itself queries on every name resolution,
   it works behind corporate firewalls that block public anchors
   like ``1.1.1.1``, and it stays correct across location changes
   (home → corporate → VPN → tethered).

Resolution order for the WAN anchor:

1. The ``WIFISCOPE_LATENCY_WAN_TARGET`` environment variable
   (explicit override).
2. The first SCDynamicStore-reported nameserver whose IP is **not**
   equal to the detected gateway. (Private vs public IP makes no
   difference — many corporate networks route DNS through an
   internal IP, which is still a more meaningful test than a
   public anchor that may be blocked.)
3. None — when the only configured DNS is the gateway itself, or
   when SCDynamicStore returns no DNS state. In that case the
   Diagnostics line reads ``Link gw 12 ms · 0% loss · WAN n/a (DNS
   == gateway)`` and only the gateway probe runs.

DNS detection re-runs every 60 s so a network switch updates the
anchor without restarting wifiscope.
"""

from __future__ import annotations

import asyncio
import os
import re
import statistics
import subprocess
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

# ``time=12.5 ms`` / ``time=412 ms`` / ``time=0.123 ms`` shapes from
# the macOS ``/sbin/ping`` text output. Decimal optional.
_TIME_RX = re.compile(r"time[=<]([0-9]+(?:\.[0-9]+)?)\s*ms")

# Spike detection thresholds — fired by the events pipeline, not by
# the poller itself. Documented in the spec.
LATENCY_SPIKE_RTT_MS = 200.0
LATENCY_SPIKE_RATIO = 5.0
LOSS_BURST_LOOKBACK = 5
LOSS_BURST_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class LatencySample:
    """One ping reply (or one observed loss).

    ``target`` is the role label (``"router"`` / ``"wan"``) and
    ``target_ip`` is the IP that was actually probed. They are
    surfaced separately so the renderer can show a friendly column
    name even after a network switch swaps the underlying IP.

    ``mono`` is the monotonic clock at record time, used by the
    aggregator's rolling-window cutoff. Producers leave it as
    ``None``; :meth:`LatencyPoller._record` rebuilds the sample
    with the current monotonic clock before storing so the cutoff
    math works on real samples. ``None`` is a real sentinel
    (rather than 0.0) because fake test clocks legitimately read
    0.0, and we must not confuse that with "unstamped".
    """
    ts: datetime
    target: str
    target_ip: str
    rtt_ms: float | None
    lost: bool
    mono: float | None = None


@dataclass(frozen=True, slots=True)
class LatencyAggregate:
    """Rolling-window summary for one target.

    All fields are computed over the last ``window_s`` seconds of
    samples. ``rtt_ms`` is the median of successful samples;
    ``loss_pct`` is the fraction of samples that were lost (0..100);
    ``jitter_ms`` is the median absolute deviation of the rtt
    distribution (more robust than stddev to single-spike outliers).
    Empty windows yield ``None`` for every field.
    """
    target: str
    target_ip: str | None
    rtt_ms: float | None
    loss_pct: float | None
    jitter_ms: float | None
    sample_count: int


def _resolve_dns_anchor(
    gateway_ip: str | None,
    *,
    env: dict[str, str] | None = None,
) -> str | None:
    """Pick the WAN anchor IP, applying the documented resolution order.

    Pure function; no side effects on the dynamic store. ``env`` is
    plumbed in so tests can inject a synthetic environment without
    touching ``os.environ``.
    """
    src = os.environ if env is None else env
    override = (src.get("WIFISCOPE_LATENCY_WAN_TARGET") or "").strip()
    if override:
        return override

    addresses = _read_dns_server_addresses()
    if not addresses:
        return None
    gw = (gateway_ip or "").strip()
    for addr in addresses:
        if not isinstance(addr, str):
            continue
        if not addr:
            continue
        if addr == gw:
            continue
        return addr
    return None


def _read_dns_server_addresses() -> list[str]:
    """Read ``State:/Network/Global/DNS`` ServerAddresses via PyObjC.

    Falls through to ``scutil --dns`` parsing when the dynamic store
    is unavailable (Linux test environment, or a transient SC
    failure). Either path returns a list of stringly-typed IPs;
    malformed entries are skipped, never raised.
    """
    try:
        from SystemConfiguration import (
            SCDynamicStoreCopyValue,
            SCDynamicStoreCreate,
        )
    except Exception:
        return _scutil_dns_fallback()
    try:
        ds = SCDynamicStoreCreate(None, "wifiscope-latency", None, None)
    except Exception:
        ds = None
    if ds is None:
        return _scutil_dns_fallback()
    try:
        val = SCDynamicStoreCopyValue(ds, "State:/Network/Global/DNS")
    except Exception:
        val = None
    if val is None:
        return []
    try:
        addrs = val.get("ServerAddresses")
    except Exception:
        return []
    return _coerce_address_list(addrs)


def _coerce_address_list(addrs) -> list[str]:
    """Filter a CF/NS array of nameserver addresses to a clean list[str].

    ``addrs`` may be a real list, an NSArray-like proxy (CFArray),
    None, a string, or anything else macOS happens to hand back —
    defensive iteration keeps us from raising on the malformed
    cases. Non-string entries are silently skipped.
    """
    if addrs is None:
        return []
    out: list[str] = []
    try:
        for item in addrs:
            if isinstance(item, str) and item:
                out.append(item)
    except TypeError:
        return []
    return out


def _scutil_dns_fallback() -> list[str]:
    """Parse ``scutil --dns`` output for the resolver #1 nameservers.

    macOS' ``scutil --dns`` reads from the same SCDynamicStore key
    we tried first; it is the documented user-facing tool for this
    information and the format is stable across releases. We pluck
    nameservers from the first ``resolver #1`` block only, since the
    later blocks are scoped resolvers (e.g. one per VPN tunnel).
    """
    try:
        proc = subprocess.run(
            ["/usr/sbin/scutil", "--dns"],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    out: list[str] = []
    in_first_resolver = False
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("resolver #1"):
            in_first_resolver = True
            continue
        if stripped.startswith("resolver #"):
            # We are now past resolver #1; stop collecting.
            break
        if in_first_resolver and stripped.startswith("nameserver["):
            # Lines look like ``nameserver[0] : 192.168.1.1``.
            _, _, ip = stripped.partition(":")
            ip = ip.strip()
            if ip:
                out.append(ip)
    return out


def _parse_ping_time_ms(stdout: str) -> float | None:
    """Pull the first ``time=N ms`` value from a ``ping -c 1`` reply.

    Returns ``None`` if the output has no ``time=`` line (which is
    how macOS ``/sbin/ping`` reports a lost packet on a non-zero
    exit; we treat the absence of a parse as loss).
    """
    m = _TIME_RX.search(stdout)
    if m is None:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


class LatencyPoller:
    """Spawns one ``/sbin/ping -c 1 -W 1 -t 1 <ip>`` per target per
    second, emits a stream of :class:`LatencySample`, and maintains
    a 60 s rolling history per target.

    The TUI's Diagnostics panel reads :meth:`aggregate` for the
    rendered numbers; the events pipeline reads raw samples for
    spike detection.

    DNS auto-detection re-runs every ``dns_refresh_s`` seconds.
    Pass ``wan_ip=`` to bypass detection entirely (the CLI's
    ``--wan`` flag and ``WIFISCOPE_LATENCY_WAN_TARGET`` env var both
    route through here).
    """

    def __init__(
        self,
        *,
        gateway_ip: str | None,
        wan_ip: str | None = None,
        interval_s: float = 1.0,
        dns_refresh_s: float = 60.0,
        window_s: float = 60.0,
        ping_path: str = "/sbin/ping",
        clock: Callable[[], float] | None = None,
        dns_resolver: Callable[[str | None], str | None] | None = None,
    ) -> None:
        self._gateway_ip = gateway_ip
        # ``wan_explicit`` records whether the caller pinned the WAN
        # anchor (CLI / env override). When True we skip auto-detect
        # entirely; when False we re-resolve every ``dns_refresh_s``.
        self._wan_explicit = wan_ip is not None
        self._wan_ip = wan_ip
        self._interval_s = interval_s
        self._dns_refresh_s = dns_refresh_s
        self._window_s = window_s
        self._ping_path = ping_path
        self._clock = clock or time.monotonic
        self._dns_resolver = dns_resolver or _resolve_dns_anchor
        self._queue: asyncio.Queue[LatencySample] = asyncio.Queue()
        # Per-target rolling sample history. The right end is the
        # newest. We trim from the left whenever a sample older than
        # ``window_s`` falls off; this keeps memory bounded at one
        # sample per second per target × window.
        self._history: dict[str, deque[LatencySample]] = {
            "router": deque(),
            "wan": deque(),
        }
        self._tasks: list[asyncio.Task] = []
        self._stopped = False
        # ``None`` means "have not resolved DNS yet"; the first call
        # to ``_wan_target_ip`` triggers a resolution unconditionally.
        # Subsequent calls observe the cadence boundary at
        # ``dns_refresh_s`` seconds.
        self._last_dns_refresh: float | None = None

    async def events(self) -> AsyncIterator[LatencySample]:
        """Drain the sample stream until :meth:`stop` is called.

        Like :class:`WiFiPoller.events`, single-use: call once and
        iterate. On generator close the per-target probe tasks are
        cancelled and awaited.
        """
        loop = asyncio.get_running_loop()
        if self._gateway_ip:
            self._tasks.append(
                loop.create_task(
                    self._probe_loop("router", lambda: self._gateway_ip),
                    name="latency-gw",
                )
            )
        # The WAN target is dynamic — _wan_target_ip() resolves the
        # current anchor on each tick, so a network switch updates
        # the probe target without restarting the poller.
        self._tasks.append(
            loop.create_task(
                self._probe_loop("wan", self._wan_target_ip),
                name="latency-wan",
            )
        )
        try:
            while not self._stopped:
                yield await self._queue.get()
        finally:
            self.stop()
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def aggregate(self, target: str, window_s: float | None = None) -> LatencyAggregate:
        """Median / loss% / jitter over the rolling window for ``target``.

        ``window_s`` defaults to the constructor's ``window_s``
        (60 s). Returning a dataclass rather than a dict keeps the
        TUI's renderer typed; loss is in 0..100 percent (not 0..1)
        so the format string can drop the multiplication.
        """
        history = self._history.get(target)
        target_ip = self._gateway_ip if target == "router" else self._wan_ip
        if not history:
            return LatencyAggregate(
                target=target, target_ip=target_ip,
                rtt_ms=None, loss_pct=None, jitter_ms=None, sample_count=0,
            )
        window = window_s if window_s is not None else self._window_s
        cutoff = self._clock() - window
        samples = [s for s in history if self._sample_clock(s) >= cutoff]
        if not samples:
            return LatencyAggregate(
                target=target, target_ip=target_ip,
                rtt_ms=None, loss_pct=None, jitter_ms=None, sample_count=0,
            )
        rtts = [s.rtt_ms for s in samples if s.rtt_ms is not None]
        lost = sum(1 for s in samples if s.lost)
        loss_pct = 100.0 * lost / len(samples)
        if rtts:
            median = statistics.median(rtts)
            mad = statistics.median([abs(r - median) for r in rtts]) if len(rtts) > 1 else 0.0
        else:
            median = None
            mad = None
        return LatencyAggregate(
            target=target,
            target_ip=samples[-1].target_ip,
            rtt_ms=median,
            loss_pct=loss_pct,
            jitter_ms=mad,
            sample_count=len(samples),
        )

    def stop(self) -> None:
        self._stopped = True

    @property
    def gateway_ip(self) -> str | None:
        return self._gateway_ip

    @property
    def wan_ip(self) -> str | None:
        return self._wan_ip

    @property
    def wan_skipped_reason(self) -> str | None:
        """Why we are not running a WAN probe right now, or None.

        ``"no_dns"`` — SCDynamicStore returned nothing.
        ``"dns_eq_gateway"`` — the only configured DNS is the gateway.
        Used by the Diagnostics panel to render
        ``WAN n/a (DNS == gateway)`` instead of leaving the user
        guessing.
        """
        if self._wan_ip is not None:
            return None
        if self._gateway_ip is None:
            return "no_dns"
        addresses = _read_dns_server_addresses()
        if not addresses:
            return "no_dns"
        # If the only address is the gateway, that's the dns_eq_gateway
        # case; otherwise we expect _wan_ip to be set by now.
        non_gateway = [a for a in addresses if a != self._gateway_ip]
        if not non_gateway:
            return "dns_eq_gateway"
        return None

    def detect_initial_wan(self) -> None:
        """Resolve the WAN anchor once before :meth:`events` is called.

        Useful for synchronous diagnostics rendering during startup
        when the caller wants the probe IP up front, before waiting
        for the first refresh tick. No-op when the WAN target was
        pinned by env / CLI override.
        """
        if self._wan_explicit:
            return
        self._wan_ip = self._dns_resolver(self._gateway_ip)
        self._last_dns_refresh = self._clock()

    def _wan_target_ip(self) -> str | None:
        """Resolve the WAN target for the next tick.

        Re-runs the DNS detection every ``dns_refresh_s`` seconds
        unless the caller pinned the anchor with an explicit IP.
        """
        if self._wan_explicit:
            return self._wan_ip
        now = self._clock()
        if (
            self._last_dns_refresh is None
            or now - self._last_dns_refresh >= self._dns_refresh_s
        ):
            self._wan_ip = self._dns_resolver(self._gateway_ip)
            self._last_dns_refresh = now
        return self._wan_ip

    async def _probe_loop(self, target: str, ip_fn: Callable[[], str | None]) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopped:
            ip = ip_fn()
            if ip is None:
                # No probe target this tick (e.g. WAN==gateway path,
                # or pre-association gateway). Sleep an interval so
                # the loop does not busy-wait, and pick up the new
                # value on the next pass.
                await asyncio.sleep(self._interval_s)
                continue
            if target == "wan":
                # The WAN anchor is a DNS server. DNS servers MUST listen
                # on TCP 53 to answer queries — but ICMP is an
                # optional courtesy that many DNS operators (notably
                # 114.114.114.114, parts of 1.1.1.1 anycast, most
                # corporate resolvers) deliberately drop. A TCP-connect
                # probe answers the right question — "can my Mac reach
                # this DNS" — and produces an honest RTT from the
                # SYN/ACK handshake. It also avoids the macOS ping
                # binary's BSD-flavour quirks entirely.
                sample = await loop.run_in_executor(
                    None, self._tcp_probe_once, target, ip, 53,
                )
            else:
                # Gateway probe stays on ICMP — home / office routers
                # almost always respond to ping, and they may or may
                # not listen on any specific TCP port.
                sample = await loop.run_in_executor(
                    None, self._ping_once, target, ip,
                )
            self._record(sample)
            await self._queue.put(sample)
            await asyncio.sleep(self._interval_s)

    def _ping_once(self, target: str, ip: str) -> LatencySample:
        """Fork-and-wait one ``ping -c 1 -W 1000 -t 64 <ip>`` call.

        macOS' ``-W`` is in milliseconds (1 ms is meaningless); we pass
        1000 so a network outage caps the call at ~1 s. ``-t`` is the
        IP TTL, not a time bound.
        """
        ts = datetime.now()
        try:
            proc = subprocess.run(
                [self._ping_path, "-c", "1", "-W", "1000", "-t", "64", ip],
                capture_output=True, text=True, timeout=2.0, check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return LatencySample(
                ts=ts, target=target, target_ip=ip,
                rtt_ms=None, lost=True,
            )
        if proc.returncode != 0:
            return LatencySample(
                ts=ts, target=target, target_ip=ip,
                rtt_ms=None, lost=True,
            )
        rtt = _parse_ping_time_ms(proc.stdout)
        if rtt is None:
            return LatencySample(
                ts=ts, target=target, target_ip=ip,
                rtt_ms=None, lost=True,
            )
        return LatencySample(
            ts=ts, target=target, target_ip=ip,
            rtt_ms=rtt, lost=False,
        )

    def _tcp_probe_once(
        self, target: str, ip: str, port: int,
    ) -> LatencySample:
        """TCP-connect probe with millisecond-precision RTT.

        Times the SYN/ACK handshake and records the elapsed time as
        rtt_ms. Connection failure / refusal / timeout all surface as
        loss. The 1.0 s timeout matches the ICMP path's per-call cap
        so the diagnostic-panel cadence stays even.
        """
        import socket
        ts = datetime.now()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        start = time.monotonic()
        try:
            sock.connect((ip, port))
        except (socket.timeout, OSError):
            return LatencySample(
                ts=ts, target=target, target_ip=ip,
                rtt_ms=None, lost=True,
            )
        finally:
            try:
                sock.close()
            except OSError:
                pass
        rtt_ms = (time.monotonic() - start) * 1000.0
        return LatencySample(
            ts=ts, target=target, target_ip=ip,
            rtt_ms=rtt_ms, lost=False,
        )

    def _record(self, sample: LatencySample) -> None:
        history = self._history.setdefault(sample.target, deque())
        # Stamp the sample with the current monotonic clock at
        # record time so the cutoff filter has something
        # non-degenerate to compare against. Earlier versions
        # tried to setattr a hidden attribute on a frozen+slots
        # LatencySample, which silently no-op'd — _sample_clock
        # then fell back to "now", which made the cutoff condition
        # ``now < now - window`` always false and let the window
        # grow to the full session history. With a multi-hour
        # run, aggregate.loss_pct diluted toward zero (loss /
        # session_total instead of loss / last_60s).
        sample = replace(sample, mono=self._clock())
        history.append(sample)
        cutoff = self._clock() - self._window_s
        while history and self._sample_clock(history[0]) < cutoff:
            history.popleft()

    def _sample_clock(self, sample: LatencySample) -> float:
        """Monotonic clock at sample-record time.

        ``LatencySample.ts`` is a :class:`~datetime.datetime` for
        operator display; window math wants a monotonic clock so a
        system-time hop (NTP step, lid-close suspend) does not
        corrupt the rolling window. ``mono`` is filled in by
        :meth:`_record`; synthetic samples that bypass _record
        (rare — some tests construct samples directly into
        ``_history``) fall back to "now" so the old behaviour is
        preserved for them.
        """
        return self._clock() if sample.mono is None else sample.mono


def detect_latency_spike(
    samples: list[LatencySample],
    *,
    rtt_ms: float = LATENCY_SPIKE_RTT_MS,
    ratio: float = LATENCY_SPIKE_RATIO,
) -> LatencySample | None:
    """Return the most recent sample that crosses both spike thresholds.

    Spike := rtt > ``rtt_ms`` AND rtt > ``ratio`` × the rolling
    median of all observed rtts in ``samples``. Loss-only samples
    are ignored (they belong to :func:`detect_loss_burst`).
    """
    rtts = [s.rtt_ms for s in samples if s.rtt_ms is not None]
    if not rtts:
        return None
    median = statistics.median(rtts)
    if median <= 0:
        return None
    threshold = max(rtt_ms, ratio * median)
    for sample in reversed(samples):
        if sample.rtt_ms is None:
            continue
        if sample.rtt_ms > threshold:
            return sample
    return None


def detect_loss_burst(
    samples: list[LatencySample],
    *,
    lookback: int = LOSS_BURST_LOOKBACK,
    threshold: int = LOSS_BURST_THRESHOLD,
) -> bool:
    """Return True when ``threshold`` of the last ``lookback`` samples were lost.

    Default 3-of-5: catches sustained dropouts without firing on a
    single transient lost packet (which is normal background noise
    on a busy gateway). Used by the events pipeline to emit
    ``loss_burst`` event lines.
    """
    if len(samples) < lookback:
        return False
    window = samples[-lookback:]
    return sum(1 for s in window if s.lost) >= threshold
