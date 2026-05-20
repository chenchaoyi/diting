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

    reachable, rtt = asyncio.run(_go())
    assert reachable is True
    assert rtt == pytest.approx(2.439, abs=0.001)


def test_ping_one_returns_none_rtt_on_nonzero_exit(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            return _fake_ping_proc(2, b"")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    assert asyncio.run(_go()) == (False, None)


def test_ping_one_returns_true_none_when_stdout_unparseable(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            # Exit 0 but stdout has no "time=X ms" segment.
            return _fake_ping_proc(0, b"weird-build-output-without-rtt")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    assert asyncio.run(_go()) == (True, None)


def test_ping_one_returns_false_none_on_oserror(monkeypatch):
    async def _go():
        async def _fake_exec(*_args, **_kwargs):
            raise OSError("ENOENT")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return await _ping_one("192.168.1.1")

    assert asyncio.run(_go()) == (False, None)


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
    """`_sweep` must return ``{ip: (reachable, rtt_ms)}`` not None.
    The merge step reads this dict to populate `last_rtt_ms` /
    `last_reachable_at` on each LANHost."""
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
    reachable, rtt = result["192.168.1.1"]
    assert reachable is True
    assert rtt == pytest.approx(2.0, abs=0.001)


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


def test_oui_refresh_script_parses_csv_to_aabbcc_keys():
    """`parse_csv` normalises 24-bit OUIs to the canonical lowercase
    colon-separated form the existing JSON file uses."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from refresh_ouis import parse_csv  # type: ignore

    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        'MA-L,001D0F,"TP-LINK TECHNOLOGIES CO.,LTD.","example address"\n'
        'MA-L,00038F,"Wave Wireless Networking","123 Example St"\n'
    )
    out = parse_csv(csv_text)
    assert out["00:1d:0f"] == "TP-LINK TECHNOLOGIES CO.,LTD."
    assert out["00:03:8f"] == "Wave Wireless Networking"


def test_oui_refresh_script_skips_non_ma_l_rows():
    """MA-M (28-bit) and MA-S (36-bit) sub-allocations are not used
    by our lookup function today — they would have keys longer than
    6 hex characters and would never match `lookup_oui_vendor`.
    `parse_csv` must filter them out so the resulting JSON stays
    consistent with the lookup contract."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from refresh_ouis import parse_csv  # type: ignore

    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        'MA-L,AABBCC,"Vendor A","addr"\n'
        'MA-M,DDEEFF0,"Vendor B (MA-M)","addr"\n'
        'MA-S,11223345678,"Vendor C (MA-S)","addr"\n'
    )
    out = parse_csv(csv_text)
    assert out == {"aa:bb:cc": "Vendor A"}


def test_oui_refresh_script_dedupes_repeated_assignments():
    """IEEE occasionally lists the same OUI twice under slight
    naming variations. First wins; second is dropped."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from refresh_ouis import parse_csv  # type: ignore

    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        'MA-L,AABBCC,"First Variant Inc","addr1"\n'
        'MA-L,AABBCC,"Second Variant LLC","addr2"\n'
    )
    out = parse_csv(csv_text)
    assert out == {"aa:bb:cc": "First Variant Inc"}


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
    host, cats = idx["192.168.1.42"]
    assert host == "ccy-MBP24-M4-Office"
    assert cats == ("AirPlay",)


def test_bonjour_cross_ref_aggregates_categories():
    poller = BonjourPoller()
    poller._state[("a", "x")] = _bonjour_device(("192.168.1.42",), category="AirPlay", name="x")
    poller._state[("b", "y")] = _bonjour_device(("192.168.1.42",), category="AirPlay audio", name="y")
    poller._state[("c", "z")] = _bonjour_device(("192.168.1.42",), category="Apple Companion", name="z")
    idx = _build_bonjour_index(poller)
    _, cats = idx["192.168.1.42"]
    assert set(cats) == {"AirPlay", "AirPlay audio", "Apple Companion"}


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
