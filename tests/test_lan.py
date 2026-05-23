"""Unit tests for the LAN inventory module."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from diting.lan import (
    LANHost,
    LANInventoryPoller,
    LANInventoryUpdate,
    _build_bonjour_index,
    _detect_subnet,
    _effective_cap_prefix,
    _is_randomised_mac,
    _parse_ifconfig_netmask,
    _ping_one,
    _read_arp_cache,
    _strip_local_suffix,
    _sweep,
)
from diting.mdns import BonjourDevice, BonjourPoller
from diting.models import Connection


# ---------- _is_randomised_mac ----------

def test_is_randomised_mac_detects_locally_administered_bit():
    # Bit 0x02 of first octet set → locally administered.
    assert _is_randomised_mac("02:11:22:33:44:55") is True
    assert _is_randomised_mac("aa:bb:cc:dd:ee:ff") is True
    assert _is_randomised_mac("AA:BB:CC:DD:EE:FF") is True
    # 0x06 = 0b0110, bit 0x02 is set → locally administered (and
    # multicast bit 0x01 clear → still a valid unicast MAC).
    assert _is_randomised_mac("06:00:00:00:00:01") is True


def test_is_randomised_mac_clears_for_universal_macs():
    # Real Apple OUI 84:2f:57, first octet 0x84 = 0b10000100, bit 0x02 clear.
    assert _is_randomised_mac("84:2f:57:9b:15:59") is False
    # TP-Link 50:c7:bf, first octet 0x50 = 0b01010000, bit 0x02 clear.
    assert _is_randomised_mac("50:c7:bf:11:22:33") is False
    # 0x00 = all clear.
    assert _is_randomised_mac("00:11:22:33:44:55") is False


def test_is_randomised_mac_returns_false_on_garbage():
    assert _is_randomised_mac("not-a-mac") is False
    assert _is_randomised_mac("") is False


# ---------- _parse_ifconfig_netmask ----------

_IFCONFIG_TYPICAL_HOME = """\
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 84:2f:57:9b:15:59
\tinet6 fe80::1cce:1d2c:14a4:db1c%en0 prefixlen 64 secured scopeid 0x4
\tinet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255
\tnd6 options=201<PERFORMNUD,DAD>
\tmedia: autoselect
\tstatus: active
"""

_IFCONFIG_CORPORATE_16 = """\
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 84:2f:57:9b:15:59
\tinet 10.5.7.42 netmask 0xffff0000 broadcast 10.5.255.255
\tnd6 options=201<PERFORMNUD,DAD>
"""

_IFCONFIG_NATIVE_22 = """\
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 84:2f:57:9b:15:59
\tinet 192.168.4.42 netmask 0xfffffc00 broadcast 192.168.7.255
"""

_IFCONFIG_NARROW_26 = """\
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 84:2f:57:9b:15:59
\tinet 192.168.1.10 netmask 0xffffffc0 broadcast 192.168.1.63
"""


def test_parse_ifconfig_netmask_typical_home_24():
    assert _parse_ifconfig_netmask(_IFCONFIG_TYPICAL_HOME, "192.168.1.42") == 24


def test_parse_ifconfig_netmask_corporate_16():
    assert _parse_ifconfig_netmask(_IFCONFIG_CORPORATE_16, "10.5.7.42") == 16


def test_parse_ifconfig_netmask_returns_none_when_ip_not_found():
    assert _parse_ifconfig_netmask(_IFCONFIG_TYPICAL_HOME, "10.0.0.1") is None


# ---------- _detect_subnet ----------

def test_subnet_from_ifconfig_parses_typical_home_24():
    hosts, cidr, cap_prefix, was_capped = _detect_subnet(
        "192.168.1.42",
        ifconfig_runner=lambda: _IFCONFIG_TYPICAL_HOME,
        cap_prefix=24,
    )
    assert cidr == "192.168.1.0/24"
    assert cap_prefix == 24
    assert was_capped is False
    assert len(hosts) == 254
    assert "192.168.1.1" in hosts
    assert "192.168.1.254" in hosts
    assert "192.168.1.0" not in hosts  # network
    assert "192.168.1.255" not in hosts  # broadcast


def test_subnet_caps_at_24_when_netmask_wider():
    hosts, cidr, cap_prefix, was_capped = _detect_subnet(
        "10.5.7.42",
        ifconfig_runner=lambda: _IFCONFIG_CORPORATE_16,
        cap_prefix=24,
    )
    assert cidr == "10.5.7.0/24"
    assert cap_prefix == 24
    assert was_capped is True
    assert len(hosts) == 254


def test_subnet_uses_full_subnet_when_netmask_is_25_or_narrower():
    hosts, cidr, cap_prefix, was_capped = _detect_subnet(
        "192.168.1.10",
        ifconfig_runner=lambda: _IFCONFIG_NARROW_26,
        cap_prefix=24,
    )
    # /26 narrower than /24 cap; sweep the full /26.
    assert cidr == "192.168.1.0/26"
    assert was_capped is False
    # /26 has 62 host IPs (64 - network - broadcast).
    assert len(hosts) == 62


def test_subnet_caps_at_22_when_wide_flag_set():
    hosts, cidr, cap_prefix, was_capped = _detect_subnet(
        "10.5.7.42",
        ifconfig_runner=lambda: _IFCONFIG_CORPORATE_16,
        cap_prefix=22,
    )
    # /22 around 10.5.7.42 = 10.5.4.0/22.
    assert cidr == "10.5.4.0/22"
    assert cap_prefix == 22
    assert was_capped is True
    assert len(hosts) == 1022


def test_subnet_still_caps_at_22_when_wide_flag_set_and_netmask_is_16():
    # /16 corp VLAN + WIDE=1 still narrows to /22 around iface_ip.
    hosts, cidr, _cap, was_capped = _detect_subnet(
        "10.5.7.42",
        ifconfig_runner=lambda: _IFCONFIG_CORPORATE_16,
        cap_prefix=22,
    )
    assert "/22" in cidr
    assert was_capped is True
    assert len(hosts) == 1022


def test_subnet_uses_full_subnet_when_native_22_and_wide_flag_set():
    hosts, cidr, _cap, was_capped = _detect_subnet(
        "192.168.4.42",
        ifconfig_runner=lambda: _IFCONFIG_NATIVE_22,
        cap_prefix=22,
    )
    assert cidr == "192.168.4.0/22"
    assert was_capped is False
    assert len(hosts) == 1022


def test_subnet_defaults_to_24_when_ifconfig_fails():
    def boom() -> str:
        raise RuntimeError("ifconfig blew up")

    hosts, cidr, _cap, was_capped = _detect_subnet(
        "192.168.1.42",
        ifconfig_runner=boom,
        cap_prefix=24,
    )
    # Falls back to /24 around iface_ip.
    assert cidr == "192.168.1.0/24"
    assert was_capped is False
    assert len(hosts) == 254


def test_effective_cap_prefix_reads_env_flag(monkeypatch):
    monkeypatch.delenv("DITING_LAN_INVENTORY_WIDE", raising=False)
    assert _effective_cap_prefix() == 24
    monkeypatch.setenv("DITING_LAN_INVENTORY_WIDE", "1")
    assert _effective_cap_prefix() == 22
    monkeypatch.setenv("DITING_LAN_INVENTORY_WIDE", "true")  # exactly "1"
    assert _effective_cap_prefix() == 24


# ---------- _ping_one ----------

def _fake_ping_proc(rc: int, stdout: bytes):
    class _FakeProc:
        def __init__(self) -> None:
            self.returncode = rc

        async def communicate(self):
            self.returncode = rc
            return stdout, b""

    return _FakeProc()


def test_ping_one_returns_rtt_on_zero_exit(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            return _fake_ping_proc(
                0,
                b"PING 192.168.1.1 (192.168.1.1): 56 data bytes\n"
                b"64 bytes from 192.168.1.1: icmp_seq=0 ttl=64 time=2.439 ms\n",
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    reachable, rtt, ttl = asyncio.run(_go())
    assert reachable is True
    assert rtt == pytest.approx(2.439, abs=0.001)
    assert ttl == 64


def test_ping_one_returns_none_rtt_on_nonzero_exit(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            return _fake_ping_proc(2, b"")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    assert asyncio.run(_go()) == (False, None, None)


def test_ping_one_returns_true_none_when_stdout_unparseable(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            # Exit 0 but stdout has no "time=X ms" or "ttl=N" segment.
            return _fake_ping_proc(0, b"weird-build-output-without-rtt")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    assert asyncio.run(_go()) == (True, None, None)


def test_ping_one_returns_false_none_on_oserror(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            raise OSError("ENOENT")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    assert asyncio.run(_go()) == (False, None, None)


# ---------- _sweep ----------

def test_sweep_caps_concurrency_at_thirty(monkeypatch):
    """The sweep MUST hold at most 30 ping subprocesses alive at once."""
    max_inflight = 0
    inflight = 0
    lock = asyncio.Lock()

    async def _go() -> None:
        nonlocal max_inflight, inflight

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = 0

            async def communicate(self):
                nonlocal max_inflight, inflight
                async with lock:
                    inflight += 1
                    if inflight > max_inflight:
                        max_inflight = inflight
                # Hold the slot for one event-loop tick so concurrency
                # actually piles up.
                await asyncio.sleep(0.01)
                async with lock:
                    inflight -= 1
                self.returncode = 0
                # No RTT in the canned output; sweep result tuple
                # becomes (True, None) which is irrelevant to the
                # concurrency assertion.
                return b"", b""

        async def _fake_exec(*_args, **_kwargs) -> _FakeProc:
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        hosts = [f"192.168.1.{i}" for i in range(1, 101)]  # 100 hosts
        await _sweep(hosts)

    asyncio.run(_go())
    assert max_inflight <= 30
    # Sanity: we hit a real concurrency ceiling, not single-step.
    assert max_inflight > 1


# ---------- _read_arp_cache ----------

_ARP_OUT_TYPICAL = """\
? (192.168.1.1) at aa:bb:cc:11:22:33 on en0 ifscope [ethernet]
? (192.168.1.42) at de:ad:be:ef:00:01 on en0 ifscope [ethernet]
? (192.168.1.99) at <incomplete> on en0 ifscope [ethernet]
? (192.168.1.55) at f4:5c:89:11:22:33 on en0 ifscope [ethernet]
"""


def test_arp_parse_extracts_mac_and_ip():
    triples = _read_arp_cache(runner=lambda: _ARP_OUT_TYPICAL)
    ips = [t[0] for t in triples]
    macs = [t[1] for t in triples]
    assert "192.168.1.1" in ips
    assert "192.168.1.42" in ips
    assert "192.168.1.55" in ips
    assert "aa:bb:cc:11:22:33" in macs
    assert "de:ad:be:ef:00:01" in macs


def test_arp_parse_skips_incomplete_entries():
    triples = _read_arp_cache(runner=lambda: _ARP_OUT_TYPICAL)
    ips = [t[0] for t in triples]
    assert "192.168.1.99" not in ips
    assert len(triples) == 3


def test_arp_parse_handles_mixed_format_lines():
    mixed = """\
not an arp line
? (10.0.0.1) at 00:11:22:33:44:55 on bridge100 [bridge]
? (10.0.0.99) at <incomplete> on bridge100 [bridge]

? (10.0.0.50) at AA:BB:CC:DD:EE:FF on bridge100 [bridge]
"""
    triples = _read_arp_cache(runner=lambda: mixed)
    assert len(triples) == 2
    # MACs are lowercased.
    assert ("10.0.0.50", "aa:bb:cc:dd:ee:ff", "bridge100") in triples


def test_arp_parse_filters_ipv4_multicast_destination_macs():
    """The kernel ARP cache picks up multicast destination MACs as
    a side effect of any UDP send to a multicast group (mDNS,
    SSDP). Those are not real LAN hosts — they should not appear
    in the LAN panel."""
    text = """\
? (192.168.1.1) at 00:11:22:33:44:55 on en0 [ethernet]
? (224.0.0.251) at 1:0:5e:0:0:fb on en0 [ethernet]
? (239.255.255.250) at 1:0:5e:7f:ff:fa on en0 [ethernet]
? (192.168.1.42) at de:ad:be:ef:00:01 on en0 [ethernet]
"""
    triples = _read_arp_cache(runner=lambda: text)
    macs = {mac for _ip, mac, _iface in triples}
    assert "00:11:22:33:44:55" in macs
    assert "de:ad:be:ef:00:01" in macs
    # Multicast destinations stripped.
    assert "1:0:5e:0:0:fb" not in macs
    assert "1:0:5e:7f:ff:fa" not in macs
    assert len(triples) == 2


def test_arp_parse_filters_ipv6_multicast_destination_macs():
    text = """\
? (192.168.1.1) at 00:11:22:33:44:55 on en0 [ethernet]
? (ff02::fb) at 33:33:0:0:0:fb on en0 [ethernet]
? (ff02::1) at 33:33:0:0:0:1 on en0 [ethernet]
"""
    triples = _read_arp_cache(runner=lambda: text)
    macs = {mac for _ip, mac, _iface in triples}
    assert "00:11:22:33:44:55" in macs
    assert "33:33:0:0:0:fb" not in macs
    assert "33:33:0:0:0:1" not in macs


def test_is_multicast_dest_mac_unit():
    from diting.lan import _is_multicast_dest_mac
    # IPv4 multicast range 01:00:5e:00:00:00 – 01:00:5e:7f:ff:ff.
    assert _is_multicast_dest_mac("01:00:5e:00:00:fb")
    assert _is_multicast_dest_mac("1:0:5e:7f:ff:fa")  # stripped-zero form
    # IPv6 multicast all 33:33:*.
    assert _is_multicast_dest_mac("33:33:00:00:00:fb")
    assert _is_multicast_dest_mac("33:33:ff:ff:ff:ff")
    # Universal MAC outside both ranges.
    assert not _is_multicast_dest_mac("aa:bb:cc:dd:ee:ff")
    assert not _is_multicast_dest_mac("00:11:22:33:44:55")
    # Apple OUI; never multicast.
    assert not _is_multicast_dest_mac("38:09:fb:0b:be:60")


def test_ip_in_network_accepts_host_ip_in_range():
    import ipaddress
    from diting.lan import _ip_in_network
    net = ipaddress.IPv4Network("192.168.1.0/24")
    assert _ip_in_network("192.168.1.1", net) is True
    assert _ip_in_network("192.168.1.254", net) is True


def test_ip_in_network_rejects_network_and_broadcast_addresses():
    import ipaddress
    from diting.lan import _ip_in_network
    net = ipaddress.IPv4Network("192.168.1.0/24")
    assert _ip_in_network("192.168.1.0", net) is False
    assert _ip_in_network("192.168.1.255", net) is False


def test_ip_in_network_rejects_out_of_range_ip():
    """A pre-existing ARP entry for a host outside the sweep network
    must be filtered out — this is the corp-VLAN cache-pollution bug
    surfaced by the real-environment audit."""
    import ipaddress
    from diting.lan import _ip_in_network
    net = ipaddress.IPv4Network("11.10.150.0/24")
    # In the broader /16, outside the /24 cap → reject.
    assert _ip_in_network("11.10.156.5", net) is False
    # Far outside → reject.
    assert _ip_in_network("8.8.8.8", net) is False


def test_ip_in_network_rejects_garbage():
    import ipaddress
    from diting.lan import _ip_in_network
    net = ipaddress.IPv4Network("192.168.1.0/24")
    assert _ip_in_network("not-an-ip", net) is False
    assert _ip_in_network("", net) is False


def test_gateway_ip_appears_when_outside_sweep_cap(monkeypatch):
    """The gateway IP is unconditionally exempt from the /24 (or /22)
    ARP filter. Corporate VLANs frequently sit clients in one /24 and
    the gateway in a different /24; excluding the gateway would drop
    the most useful row from the panel."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    monkeypatch.setattr("diting.lan._sweep", _stub_sweep)
    monkeypatch.setattr(
        "diting.lan._detect_subnet",
        lambda *_a, **_k: (["11.10.158.1"], "11.10.158.0/24", 24, True),
    )
    # Mock ARP cache that includes the gateway (out of the /24 cap)
    # and the user's Mac (in the /24).
    monkeypatch.setattr(
        "diting.lan._read_arp_cache",
        lambda **_: [
            ("11.10.158.42", "84:2f:57:9b:15:59", "en0"),
            # Gateway outside the /24 cap — must still appear.
            ("11.10.128.1", "aa:bb:cc:11:22:33", "en0"),
            # Unrelated cached entry — must be filtered out.
            ("11.10.999.5", "f4:5c:89:11:22:33", "en0"),
            # Truly out-of-range neighbour — filtered out.
            ("8.8.8.8", "00:11:22:33:44:55", "en0"),
        ],
    )

    async def _go() -> LANInventoryUpdate | None:
        conn = _make_conn(
            ip="11.10.158.72",
            router="11.10.128.1",
            mac="84:2f:57:9b:15:59",
        )
        poller = LANInventoryPoller(connection_provider=lambda: conn)
        await poller._do_sweep_and_emit()
        return poller._queue.get_nowait()

    update = asyncio.run(_go())
    assert update is not None
    macs = {h.mac for h in update.hosts}
    assert "aa:bb:cc:11:22:33" in macs, "gateway must appear even outside cap"
    # Self always pinned.
    assert "84:2f:57:9b:15:59" in macs
    # Out-of-cap, non-gateway IPs are filtered out.
    assert "f4:5c:89:11:22:33" not in macs
    assert "00:11:22:33:44:55" not in macs
    # The host marked is_gateway is the one whose IP matches router.
    gw = next(h for h in update.hosts if h.is_gateway)
    assert gw.ip == "11.10.128.1"


async def _stub_sweep(hosts, **_kwargs):
    return {ip: (True, 1.0) for ip in hosts}


def test_sweep_returns_per_ip_results_dict(monkeypatch):
    """`_sweep` must return ``{ip: (reachable, rtt_ms, ttl)}`` not
    None. The merge step reads this dict to populate `last_rtt_ms`,
    `last_reachable_at`, and the new `ttl` field on each LANHost."""
    from diting.lan import _sweep

    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            return _fake_ping_proc(
                0,
                b"PING 192.168.1.1 (192.168.1.1): 56 data bytes\n"
                b"64 bytes from 192.168.1.1: icmp_seq=0 ttl=64 time=2.0 ms\n",
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _sweep(["192.168.1.1", "192.168.1.2"])

    result = asyncio.run(_go())
    assert isinstance(result, dict)
    assert "192.168.1.1" in result
    assert "192.168.1.2" in result
    reachable, rtt, ttl = result["192.168.1.1"]
    assert reachable is True
    assert rtt == pytest.approx(2.0, abs=0.001)
    assert ttl == 64


def test_lan_host_last_rtt_ms_populated_from_sweep(monkeypatch):
    """After a successful ping, the LANHost's last_rtt_ms must equal
    the sweep result's RTT and last_reachable_at must be set to the
    sweep tick's `now`."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 3.14)},
        )
        return poller._state["de:ad:be:ef:00:01"], now

    host, now = asyncio.run(_go())
    assert host.last_rtt_ms == pytest.approx(3.14, abs=0.001)
    assert host.last_reachable_at == now


def test_lan_host_last_rtt_ms_preserved_when_silent_tick(monkeypatch):
    """Host responded on tick N then went silent on tick N+1 —
    `last_rtt_ms` and `last_reachable_at` must NOT be reset to None
    when ARP still has the entry."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        first_now = datetime.now(timezone.utc)
        # Tick 1: host responds, RTT 2.4 ms.
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=first_now,
            sweep_results={"192.168.1.42": (True, 2.4)},
        )
        first_host = poller._state["de:ad:be:ef:00:01"]
        # Tick 2: ARP still has the entry, but ping got no reply.
        second_now = first_now
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=second_now,
            sweep_results={"192.168.1.42": (False, None)},
        )
        return first_host, poller._state["de:ad:be:ef:00:01"]

    first_host, second_host = asyncio.run(_go())
    assert first_host.last_rtt_ms == pytest.approx(2.4, abs=0.001)
    assert second_host.last_rtt_ms == pytest.approx(2.4, abs=0.001)
    assert second_host.last_reachable_at == first_host.last_reachable_at


def test_lan_host_last_reachable_at_set_on_successful_ping(monkeypatch):
    """Distinguished from last_seen: last_reachable_at advances only
    when ICMP got a reply."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 1.0)},
        )
        return poller._state["de:ad:be:ef:00:01"], now

    host, now = asyncio.run(_go())
    assert host.last_seen == now
    assert host.last_reachable_at == now


def test_lan_host_last_reachable_at_preserved_when_silent(monkeypatch):
    """ARP cache still has the entry; ping got no reply this sweep.
    last_seen advances; last_reachable_at stays at the prior value."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        t1 = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=t1,
            sweep_results={"192.168.1.42": (True, 1.5)},
        )
        # ~10ms later, ping silent.
        from datetime import timedelta

        t2 = t1 + timedelta(milliseconds=10)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=t2,
            sweep_results={"192.168.1.42": (False, None)},
        )
        return t1, poller._state["de:ad:be:ef:00:01"]

    t1, host = asyncio.run(_go())
    assert host.last_reachable_at == t1  # frozen at the original
    assert host.last_seen > t1  # advanced


def _refresh_ouis_module():
    """Return the `scripts/refresh_ouis.py` module, importing once."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import refresh_ouis  # type: ignore
    return refresh_ouis


def test_oui_refresh_script_parses_csv_to_aabbcc_keys():
    """`parse_csv` normalises 24-bit MA-L OUIs to the canonical
    lowercase colon-separated form the existing JSON file uses."""
    mod = _refresh_ouis_module()
    ma_l = next(r for r in mod._REGISTRIES if r.name == "MA-L")
    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        'MA-L,001D0F,"TP-LINK TECHNOLOGIES CO.,LTD.","example address"\n'
        'MA-L,00038F,"Wave Wireless Networking","123 Example St"\n'
    )
    out = mod.parse_csv(csv_text, ma_l)
    assert out["00:1d:0f"] == "TP-LINK TECHNOLOGIES CO.,LTD."
    assert out["00:03:8f"] == "Wave Wireless Networking"


def test_oui_refresh_script_parses_each_tier_separately():
    """parse_csv filters to the registry passed in; the three tiers
    do not bleed into each other."""
    mod = _refresh_ouis_module()
    ma_l = next(r for r in mod._REGISTRIES if r.name == "MA-L")
    ma_m = next(r for r in mod._REGISTRIES if r.name == "MA-M")
    ma_s = next(r for r in mod._REGISTRIES if r.name == "MA-S")
    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        'MA-L,AABBCC,"Vendor A","addr"\n'
        'MA-M,DDEEFF0,"Vendor B (MA-M)","addr"\n'
        'MA-S,112233455,"Vendor C (MA-S)","addr"\n'
    )
    assert mod.parse_csv(csv_text, ma_l) == {"aa:bb:cc": "Vendor A"}
    assert mod.parse_csv(csv_text, ma_m) == {"dd:ee:ff:0": "Vendor B (MA-M)"}
    assert mod.parse_csv(csv_text, ma_s) == {
        "11:22:33:45:5": "Vendor C (MA-S)",
    }


def test_oui_refresh_script_dedupes_repeated_assignments():
    """IEEE occasionally lists the same OUI twice under slight
    naming variations. First wins; second is dropped."""
    mod = _refresh_ouis_module()
    ma_l = next(r for r in mod._REGISTRIES if r.name == "MA-L")
    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        'MA-L,AABBCC,"First Variant Inc","addr1"\n'
        'MA-L,AABBCC,"Second Variant LLC","addr2"\n'
    )
    out = mod.parse_csv(csv_text, ma_l)
    assert out == {"aa:bb:cc": "First Variant Inc"}


def test_oui_refresh_script_parses_wireshark_manuf_all_three_tiers():
    """The Wireshark `manuf` fallback splits a single file into the
    three tiers by `/N` prefix-bit notation."""
    mod = _refresh_ouis_module()
    manuf_text = (
        "# comment line ignored\n"
        "00:00:01         \tXerox        \tXerox Corporation\n"
        "00:55:DA:00/28   \tShinkoTechno \tShinko Technos co.,ltd.\n"
        "00:1B:C5:00:00/36\tConverging   \tConverging Systems Inc.\n"
    )
    out = mod.parse_wireshark_manuf(manuf_text)
    assert out["MA-L"] == {"00:00:01": "Xerox Corporation"}
    assert out["MA-M"] == {"00:55:da:0": "Shinko Technos co.,ltd."}
    assert out["MA-S"] == {"00:1b:c5:00:0": "Converging Systems Inc."}


def test_oui_refresh_script_wireshark_manuf_skips_unknown_widths():
    """Wireshark sometimes carries non-standard widths in `manuf`
    (custom annotations). Those entries get skipped, not mis-keyed."""
    mod = _refresh_ouis_module()
    manuf_text = (
        "AB:CD:EF:00/20\tWeirdWidth  \tShould Be Skipped\n"
        "AB:CD:EF      \tValidLong   \tValid 24-bit Entry\n"
    )
    out = mod.parse_wireshark_manuf(manuf_text)
    assert "MA-L" in out
    assert out["MA-L"] == {"ab:cd:ef": "Valid 24-bit Entry"}
    # No MA-M / MA-S entries because /20 was rejected and the second
    # line was 24-bit.
    assert out["MA-M"] == {}
    assert out["MA-S"] == {}


def test_lan_host_last_reachable_at_none_when_never_reached(monkeypatch):
    """Host appeared in the kernel ARP cache (e.g. from before diting
    started) but the sweep has never gotten a ping reply.
    last_reachable_at stays None — the modal renders 'never'."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.99", "aa:bb:cc:00:00:01", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.99": (False, None)},
        )
        return poller._state["aa:bb:cc:00:00:01"]

    host = asyncio.run(_go())
    assert host.last_rtt_ms is None
    assert host.last_reachable_at is None


def test_arp_parse_returns_empty_on_subprocess_failure():
    def boom() -> str:
        raise OSError("arp not found")

    assert _read_arp_cache(runner=boom) == []


# ---------- _strip_local_suffix ----------

def test_strip_local_suffix_removes_trailing_dot_and_local():
    assert _strip_local_suffix("foo.local.") == "foo"
    assert _strip_local_suffix("foo.local") == "foo"
    assert _strip_local_suffix("foo") == "foo"


def test_strip_local_suffix_handles_none():
    assert _strip_local_suffix(None) is None
    assert _strip_local_suffix("") is None


# ---------- _build_bonjour_index ----------

def _bonjour_device(
    addresses: tuple[str, ...],
    *,
    category: str | None = None,
    host: str | None = "ccy-MBP24-M4-Office.local.",
    name: str = "x",
    service_type: str = "_airplay._tcp.local.",
) -> BonjourDevice:
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    return BonjourDevice(
        service_type=service_type,
        name=name,
        host=host,
        port=7000,
        addresses=addresses,
        txt={},
        vendor=None,
        category=category,
        first_seen=now,
        last_seen=now,
    )


def test_bonjour_cross_ref_pulls_name_from_state():
    poller = BonjourPoller()
    dev = _bonjour_device(("192.168.1.42",), category="AirPlay")
    poller._state[(dev.service_type, dev.name)] = dev
    idx = _build_bonjour_index(poller)
    host, cats, model = idx["192.168.1.42"]
    assert host == "ccy-MBP24-M4-Office"
    assert cats == ("AirPlay",)
    assert model is None  # no `model=` TXT in this fixture


def test_bonjour_cross_ref_aggregates_categories():
    poller = BonjourPoller()
    poller._state[("a", "x")] = _bonjour_device(("192.168.1.42",), category="AirPlay", name="x")
    poller._state[("b", "y")] = _bonjour_device(("192.168.1.42",), category="AirPlay audio", name="y")
    poller._state[("c", "z")] = _bonjour_device(("192.168.1.42",), category="Apple Companion", name="z")
    idx = _build_bonjour_index(poller)
    _, cats, _ = idx["192.168.1.42"]
    assert set(cats) == {"AirPlay", "AirPlay audio", "Apple Companion"}


def test_bonjour_cross_ref_pulls_apple_model_code_from_txt():
    """When any BonjourDevice for an IP carries `model=` (AirPlay
    TXT key) in its TXT records, the index surfaces it on the IP
    entry. First-wins."""
    from dataclasses import replace as _replace
    poller = BonjourPoller()
    # First device — no model in TXT.
    dev1 = _bonjour_device(("192.168.1.42",), category="AirPlay", name="x")
    # Second device on the same IP — has model code.
    dev2 = _bonjour_device(("192.168.1.42",), category="Apple Companion", name="y")
    dev2 = _replace(dev2, txt={"model": "Mac14,2"})
    poller._state[("a", "x")] = dev1
    poller._state[("b", "y")] = dev2
    idx = _build_bonjour_index(poller)
    _, _, model = idx["192.168.1.42"]
    assert model == "Mac14,2"


def test_bonjour_cross_ref_pulls_apple_model_code_from_rpmd_txt():
    """A `_companion-link._tcp` TXT uses the `rpMd` key (rendezvous-
    protocol Model). Diagnostic for random-MAC iPads that only
    publish Apple Companion — without this extraction we'd have
    no authoritative class signal for them."""
    from dataclasses import replace as _replace
    poller = BonjourPoller()
    dev = _bonjour_device(
        ("192.168.1.42",), category="Apple Companion", name="y",
    )
    dev = _replace(dev, txt={"rpMd": "iPad14,3"})
    poller._state[("a", "y")] = dev
    idx = _build_bonjour_index(poller)
    _, _, model = idx["192.168.1.42"]
    assert model == "iPad14,3"


def test_bonjour_cross_ref_pulls_apple_model_code_from_am_txt():
    """A `_raop._tcp` TXT uses the `am` key for the Apple model
    identifier. AirPlay receivers (HomePods, AirPlay 2 speakers)
    publish here."""
    from dataclasses import replace as _replace
    poller = BonjourPoller()
    dev = _bonjour_device(
        ("192.168.1.42",), category="AirPlay audio", name="z",
    )
    dev = _replace(dev, txt={"am": "AudioAccessory6,1"})
    poller._state[("a", "z")] = dev
    idx = _build_bonjour_index(poller)
    _, _, model = idx["192.168.1.42"]
    assert model == "AudioAccessory6,1"


def test_bonjour_cross_ref_apple_model_none_when_no_txt_key_present():
    """No `model` / `rpMd` / `am` TXT key on any device → model
    field is None. Other TXT keys are irrelevant for classification."""
    from dataclasses import replace as _replace
    poller = BonjourPoller()
    dev = _bonjour_device(("192.168.1.42",), category="AirPlay")
    dev = _replace(dev, txt={"rpFl": "0x123", "deviceid": "abc"})
    poller._state[(dev.service_type, dev.name)] = dev
    idx = _build_bonjour_index(poller)
    _, _, model = idx["192.168.1.42"]
    assert model is None


def test_bonjour_cross_ref_leaves_name_none_when_no_match():
    poller = BonjourPoller()
    poller._state[("a", "x")] = _bonjour_device(("192.168.1.42",), category="AirPlay")
    idx = _build_bonjour_index(poller)
    assert "192.168.1.99" not in idx


def test_bonjour_cross_ref_handles_none_poller():
    assert _build_bonjour_index(None) == {}


def test_bonjour_cross_ref_does_not_mutate_state():
    poller = BonjourPoller()
    dev = _bonjour_device(("192.168.1.42",), category="AirPlay")
    poller._state[(dev.service_type, dev.name)] = dev
    snapshot_before = dict(poller._state)
    _ = _build_bonjour_index(poller)
    assert poller._state == snapshot_before


# ---------- vendor lookup integration ----------

def test_vendor_lookup_for_universal_mac_returns_vendor():
    from diting.ble import load_ouis, lookup_oui_vendor

    ouis = load_ouis()
    # Apple OUI 00:03:93 ships in the bundled OUI map.
    assert lookup_oui_vendor("00:03:93:11:22:33", ouis) == "Apple, Inc."


def test_vendor_lookup_for_random_mac_returns_none():
    # A locally-administered MAC (bit 0x02 of first octet set) is
    # not in the IEEE registry — vendor lookup should miss.
    from diting.ble import load_ouis, lookup_oui_vendor

    ouis = load_ouis()
    # 0x02 first octet → locally administered.
    assert lookup_oui_vendor("02:11:22:33:44:55", ouis) is None


# ---------- LANHost.vendor + vendor_raw round-trip ----------


def _build_state_with_vendor(monkeypatch, mac: str, raw_vendor: str | None):
    """Drive _merge_arp_into_state once with synthetic OUI tables so we
    can assert what `vendor` and `vendor_raw` land as on the LANHost."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    # Pre-seed the layered cache so the merge step doesn't try to
    # touch the bundled JSON.
    oui_24 = mac[:8].lower()
    ma_l = {oui_24: raw_vendor} if raw_vendor is not None else {}
    poller._oui_layers = (ma_l, {}, {})
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", mac, "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4)},
        )
        return poller._state[mac.lower()]

    return asyncio.run(_go())


def test_vendor_normalized_on_host_when_lookup_hits(monkeypatch):
    """Raw IEEE string `"NEW H3C TECHNOLOGIES CO., LTD"` lands on
    `vendor_raw`; `vendor` is the normalized short form `"New H3C"`."""
    host = _build_state_with_vendor(
        monkeypatch, "00:03:93:11:22:33", "NEW H3C TECHNOLOGIES CO., LTD",
    )
    assert host.vendor_raw == "NEW H3C TECHNOLOGIES CO., LTD"
    assert host.vendor == "New H3C"


def test_vendor_raw_preserved_when_normalization_changes_name(monkeypatch):
    host = _build_state_with_vendor(
        monkeypatch, "00:03:93:11:22:33", "SHENZHEN BILIAN ELECTRONIC CO.,LTD",
    )
    assert host.vendor_raw == "SHENZHEN BILIAN ELECTRONIC CO.,LTD"
    assert host.vendor == "Bilian"


def test_vendor_raw_equals_vendor_when_already_clean(monkeypatch):
    host = _build_state_with_vendor(
        monkeypatch, "00:03:93:11:22:33", "Apple",
    )
    assert host.vendor_raw == "Apple"
    assert host.vendor == "Apple"


def test_vendor_raw_none_for_random_mac(monkeypatch):
    # Locally-administered MAC short-circuits the lookup entirely.
    host = _build_state_with_vendor(
        monkeypatch, "02:11:22:33:44:55", "Should Not Be Used",
    )
    assert host.vendor is None
    assert host.vendor_raw is None
    assert host.is_randomised_mac is True


def test_vendor_raw_none_when_oui_misses(monkeypatch):
    # 0x08 first octet — universal (bit 0x02 clear) but unknown to
    # the synthetic OUI table.
    host = _build_state_with_vendor(
        monkeypatch, "08:11:22:33:44:55", None,
    )
    assert host.vendor is None
    assert host.vendor_raw is None
    assert host.is_randomised_mac is False


# ---------- TTL bucket + ttl_class helper (Phase 3) ----------


def test_unpack_sweep_entry_handles_three_tuple():
    from diting.lan import _unpack_sweep_entry
    assert _unpack_sweep_entry((True, 2.4, 64)) == (True, 2.4, 64)


def test_unpack_sweep_entry_handles_legacy_two_tuple():
    from diting.lan import _unpack_sweep_entry
    # Existing fixtures that pre-date Phase 3 still pass 2-tuples.
    # The unpacker must yield None for the TTL slot so the caller
    # can compose without branching.
    assert _unpack_sweep_entry((True, 2.4)) == (True, 2.4, None)


def test_unpack_sweep_entry_handles_none():
    from diting.lan import _unpack_sweep_entry
    assert _unpack_sweep_entry(None) == (False, None, None)


def test_ttl_class_unix_band():
    from diting.lan import ttl_class_for
    assert ttl_class_for(64) == "unix"
    assert ttl_class_for(50) == "unix"


def test_ttl_class_windows_band():
    from diting.lan import ttl_class_for
    assert ttl_class_for(128) == "windows"
    assert ttl_class_for(100) == "windows"


def test_ttl_class_router_band():
    from diting.lan import ttl_class_for
    assert ttl_class_for(255) == "router"
    assert ttl_class_for(200) == "router"


def test_ttl_class_decremented_hop_still_unix():
    from diting.lan import ttl_class_for
    # Two-hop decrement from 64 → 62. The 50-64 band absorbs
    # single-digit hop decrements.
    assert ttl_class_for(62) == "unix"


def test_ttl_class_out_of_range_returns_none():
    from diting.lan import ttl_class_for
    assert ttl_class_for(40) is None
    assert ttl_class_for(90) is None  # gap between unix and windows
    assert ttl_class_for(180) is None  # gap between windows and router


def test_ttl_class_none_input_returns_none():
    from diting.lan import ttl_class_for
    assert ttl_class_for(None) is None


def test_lan_host_ttl_populated_from_sweep(monkeypatch):
    """When the sweep result carries a TTL, the merged LANHost
    surfaces both the raw value and the derived class."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    poller = LANInventoryPoller(connection_provider=lambda: None)
    poller._oui_layers = ({}, {}, {})
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4, 128)},
        )
        return poller._state["08:11:22:33:44:55"]

    host = asyncio.run(_go())
    assert host.ttl == 128
    assert host.ttl_class == "windows"


def test_lan_host_ttl_preserved_when_silent_tick(monkeypatch):
    """A host that ping-replied once with TTL=64 and then went
    silent must keep its `ttl` populated — the modal still shows it."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    poller = LANInventoryPoller(connection_provider=lambda: None)
    poller._oui_layers = ({}, {}, {})
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        # Tick 1: TTL captured.
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4, 64)},
        )
        # Tick 2: silent.
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (False, None, None)},
        )
        return poller._state["08:11:22:33:44:55"]

    host = asyncio.run(_go())
    assert host.ttl == 64
    assert host.ttl_class == "unix"


def test_lan_host_ttl_class_derived_from_ttl_value(monkeypatch):
    """The ttl_class is derived from ttl, not from a separate
    sweep_results slot — sanity that the bucketing happens in the
    merge step."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    poller = LANInventoryPoller(connection_provider=lambda: None)
    poller._oui_layers = ({}, {}, {})
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4, 250)},
        )
        return poller._state["08:11:22:33:44:55"]

    host = asyncio.run(_go())
    assert host.ttl == 250
    assert host.ttl_class == "router"


# ---------- classifier wired into merge / probe paths ----------


def test_merge_populates_device_class_when_classifier_matches(monkeypatch):
    """Vendor lookup yields a router-class string; the merge step
    must populate `device_class` on the resulting LANHost."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    poller = LANInventoryPoller(connection_provider=lambda: None)
    # Pre-seed an OUI dict that resolves the MAC to a router vendor.
    poller._oui_layers = (
        {"08:11:22": "Tp-Link Technologies Co.,Ltd."}, {}, {},
    )
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4, 64)},
        )
        return poller._state["08:11:22:33:44:55"]

    host = asyncio.run(_go())
    assert host.device_class == "router"


def test_apply_probe_results_reclassifies_after_upnp_lands(monkeypatch):
    """A host with no vendor-side signal first merges with
    device_class=None. After the active-discovery phase populates
    the UPnP server header, _apply_probe_results must re-run the
    classifier — the same row goes from class=None to class=`tv`."""
    from diting.lan_probes import SSDPResponse

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    poller = LANInventoryPoller(connection_provider=lambda: None)
    poller._oui_layers = ({}, {}, {})  # vendor lookup misses
    conn = _make_conn()

    async def _seed():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4, 64)},
        )

    asyncio.run(_seed())
    # Initially: no signals → class None.
    assert poller._state["08:11:22:33:44:55"].device_class is None

    # Probe phase brings a UPnP server header that signals TV.
    poller._apply_probe_results(
        {},
        {
            "192.168.1.42": SSDPResponse(
                ip="192.168.1.42",
                server="Linux/3.10 UPnP/1.0 HiSense/2024.01",
                location=None,
                usn=None,
                st=None,
            ),
        },
    )
    assert poller._state["08:11:22:33:44:55"].device_class == "tv"


# ---------- active-discovery integration (Phase 2) ----------


def _poller_with_one_host(monkeypatch):
    """Build a LANInventoryPoller pre-populated with one synthetic
    host so the probe-merge logic can be exercised without standing
    up a real sweep."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    poller = LANInventoryPoller(
        connection_provider=lambda: None,
        active_probe_enabled=True,
    )
    poller._oui_layers = ({}, {}, {})
    conn = _make_conn()

    async def _seed():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "08:11:22:33:44:55", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.4)},
        )

    asyncio.run(_seed())
    return poller


def test_apply_probe_results_merges_nbns_into_state(monkeypatch):
    poller = _poller_with_one_host(monkeypatch)
    poller._apply_probe_results(
        {"192.168.1.42": "LAB-PRINTER-01"}, {},
    )
    host = poller._state["08:11:22:33:44:55"]
    assert host.nbns_name == "LAB-PRINTER-01"
    assert host.upnp_server is None


def test_apply_probe_results_merges_upnp_into_state(monkeypatch):
    from diting.lan_probes import SSDPResponse
    poller = _poller_with_one_host(monkeypatch)
    poller._apply_probe_results(
        {},
        {
            "192.168.1.42": SSDPResponse(
                ip="192.168.1.42",
                server="Linux/3.10 UPnP/1.0 HiSenseTV/2024.01",
                location="http://192.168.1.42:1900/desc.xml",
                usn=None,
                st="upnp:rootdevice",
                friendly_name="Living Room TV",
                model_name="HiSense 75U7K",
            )
        },
    )
    host = poller._state["08:11:22:33:44:55"]
    assert host.upnp_server == "Linux/3.10 UPnP/1.0 HiSenseTV/2024.01"
    assert host.upnp_friendly_name == "Living Room TV"
    assert host.upnp_model == "HiSense 75U7K"


def test_apply_probe_results_leaves_untouched_hosts_alone(monkeypatch):
    poller = _poller_with_one_host(monkeypatch)
    # No probe data for this host's IP.
    poller._apply_probe_results({"10.0.0.99": "ghost"}, {})
    host = poller._state["08:11:22:33:44:55"]
    assert host.nbns_name is None
    assert host.upnp_server is None


def test_apply_probe_results_preserves_prior_enrichment_when_new_value_none(
    monkeypatch,
):
    """A subsequent sweep where the host briefly didn't answer NBNS
    must NOT clobber a name we previously captured."""
    poller = _poller_with_one_host(monkeypatch)
    poller._apply_probe_results({"192.168.1.42": "LAB-PRINTER-01"}, {})
    assert poller._state["08:11:22:33:44:55"].nbns_name == "LAB-PRINTER-01"
    # Second probe — same IP, None result (silent this tick).
    poller._apply_probe_results({"192.168.1.42": None}, {})
    assert poller._state["08:11:22:33:44:55"].nbns_name == "LAB-PRINTER-01"


def test_run_active_probes_swallows_nbns_exception(monkeypatch):
    """NBNS phase raising must not propagate from _run_active_probes —
    the next phase still runs and the sweep cycle proceeds."""
    poller = _poller_with_one_host(monkeypatch)
    conn = _make_conn()

    async def _boom(*args, **kwargs):
        raise RuntimeError("nbns kaboom")

    async def _empty_ssdp(*args, **kwargs):
        return {}

    monkeypatch.setattr("diting.lan_probes.probe_nbns", _boom)
    monkeypatch.setattr("diting.lan_probes.probe_ssdp", _empty_ssdp)

    async def _go():
        await poller._run_active_probes(conn=conn)

    # Must not raise.
    asyncio.run(_go())


def test_run_active_probes_swallows_ssdp_exception(monkeypatch):
    poller = _poller_with_one_host(monkeypatch)
    conn = _make_conn()

    async def _empty_nbns(*args, **kwargs):
        return {}

    async def _boom(*args, **kwargs):
        raise RuntimeError("ssdp kaboom")

    monkeypatch.setattr("diting.lan_probes.probe_nbns", _empty_nbns)
    monkeypatch.setattr("diting.lan_probes.probe_ssdp", _boom)

    async def _go():
        await poller._run_active_probes(conn=conn)

    asyncio.run(_go())


def test_run_active_probes_returns_normally_on_total_phase_failure(monkeypatch):
    """All three probe phases failing must NOT raise. The sweep just
    yields no enrichments and the existing host state is preserved."""
    poller = _poller_with_one_host(monkeypatch)
    conn = _make_conn()

    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("diting.lan_probes.probe_nbns", _boom)
    monkeypatch.setattr("diting.lan_probes.probe_ssdp", _boom)

    async def _go():
        await poller._run_active_probes(conn=conn)

    asyncio.run(_go())
    # Host state untouched.
    assert poller._state["08:11:22:33:44:55"].nbns_name is None


def test_one_shot_probe_armed_runs_probes_once_then_clears(monkeypatch):
    """Setting _one_shot_probe_armed=True drives one probe sweep
    even when active_probe_enabled is False; the flag clears
    afterwards so subsequent sweeps revert to passive."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    calls = {"nbns": 0, "ssdp": 0}

    async def _fake_nbns(ips, **kwargs):
        calls["nbns"] += 1
        return {ip: None for ip in ips}

    async def _fake_ssdp(**kwargs):
        calls["ssdp"] += 1
        return {}

    monkeypatch.setattr("diting.lan_probes.probe_nbns", _fake_nbns)
    monkeypatch.setattr("diting.lan_probes.probe_ssdp", _fake_ssdp)
    # Subnet detection runs ifconfig; mock to deterministic value.
    monkeypatch.setattr(
        "diting.lan._detect_subnet",
        lambda _ip: (["192.168.1.42"], "192.168.1.0/24", 24, False),
    )
    # ARP cache: one host.
    monkeypatch.setattr(
        "diting.lan._read_arp_cache",
        lambda: [("192.168.1.42", "08:11:22:33:44:55", "en0")],
    )

    # Force the ping sweep to succeed without subprocess.
    async def _fake_sweep(hosts, **kwargs):
        return {ip: (True, 2.4) for ip in hosts}

    monkeypatch.setattr("diting.lan._sweep", _fake_sweep)

    conn = _make_conn()
    poller = LANInventoryPoller(
        connection_provider=lambda: conn,
        active_probe_enabled=False,  # scene-default off
    )

    async def _go():
        # Arm and drive one sweep — probes should fire.
        poller._one_shot_probe_armed = True
        await poller._do_sweep_and_emit()
        # The flag clears after the sweep.
        assert poller._one_shot_probe_armed is False
        # Run another sweep with no arming — probes should NOT fire
        # again (call counts stay at 1).
        await poller._do_sweep_and_emit()

    asyncio.run(_go())
    assert calls["nbns"] == 1
    assert calls["ssdp"] == 1


def test_one_shot_probe_armed_clears_even_when_no_host_replied(monkeypatch):
    """Consent has already been paid for the arming press — clear
    the flag whether or not any host answered."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    monkeypatch.setattr(
        "diting.lan._detect_subnet",
        lambda _ip: ([], "192.168.1.0/24", 24, False),
    )
    monkeypatch.setattr("diting.lan._read_arp_cache", lambda: [])

    async def _fake_sweep(hosts, **kwargs):
        return {ip: (False, None) for ip in hosts}

    async def _fake_nbns(ips, **kwargs):
        return {ip: None for ip in ips}

    async def _fake_ssdp(**kwargs):
        return {}

    monkeypatch.setattr("diting.lan._sweep", _fake_sweep)
    monkeypatch.setattr("diting.lan_probes.probe_nbns", _fake_nbns)
    monkeypatch.setattr("diting.lan_probes.probe_ssdp", _fake_ssdp)

    conn = _make_conn()
    poller = LANInventoryPoller(
        connection_provider=lambda: conn,
        active_probe_enabled=False,
    )

    async def _go():
        poller._one_shot_probe_armed = True
        await poller._do_sweep_and_emit()
        assert poller._one_shot_probe_armed is False

    asyncio.run(_go())


# ---------- LANInventoryPoller — state merge / first_seen preservation ----------

def _make_conn(
    ip="192.168.1.20",
    router="192.168.1.1",
    mac="84:2f:57:9b:15:59",
) -> Connection:
    return Connection(
        ssid="home",
        bssid="aa:bb:cc:dd:ee:ff",
        rssi_dbm=-50,
        noise_dbm=-90,
        tx_rate_mbps=300.0,
        channel=36,
        channel_width_mhz=80,
        channel_band="5G",
        phy_mode="11ax",
        security="WPA2",
        mcs_index=9,
        nss=2,
        timestamp=datetime.now(timezone.utc),
        interface_mac=mac,
        country_code="US",
        ip_address=ip,
        router_ip=router,
        max_link_speed_mbps=1200,
    )


def _run_one_sweep(
    poller: LANInventoryPoller,
    *,
    triples: list[tuple[str, str, str]],
    conn: Connection,
    monkeypatch,
) -> LANInventoryUpdate:
    """Drive one merge tick directly; bypass the asyncio scheduling
    plumbing for a deterministic state assertion."""

    async def _go() -> LANInventoryUpdate:
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(triples, conn=conn, now=now)
        # Reuse the snapshot-build logic by faking the rest of the
        # outer sweep path.
        return LANInventoryUpdate(
            hosts=tuple(sorted(poller._state.values(), key=lambda h: (
                0 if h.is_self else (1 if h.is_gateway else 2),
                tuple(int(p) for p in h.ip.split(".")),
            ))),
            subnet="192.168.1.0/24",
            subnet_capped=False,
            cap_prefix=24,
            last_sweep_at=now,
            next_sweep_at=now,
        )

    return asyncio.run(_go())


def test_lan_host_keyed_by_mac_keeps_first_seen_across_ip_change(monkeypatch):
    """The state dict is keyed by lowercase MAC. When the same MAC
    reappears at a new IP (DHCP rotation), ``first_seen`` is preserved
    while ``ip`` and ``last_seen`` update."""

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()
    snap1 = _run_one_sweep(
        poller,
        triples=[("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
        conn=conn,
        monkeypatch=monkeypatch,
    )
    first = next(h for h in snap1.hosts if h.mac == "de:ad:be:ef:00:01")
    original_first_seen = first.first_seen
    assert first.ip == "192.168.1.42"

    # Same MAC, different IP — DHCP rotation.
    snap2 = _run_one_sweep(
        poller,
        triples=[("192.168.1.77", "de:ad:be:ef:00:01", "en0")],
        conn=conn,
        monkeypatch=monkeypatch,
    )
    second = next(h for h in snap2.hosts if h.mac == "de:ad:be:ef:00:01")
    assert second.ip == "192.168.1.77"
    assert second.first_seen == original_first_seen
    assert second.last_seen > original_first_seen or second.last_seen >= original_first_seen


def test_lan_host_last_seen_updates_on_every_observation(monkeypatch):
    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()
    snap1 = _run_one_sweep(
        poller,
        triples=[("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
        conn=conn,
        monkeypatch=monkeypatch,
    )
    seen_first = next(h for h in snap1.hosts if h.mac == "de:ad:be:ef:00:01").last_seen

    snap2 = _run_one_sweep(
        poller,
        triples=[("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
        conn=conn,
        monkeypatch=monkeypatch,
    )
    seen_second = next(h for h in snap2.hosts if h.mac == "de:ad:be:ef:00:01").last_seen
    assert seen_second >= seen_first


# ---------- LANInventoryPoller — gateway / self flagging ----------

def test_self_pinned_first_with_is_self_flag(monkeypatch):
    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn(mac="84:2f:57:9b:15:59")
    snap = _run_one_sweep(
        poller,
        triples=[
            ("192.168.1.1", "aa:bb:cc:11:22:33", "en0"),
            ("192.168.1.55", "f4:5c:89:11:22:33", "en0"),
        ],
        conn=conn,
        monkeypatch=monkeypatch,
    )
    # Self appears first, then gateway, then other hosts.
    assert snap.hosts[0].is_self is True
    assert snap.hosts[0].mac == "84:2f:57:9b:15:59"
    assert snap.hosts[1].is_gateway is True
    assert snap.hosts[1].mac == "aa:bb:cc:11:22:33"


# ---------- LANInventoryPoller — Bonjour cross-ref ----------

def test_poller_pulls_bonjour_name_when_ip_matches(monkeypatch):
    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    bonjour = BonjourPoller()
    bonjour._state[("_airplay._tcp.local.", "x")] = _bonjour_device(
        ("192.168.1.42",), category="AirPlay"
    )
    poller = LANInventoryPoller(
        connection_provider=lambda: None,
        bonjour_poller=bonjour,
    )
    snap = _run_one_sweep(
        poller,
        triples=[("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
        conn=_make_conn(),
        monkeypatch=monkeypatch,
    )
    h = next(host for host in snap.hosts if host.mac == "de:ad:be:ef:00:01")
    assert h.bonjour_name == "ccy-MBP24-M4-Office"
    assert h.bonjour_services == ("AirPlay",)


# ---------- LANInventoryPoller — force_now / update flags ----------

def test_force_now_schedules_immediate_sweep():
    poller = LANInventoryPoller(connection_provider=lambda: None)

    async def _go() -> bool:
        # The sweep loop creates the event lazily; simulate that.
        poller._sweep_wakeup = asyncio.Event()
        poller.force_now()
        return poller._sweep_wakeup.is_set()

    assert asyncio.run(_go()) is True


def test_force_now_is_noop_before_loop_starts():
    poller = LANInventoryPoller(connection_provider=lambda: None)
    # _sweep_wakeup is None until events() is called.
    assert poller._sweep_wakeup is None
    poller.force_now()  # must not raise


def test_update_carries_cap_prefix_and_subnet_capped_flags():
    now = datetime.now(timezone.utc)
    upd = LANInventoryUpdate(
        hosts=(),
        subnet="10.5.7.0/24",
        subnet_capped=True,
        cap_prefix=24,
        last_sweep_at=now,
        next_sweep_at=now,
    )
    assert upd.subnet_capped is True
    assert upd.cap_prefix == 24


# ---------- LANInventoryPoller — does not start I/O before events() ----------

def test_poller_not_constructed_before_lan_view_entry():
    """Constructing the poller does not spawn any background task or
    open any subprocess. The TUI must control when sweeps start."""
    sweeps = []

    poller = LANInventoryPoller(connection_provider=lambda: sweeps.append("called") or None)
    # No events() call yet — the connection provider must not have
    # been invoked, and no sweep_wakeup event exists.
    assert sweeps == []
    assert poller._sweep_wakeup is None
    assert poller._state == {}


def test_poller_constructed_on_first_lan_view_entry():
    """Calling events() spawns the sweep loop. We drive one __anext__
    step (with a timeout, since connection_provider returns None and
    no update will ever be queued) so the loop body runs."""

    async def _go() -> None:
        poller = LANInventoryPoller(
            connection_provider=lambda: None,
            sweep_interval_s=1000,  # long
        )
        agen = poller.events()
        # Race: the events() body must run until it queues a get.
        # With connection_provider returning None, no update lands,
        # so we wait with a timeout and verify the loop is alive.
        try:
            await asyncio.wait_for(agen.__anext__(), timeout=0.2)
        except asyncio.TimeoutError:
            pass
        assert poller._sweep_wakeup is not None
        await agen.aclose()

    asyncio.run(_go())


# ------------------------------------------------------------------
# Transition events: LANHostSeenEvent / LANHostLeftEvent /
# LANHostDHCPRotationEvent
# ------------------------------------------------------------------

def test_poller_emits_seen_on_new_non_self_non_gateway_mac(monkeypatch):
    """A new MAC (not self, not gateway) entering the merge path
    accumulates one `LANHostSeenEvent` on `_pending_transitions`."""
    from diting.events import LANHostSeenEvent

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn(
        ip="192.168.1.20",
        router="192.168.1.1",
        mac="84:2f:57:9b:15:59",
    )

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn,
            now=now,
            sweep_results={"192.168.1.42": (True, 2.0)},
        )
        return poller.drain_transitions()

    out = asyncio.run(_go())
    seen = [e for e in out if isinstance(e, LANHostSeenEvent)]
    assert len(seen) == 1
    assert seen[0].mac == "de:ad:be:ef:00:01"
    assert seen[0].ip == "192.168.1.42"


def test_poller_skips_seen_for_self_and_gateway(monkeypatch):
    """Self injection AND gateway-row creation do NOT emit
    `LANHostSeenEvent` — those are noise on every diting launch."""
    from diting.events import LANHostSeenEvent

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn(
        ip="192.168.1.20",
        router="192.168.1.1",
        mac="84:2f:57:9b:15:59",
    )

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [
                # Gateway IP → is_gateway = True
                ("192.168.1.1", "aa:bb:cc:11:22:33", "en0"),
                # Self MAC
                ("192.168.1.20", "84:2f:57:9b:15:59", "en0"),
            ],
            conn=conn,
            now=now,
            sweep_results={
                "192.168.1.1": (True, 1.0),
                "192.168.1.20": (True, 0.1),
            },
        )
        return poller.drain_transitions()

    out = asyncio.run(_go())
    seen = [e for e in out if isinstance(e, LANHostSeenEvent)]
    # Neither self nor gateway should be in seen events.
    assert seen == []


def test_poller_emits_dhcp_rotation_before_ip_update(monkeypatch):
    """When a known MAC reappears at a new IP, the rotation event
    carries `previous_ip` (the old value) BEFORE the state entry's
    `ip` field gets updated."""
    from diting.events import LANHostDHCPRotationEvent

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        # Tick 1: first observation at IP A.
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn, now=now,
            sweep_results={"192.168.1.42": (True, 2.0)},
        )
        poller.drain_transitions()  # discard seen
        # Tick 2: same MAC, new IP.
        await poller._merge_arp_into_state(
            [("192.168.1.77", "de:ad:be:ef:00:01", "en0")],
            conn=conn, now=now,
            sweep_results={"192.168.1.77": (True, 2.4)},
        )
        return poller.drain_transitions()

    out = asyncio.run(_go())
    rotations = [e for e in out if isinstance(e, LANHostDHCPRotationEvent)]
    assert len(rotations) == 1
    assert rotations[0].previous_ip == "192.168.1.42"
    assert rotations[0].new_ip == "192.168.1.77"


def test_poller_emits_left_after_host_left_timeout(monkeypatch):
    """A tracked host whose `last_reachable_at` is older than
    `_HOST_LEFT_TIMEOUT_S` AND who is absent from the latest ARP
    triples → `LANHostLeftEvent` once; entry then removed."""
    from datetime import timedelta
    from diting.events import LANHostLeftEvent

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)
    # Shorten the timeout for the test.
    monkeypatch.setattr("diting.lan._HOST_LEFT_TIMEOUT_S", 1.0)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        t1 = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn, now=t1,
            sweep_results={"192.168.1.42": (True, 2.0)},
        )
        poller.drain_transitions()  # discard seen
        # Time advances past the timeout AND the host disappears
        # from ARP. Self-only triples → host is missing.
        t2 = t1 + timedelta(seconds=10)
        await poller._merge_arp_into_state(
            [],
            conn=conn, now=t2,
            sweep_results={},
        )
        return poller.drain_transitions(), poller._state

    out, state = asyncio.run(_go())
    left = [e for e in out if isinstance(e, LANHostLeftEvent)]
    assert len(left) == 1
    assert left[0].mac == "de:ad:be:ef:00:01"
    assert "de:ad:be:ef:00:01" not in state  # entry removed


def test_poller_does_not_re_emit_seen_for_known_mac(monkeypatch):
    """A known MAC observed again on a subsequent tick must NOT
    re-fire `LANHostSeenEvent`."""
    from diting.events import LANHostSeenEvent

    async def _no_rdns(_ip, *, timeout_s=0.5):
        return None

    monkeypatch.setattr("diting.lan._reverse_dns", _no_rdns)

    poller = LANInventoryPoller(connection_provider=lambda: None)
    conn = _make_conn()

    async def _go():
        now = datetime.now(timezone.utc)
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn, now=now,
            sweep_results={"192.168.1.42": (True, 2.0)},
        )
        first = poller.drain_transitions()
        # Same observation again.
        await poller._merge_arp_into_state(
            [("192.168.1.42", "de:ad:be:ef:00:01", "en0")],
            conn=conn, now=now,
            sweep_results={"192.168.1.42": (True, 2.0)},
        )
        second = poller.drain_transitions()
        return first, second

    first, second = asyncio.run(_go())
    seen1 = [e for e in first if isinstance(e, LANHostSeenEvent)]
    seen2 = [e for e in second if isinstance(e, LANHostSeenEvent)]
    assert len(seen1) == 1
    assert seen2 == []
