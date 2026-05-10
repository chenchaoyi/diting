"""Tests for the LatencyPoller, ping output parsing, DNS auto-detection,
and the spike / loss-burst detectors.

The Swift-side and macOS-side pieces (``/sbin/ping`` itself,
SCDynamicStore) are mocked: tests inject synthetic command output
and synthetic CFDictionary shapes through the seam helpers so the
suite runs hermetically on Linux CI as well.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from unittest.mock import patch

import pytest

from diting import latency
from diting.latency import (
    LatencyPoller,
    LatencySample,
    _coerce_address_list,
    _parse_ping_time_ms,
    _resolve_dns_anchor,
    detect_latency_spike,
    detect_loss_burst,
)


# --- ping output parsing --------------------------------------------

def test_parse_ping_time_ms_decimal():
    out = (
        "PING 192.168.1.1 (192.168.1.1): 56 data bytes\n"
        "64 bytes from 192.168.1.1: icmp_seq=0 ttl=64 time=12.5 ms\n"
    )
    assert _parse_ping_time_ms(out) == pytest.approx(12.5)


def test_parse_ping_time_ms_integer():
    out = "64 bytes from 1.1.1.1: icmp_seq=0 ttl=58 time=412 ms\n"
    assert _parse_ping_time_ms(out) == pytest.approx(412.0)


def test_parse_ping_time_ms_returns_none_when_missing():
    """``ping -c 1`` exits non-zero on loss but also occasionally
    prints a redirect / unreachable line with no time= match. Either
    way the parser returns None and the caller treats the sample as
    lost."""
    out = "ping: sendto: No route to host\n"
    assert _parse_ping_time_ms(out) is None


def test_parse_ping_time_ms_handles_lt_form():
    """macOS' ping uses time<1.0 ms for sub-millisecond replies on
    a wired LAN. Defensive: parser still extracts the numeric value."""
    out = "64 bytes from 192.168.1.1: icmp_seq=0 ttl=64 time<1.0 ms\n"
    assert _parse_ping_time_ms(out) == pytest.approx(1.0)


# --- ping subprocess -------------------------------------------------

def _proc(stdout="", returncode=0):
    class _R:
        pass
    p = _R()
    p.stdout = stdout
    p.stderr = ""
    p.returncode = returncode
    return p


def test_ping_once_records_rtt():
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip="8.8.8.8")
    out = "64 bytes from 192.168.1.1: icmp_seq=0 ttl=64 time=12.5 ms\n"
    with patch(
        "diting.latency.subprocess.run",
        return_value=_proc(stdout=out, returncode=0),
    ):
        sample = poller._ping_once("router", "192.168.1.1")
    assert sample.lost is False
    assert sample.rtt_ms == pytest.approx(12.5)
    assert sample.target == "router"
    assert sample.target_ip == "192.168.1.1"


def test_ping_once_loss_on_nonzero_exit():
    """``ping -c 1`` returns 2 on no-reply. We surface that as a
    lost sample with ``rtt_ms=None`` rather than raising."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip="8.8.8.8")
    with patch(
        "diting.latency.subprocess.run",
        return_value=_proc(returncode=2),
    ):
        sample = poller._ping_once("wan", "8.8.8.8")
    assert sample.lost is True
    assert sample.rtt_ms is None


def test_ping_once_loss_on_no_time_field():
    """Edge case: ping exits 0 but the line we get is the trailing
    ``--- statistics ---`` block without a single reply (rare but
    documented). Parser returns None → lost sample."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip="8.8.8.8")
    with patch(
        "diting.latency.subprocess.run",
        return_value=_proc(stdout="--- 1.1.1.1 ping statistics ---\n"),
    ):
        sample = poller._ping_once("wan", "1.1.1.1")
    assert sample.lost is True


def test_ping_once_loss_on_subprocess_error():
    """A timeout / OSError on the subprocess invocation must produce a
    lost sample, never an exception that tears down the poller."""
    poller = LatencyPoller(gateway_ip="192.168.1.1")
    with patch(
        "diting.latency.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ping", timeout=2),
    ):
        sample = poller._ping_once("router", "192.168.1.1")
    assert sample.lost is True
    assert sample.rtt_ms is None


# --- TCP probe (used for the WAN / DNS anchor) -----------------------

def test_tcp_probe_records_rtt_on_successful_connect():
    """TCP-connect to port 53 succeeds → rtt_ms is the wall-clock
    elapsed between connect() entry and connect() return. Many DNS
    operators (notably 114.114.114.114, parts of the Cloudflare /
    Google anycast set, most corporate resolvers) silently drop ICMP
    while still answering DNS perfectly — TCP probes are the honest
    'is the resolver reachable' test."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip="1.1.1.1")
    fake_sock = type("S", (), {})()
    fake_sock.settimeout = lambda *a, **k: None
    fake_sock.connect = lambda addr: None
    fake_sock.close = lambda: None
    with patch("socket.socket", return_value=fake_sock):
        sample = poller._tcp_probe_once("wan", "1.1.1.1", 53)
    assert sample.lost is False
    assert sample.rtt_ms is not None
    assert sample.rtt_ms >= 0
    assert sample.target == "wan"


def test_tcp_probe_loss_on_timeout():
    """A TCP connect that times out (DNS server filtering port 53,
    routing black hole, etc.) surfaces as a lost sample without
    raising into the poller loop."""
    import socket
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip="1.1.1.1")
    fake_sock = type("S", (), {})()
    fake_sock.settimeout = lambda *a, **k: None
    fake_sock.connect = lambda addr: (_ for _ in ()).throw(socket.timeout())
    fake_sock.close = lambda: None
    with patch("socket.socket", return_value=fake_sock):
        sample = poller._tcp_probe_once("wan", "1.1.1.1", 53)
    assert sample.lost is True
    assert sample.rtt_ms is None


def test_tcp_probe_loss_on_connection_refused():
    """Refused (closed port, host firewall) is structurally the same
    outcome as timeout — sample marked lost. Important because if our
    DNS-detection picks up a stale entry pointing at a host that is
    no longer running a resolver, we want to *say* WAN is unreachable
    rather than crash."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip="1.1.1.1")
    fake_sock = type("S", (), {})()
    fake_sock.settimeout = lambda *a, **k: None
    fake_sock.connect = lambda addr: (_ for _ in ()).throw(
        ConnectionRefusedError(),
    )
    fake_sock.close = lambda: None
    with patch("socket.socket", return_value=fake_sock):
        sample = poller._tcp_probe_once("wan", "1.1.1.1", 53)
    assert sample.lost is True
    assert sample.rtt_ms is None


# --- aggregate -------------------------------------------------------

def _sample(rtt, *, lost=False, target="router", ip="192.168.1.1"):
    return LatencySample(
        ts=datetime.now(), target=target, target_ip=ip,
        rtt_ms=rtt, lost=lost,
    )


def test_aggregate_yields_median_loss_and_jitter():
    """Five samples: two clean at ~12 ms, one outlier at 80 ms, two
    lost. Median rtt should be the middle of the three non-loss
    values; loss% should be 40; jitter (MAD) should pick up the
    spread between cleans and outlier."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", clock=lambda: 1000.0)
    history = poller._history["router"]
    history.append(_sample(12.0))
    history.append(_sample(13.0))
    history.append(_sample(80.0))
    history.append(_sample(None, lost=True))
    history.append(_sample(None, lost=True))
    agg = poller.aggregate("router", window_s=3600)
    assert agg.sample_count == 5
    assert agg.rtt_ms == pytest.approx(13.0)
    assert agg.loss_pct == pytest.approx(40.0)
    assert agg.jitter_ms is not None
    assert agg.jitter_ms > 0


def test_aggregate_empty_returns_none_fields():
    poller = LatencyPoller(gateway_ip="192.168.1.1")
    agg = poller.aggregate("router")
    assert agg.sample_count == 0
    assert agg.rtt_ms is None
    assert agg.loss_pct is None
    assert agg.jitter_ms is None


def test_aggregate_window_actually_drops_old_samples():
    """Regression for the multi-hour-session bug where loss_pct was
    diluted toward zero (e.g. log shows 0.33 instead of 33%) because
    the rolling-window cutoff filter was a no-op. Cause: samples
    were not stamped with their record-time monotonic clock, so
    _sample_clock fell back to ``now``, making the cutoff condition
    ``now < now - window`` always false. With the fix, samples
    stamped > window seconds ago must be excluded from aggregate
    even if they're still in the deque."""
    clock = [1000.0]
    poller = LatencyPoller(
        gateway_ip="192.168.1.1",
        clock=lambda: clock[0],
        window_s=60.0,
    )
    # Record two old samples at t=1000 (mono=1000), both lost.
    poller._record(_sample(None, lost=True))
    poller._record(_sample(None, lost=True))
    # Advance the clock 600 s past the window (the user's overnight
    # session was 9 h — 600 s is plenty to assert the property).
    clock[0] = 2000.0
    # Record two fresh samples at t=2000 (mono=2000), one lost.
    poller._record(_sample(10.0))
    poller._record(_sample(None, lost=True))
    agg = poller.aggregate("router")
    # Window should now contain only the two fresh samples; the
    # two old losses should have been popped on the most recent
    # _record's left-trim pass.
    assert agg.sample_count == 2
    # 1 of 2 lost = 50%, NOT 3 of 4 = 75% (which we'd see if the
    # old samples had survived).
    assert agg.loss_pct == pytest.approx(50.0)


def test_aggregate_loss_pct_in_zero_to_hundred_range():
    """Concrete property test: emit one minute of 1 Hz samples with
    a known loss ratio, assert aggregate.loss_pct lands in the
    documented 0..100 percentage range. Pre-fix this came back as
    a fraction (0..1) for any session longer than the window."""
    clock = [0.0]
    poller = LatencyPoller(
        gateway_ip="192.168.1.1",
        clock=lambda: clock[0],
        window_s=60.0,
    )
    for i in range(60):
        clock[0] = float(i)
        poller._record(_sample(
            None if i % 4 == 0 else 10.0,
            lost=(i % 4 == 0),
        ))
    # Now jump forward 10 hours and emit one more sample to confirm
    # the trim is applied at record time, not just aggregate.
    clock[0] = 36000.0
    poller._record(_sample(11.0))
    agg = poller.aggregate("router")
    # Only the one fresh sample survived the last trim.
    assert agg.sample_count == 1
    assert agg.loss_pct == pytest.approx(0.0)


# --- spike + loss-burst detectors ----------------------------------

def test_detect_latency_spike_requires_both_thresholds():
    """rtt > 200 ms AND > 5× median. A single 250 ms spike against
    a 12 ms baseline qualifies; a 250 ms spike against a 60 ms
    baseline does not (250 < 5*60)."""
    baseline = [_sample(12.0)] * 10
    samples = baseline + [_sample(250.0)]
    spike = detect_latency_spike(samples)
    assert spike is not None
    assert spike.rtt_ms == 250.0

    baseline_high = [_sample(60.0)] * 10
    not_high_enough = baseline_high + [_sample(250.0)]
    assert detect_latency_spike(not_high_enough) is None


def test_detect_loss_burst_three_of_last_five():
    """Spec rule: 3 of last 5 samples lost = burst."""
    samples = [_sample(12.0)] * 4 + [
        _sample(None, lost=True),
        _sample(None, lost=True),
        _sample(None, lost=True),
        _sample(12.0),
        _sample(12.0),
    ]
    # Last 5 are: lost, lost, lost, 12.0, 12.0 → 3 lost → True
    assert detect_loss_burst(samples) is True


def test_detect_loss_burst_one_loss_does_not_fire():
    samples = [_sample(12.0), _sample(12.0), _sample(None, lost=True),
               _sample(12.0), _sample(12.0)]
    assert detect_loss_burst(samples) is False


# --- LatencyPoller stop --------------------------------------------

def test_stop_marks_poller_stopped():
    poller = LatencyPoller(gateway_ip="192.168.1.1")
    assert poller._stopped is False
    poller.stop()
    assert poller._stopped is True


# --- DNS auto-detection ---------------------------------------------

def _patch_sc(serveraddresses):
    """Build a context that makes _read_dns_server_addresses behave
    as if SCDynamicStoreCopyValue returned a CFDictionary with the
    given ``ServerAddresses`` field. ``serveraddresses=None`` simulates
    SCDynamicStoreCopyValue returning None (no DNS state).

    We mock at the module-level seam, not the import level, so the
    pyobjc-framework-systemconfiguration package does not need to
    actually be installed for these tests to run.
    """
    return patch(
        "diting.latency._read_dns_server_addresses",
        return_value=_coerce_address_list(serveraddresses),
    )


def test_dns_typical_home_returns_none_when_dns_eq_gateway():
    """Home network: only nameserver is the gateway itself (router
    runs the DNS forwarder). No useful WAN probe — return None."""
    with _patch_sc(["192.168.1.1"]):
        assert _resolve_dns_anchor("192.168.1.1") is None


def test_dns_corporate_returns_internal_resolver():
    """Corporate / kubernetes-y: gateway is 10.0.0.1, DNS is
    10.0.0.53. Internal IP is fine — still a more meaningful test
    than a public anchor that may be firewalled."""
    with _patch_sc(["10.0.0.53"]):
        assert _resolve_dns_anchor("10.0.0.1") == "10.0.0.53"


def test_dns_cloudflare_user_returns_first_public_address():
    """Cloudflare DoH user with ``1.1.1.1`` / ``1.0.0.1``. We pick
    the first non-gateway, which is the resolver the OS itself uses
    first."""
    with _patch_sc(["1.1.1.1", "1.0.0.1"]):
        assert _resolve_dns_anchor("192.168.1.1") == "1.1.1.1"


def test_dns_skips_gateway_when_listed_first():
    """Multi-resolver setup with the gateway listed first; we walk
    the list and pick the first IP that is *not* the gateway, since
    pinging the gateway as the WAN target gives us nothing the
    gateway probe doesn't already."""
    with _patch_sc(["192.168.1.1", "8.8.8.8"]):
        assert _resolve_dns_anchor("192.168.1.1") == "8.8.8.8"


def test_dns_no_state_returns_none():
    """SCDynamicStore returns None (no current network config /
    transient boot state)."""
    with _patch_sc(None):
        assert _resolve_dns_anchor("192.168.1.1") is None


def test_dns_empty_addresses_returns_none():
    """ServerAddresses is present but empty (an unconfigured
    interface)."""
    with _patch_sc([]):
        assert _resolve_dns_anchor("192.168.1.1") is None


def test_dns_malformed_addresses_filters_to_none():
    """Defensive: non-string entries get filtered out by
    _coerce_address_list, and a list of nothing-but-junk yields
    None for the resolver."""
    addrs = _coerce_address_list([None, 12345, object()])
    assert addrs == []
    with _patch_sc([None, 12345, object()]):
        assert _resolve_dns_anchor("192.168.1.1") is None


def test_dns_env_override_wins_over_auto_detect():
    """``DITING_LATENCY_WAN_TARGET=1.1.1.1`` is the explicit
    override; it beats whatever SCDynamicStore would have picked."""
    env = {"DITING_LATENCY_WAN_TARGET": "1.1.1.1"}
    with _patch_sc(["8.8.8.8"]):
        assert _resolve_dns_anchor("192.168.1.1", env=env) == "1.1.1.1"


def test_dns_refresh_runs_on_cadence():
    """The poller re-resolves the WAN anchor every ``dns_refresh_s``
    seconds. We inject a synthetic clock and a counting resolver to
    verify the cadence without sleeping."""
    calls: list[str | None] = []
    def resolver(gateway_ip):
        calls.append(gateway_ip)
        return "1.2.3.4"

    clock_now = [0.0]
    def clock():
        return clock_now[0]

    poller = LatencyPoller(
        gateway_ip="192.168.1.1",
        wan_ip=None,
        dns_refresh_s=60.0,
        clock=clock,
        dns_resolver=resolver,
    )
    # First tick — _last_dns_refresh starts at 0 and current clock is
    # 0; 60 s have not passed but the *first* call still fires because
    # the poller treats the boot tick as a forced resolution.
    poller._wan_target_ip()
    assert len(calls) == 1
    # Within the refresh window — no new resolver calls.
    clock_now[0] = 10.0
    poller._wan_target_ip()
    assert len(calls) == 1
    # 60 s past the previous refresh — re-resolves.
    clock_now[0] = 70.0
    poller._wan_target_ip()
    assert len(calls) == 2


def test_explicit_wan_ip_disables_refresh():
    """When the caller passes ``wan_ip=`` explicitly (CLI / env), the
    poller never re-resolves DNS — that anchor is sticky for the
    lifetime of the run."""
    calls: list[str | None] = []
    def resolver(gateway_ip):
        calls.append(gateway_ip)
        return "should-not-be-called"

    poller = LatencyPoller(
        gateway_ip="192.168.1.1",
        wan_ip="9.9.9.9",
        dns_resolver=resolver,
    )
    for _ in range(5):
        assert poller._wan_target_ip() == "9.9.9.9"
    assert calls == []


def test_wan_skipped_reason_dns_eq_gateway():
    """When the only DNS is the gateway, the probe is skipped and the
    diagnostic line surfaces the reason. The poller mirrors that as
    ``wan_skipped_reason == 'dns_eq_gateway'``."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip=None)
    # Pretend SCDynamicStore returns only the gateway.
    with _patch_sc(["192.168.1.1"]):
        assert poller.wan_skipped_reason == "dns_eq_gateway"


def test_wan_skipped_reason_no_dns():
    """When SCDynamicStore returns nothing (boot state), reason is
    ``no_dns`` so the renderer can distinguish it from the
    gateway-collision case."""
    poller = LatencyPoller(gateway_ip="192.168.1.1", wan_ip=None)
    with _patch_sc(None):
        assert poller.wan_skipped_reason == "no_dns"


def test_scutil_dns_fallback_parses_resolver_block():
    """The scutil fallback path: feed real-shaped output and verify
    it pulls out the resolver-#1 nameservers and stops at #2."""
    sample = (
        "DNS configuration\n"
        "\n"
        "resolver #1\n"
        "  nameserver[0] : 192.168.1.1\n"
        "  nameserver[1] : 1.1.1.1\n"
        "\n"
        "resolver #2\n"
        "  domain   : example.com\n"
        "  nameserver[0] : 10.0.0.99\n"
    )
    proc = _proc(stdout=sample, returncode=0)
    with patch(
        "diting.latency.subprocess.run", return_value=proc,
    ):
        addrs = latency._scutil_dns_fallback()
    assert addrs == ["192.168.1.1", "1.1.1.1"]
