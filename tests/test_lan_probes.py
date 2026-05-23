"""Tests for the active-discovery layer (`diting.lan_probes`).

Wire-protocol encoding + parsing are unit-tested against synthetic
byte sequences. The network senders themselves (probe_nbns,
probe_ssdp, fetch_upnp_location) are only exercised at the
fail-soft level — actually hitting UDP / HTTP requires integration
testing that lives outside this suite.
"""
from __future__ import annotations

import asyncio
import struct

import pytest

from diting.lan_probes import (
    NBNSNameEntry,
    SSDPResponse,
    SSDP_MSEARCH_PACKET,
    encode_nbns_status_query,
    fetch_upnp_location,
    parse_nbns_status_response,
    parse_ssdp_response,
    parse_upnp_location_xml,
    resolve_lan_active_probe,
    resolve_upnp_fetch_enabled,
    workstation_name,
)


# ---------- NBNS encode ----------


def test_encode_nbns_status_query_is_50_bytes():
    """RFC 1002 §4.2.18 wildcard NBSTAT query: 12-byte header + 38-byte
    question section = 50 bytes total."""
    packet = encode_nbns_status_query(0x1234)
    assert len(packet) == 50


def test_encode_nbns_status_query_uses_txn_id():
    packet = encode_nbns_status_query(0xABCD)
    assert packet[:2] == b"\xab\xcd"


def test_encode_nbns_status_query_rejects_out_of_range_txn_id():
    with pytest.raises(ValueError):
        encode_nbns_status_query(-1)
    with pytest.raises(ValueError):
        encode_nbns_status_query(0x10000)


def test_encode_nbns_status_query_uses_wildcard_name_and_nbstat_type():
    packet = encode_nbns_status_query(0x0001)
    # After 12-byte header: length byte 0x20, then 32-byte encoded
    # wildcard "CKAAAA...", then null terminator.
    assert packet[12] == 0x20
    assert packet[13 : 13 + 32] == b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert packet[45] == 0x00
    # type NBSTAT 0x0021, class IN 0x0001
    qtype, qclass = struct.unpack(">HH", packet[46:50])
    assert qtype == 0x0021
    assert qclass == 0x0001


# ---------- NBNS response parse ----------


def _build_nbns_response(name_entries: list[tuple[str, int, bool]]) -> bytes:
    """Helper: assemble a minimal NBNS Status Response by hand.

    Each entry is ``(name, suffix, group)``. Names are padded to 15
    bytes with spaces. The 2-byte flags field encodes the group bit
    in the high bit.
    """
    header = struct.pack(
        ">HHHHHH",
        0x1234,  # txn id
        0x8400,  # flags: response | authoritative
        0x0000,  # questions
        0x0001,  # answer count
        0x0000,
        0x0000,
    )
    # Question section: even though answer-only, the response often
    # mirrors the question. Real responders sometimes omit it; we
    # include it because the parser walks past it.
    q_name = b"\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00"
    # Above is 1 + 32 + 1 = 34 bytes. Adjusted to length-prefix 0x20
    # (32 chars). Trim back to 0x20:
    q_name = bytes([0x20]) + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:32] + b"\x00"
    q_tail = struct.pack(">HH", 0x0021, 0x0001)
    question = q_name + q_tail

    # Answer record. We use a compressed name pointer (0xC00C) → offset 12
    # (where the question name lived). Type NBSTAT, class IN, TTL 0,
    # then RDATA.
    rr_header = b"\xc0\x0c" + struct.pack(">HHIH", 0x0021, 0x0001, 0, 0)
    rdata = bytes([len(name_entries)])
    for name, suffix, group in name_entries:
        nm = name.encode("ascii").ljust(15, b" ")
        flags = 0x8000 if group else 0x0000
        rdata += nm + bytes([suffix]) + struct.pack(">H", flags)
    # Rewrite RDLENGTH (we deferred above with 0).
    rr_with_rdlen = (
        b"\xc0\x0c"
        + struct.pack(
            ">HHIH",
            0x0021,
            0x0001,
            0,
            len(rdata),
        )
        + rdata
    )
    return header + question + rr_with_rdlen


def test_parse_nbns_returns_name_table():
    data = _build_nbns_response(
        [("LAB-PRINTER-01", 0x00, False), ("WORKGROUP", 0x00, True)],
    )
    entries = parse_nbns_status_response(data)
    assert len(entries) == 2
    assert entries[0] == NBNSNameEntry(name="LAB-PRINTER-01", suffix=0x00, group=False)
    assert entries[1] == NBNSNameEntry(name="WORKGROUP", suffix=0x00, group=True)


def test_parse_nbns_workstation_name_picks_zero_suffix_unique():
    entries = [
        NBNSNameEntry(name="WORKGROUP", suffix=0x00, group=True),
        NBNSNameEntry(name="LAB-PRINTER-01", suffix=0x00, group=False),
        NBNSNameEntry(name="LAB-PRINTER-01", suffix=0x20, group=False),
    ]
    assert workstation_name(entries) == "LAB-PRINTER-01"


def test_parse_nbns_skips_group_names():
    entries = [
        NBNSNameEntry(name="WORKGROUP", suffix=0x00, group=True),
    ]
    assert workstation_name(entries) is None


def test_parse_nbns_truncated_data_returns_empty():
    # 8 bytes is shorter than the 12-byte header — must not raise.
    assert parse_nbns_status_response(b"\x00" * 8) == []


def test_parse_nbns_malformed_data_does_not_raise():
    # Plausible-looking but truncated answer section.
    data = _build_nbns_response([("X", 0x00, False)])
    # Truncate to drop the last name-table entry's flags bytes.
    assert parse_nbns_status_response(data[:-2]) == []  # final entry skipped
    # And a fully random blob should not raise either.
    assert parse_nbns_status_response(b"this is not nbns at all") == []


# ---------- SSDP packet shape ----------


def test_ssdp_msearch_packet_has_required_headers():
    p = SSDP_MSEARCH_PACKET
    assert p.startswith(b"M-SEARCH * HTTP/1.1\r\n")
    assert b"HOST: 239.255.255.250:1900\r\n" in p
    assert b'MAN: "ssdp:discover"\r\n' in p
    assert b"MX: 2\r\n" in p
    assert b"ST: ssdp:all\r\n" in p
    assert p.endswith(b"\r\n\r\n")


def test_ssdp_msearch_packet_can_set_mx():
    """probe_ssdp swaps the MX header at send time. The default
    bytes here are what gets templated."""
    swapped = SSDP_MSEARCH_PACKET.replace(b"MX: 2\r\n", b"MX: 5\r\n")
    assert b"MX: 5\r\n" in swapped
    assert b"MX: 2\r\n" not in swapped


# ---------- SSDP response parse ----------


_SAMPLE_SSDP_RESPONSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"CACHE-CONTROL: max-age=1800\r\n"
    b"DATE: Sat, 23 May 2026 04:20:00 GMT\r\n"
    b"EXT:\r\n"
    b"LOCATION: http://192.168.124.7:1900/description.xml\r\n"
    b"SERVER: Linux/3.10 UPnP/1.0 HiSenseTV/2024.01\r\n"
    b"ST: upnp:rootdevice\r\n"
    b"USN: uuid:abcd-1234::upnp:rootdevice\r\n"
    b"\r\n"
)


def test_parse_ssdp_extracts_server_location_usn_st():
    r = parse_ssdp_response(_SAMPLE_SSDP_RESPONSE, ip="192.168.124.7")
    assert r is not None
    assert r.ip == "192.168.124.7"
    assert r.server == "Linux/3.10 UPnP/1.0 HiSenseTV/2024.01"
    assert r.location == "http://192.168.124.7:1900/description.xml"
    assert r.st == "upnp:rootdevice"
    assert r.usn == "uuid:abcd-1234::upnp:rootdevice"


def test_parse_ssdp_picks_source_ip_from_caller():
    """The ip field is set by the socket recvfrom address, NOT by
    any header — UPnP devices lie about their LOCATION host."""
    r = parse_ssdp_response(_SAMPLE_SSDP_RESPONSE, ip="10.0.0.1")
    assert r is not None and r.ip == "10.0.0.1"


def test_parse_ssdp_rejects_non_200_response():
    # 404
    resp = (
        b"HTTP/1.1 404 Not Found\r\n"
        b"SERVER: x\r\n\r\n"
    )
    assert parse_ssdp_response(resp, ip="1.2.3.4") is None


def test_parse_ssdp_ignores_malformed_payload():
    assert parse_ssdp_response(b"not http at all", ip="1.2.3.4") is None
    assert parse_ssdp_response(b"", ip="1.2.3.4") is None


# ---------- UPnP XML parse ----------


_SAMPLE_UPNP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion>
    <major>1</major><minor>0</minor>
  </specVersion>
  <device>
    <friendlyName>Living Room TV</friendlyName>
    <modelName>HiSense 75U7K</modelName>
    <UDN>uuid:abcd</UDN>
  </device>
</root>
"""


def test_parse_upnp_xml_extracts_friendly_name_and_model_name():
    friendly, model = parse_upnp_location_xml(_SAMPLE_UPNP_XML)
    assert friendly == "Living Room TV"
    assert model == "HiSense 75U7K"


def test_parse_upnp_xml_returns_none_on_missing_fields():
    xml = b"""<root><device><UDN>uuid:1</UDN></device></root>"""
    friendly, model = parse_upnp_location_xml(xml)
    assert friendly is None
    assert model is None


def test_parse_upnp_xml_returns_none_on_malformed_xml():
    friendly, model = parse_upnp_location_xml(b"<not closed")
    assert friendly is None
    assert model is None


def test_parse_upnp_xml_ignores_external_entity_doctype():
    """Stdlib ElementTree does not resolve external entities. Pass a
    DOCTYPE-laced payload — the parser may reject or silently strip
    the entity; either way it must not fetch the external URL or
    raise out of the function."""
    xml = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE root ['
        b'  <!ENTITY xxe SYSTEM "http://attacker.example.com/secret">'
        b']>'
        b'<root xmlns="urn:schemas-upnp-org:device-1-0">'
        b'  <device>'
        b'    <friendlyName>safe-default</friendlyName>'
        b'  </device>'
        b'</root>'
    )
    friendly, model = parse_upnp_location_xml(xml)
    # Either: (a) ET refused the DOCTYPE → (None, None), or (b) ET
    # parsed the device but skipped the entity → ("safe-default", None).
    # Both are acceptable; the contract is "no external fetch, no
    # exception leak". Assert one of the two outcomes.
    assert friendly in (None, "safe-default")
    assert model is None


# ---------- fetch_upnp_location async wrapper ----------


def test_fetch_upnp_location_returns_none_for_none_url():
    f, m = asyncio.run(fetch_upnp_location(None))
    assert f is None
    assert m is None


def test_fetch_upnp_location_returns_none_for_empty_url():
    f, m = asyncio.run(fetch_upnp_location(""))
    assert f is None
    assert m is None


def test_fetch_upnp_location_swallows_url_errors():
    # http://0.0.0.0:1/nope/ — definitely unreachable, will raise.
    # We assert the wrapper swallows the urllib error.
    f, m = asyncio.run(
        fetch_upnp_location("http://0.0.0.0:1/nope.xml", timeout_s=0.2),
    )
    assert f is None
    assert m is None


# ---------- env var resolution ----------


def test_resolve_lan_active_probe_scene_default_when_env_unset():
    assert resolve_lan_active_probe(env={}, scene_default=True) is True
    assert resolve_lan_active_probe(env={}, scene_default=False) is False


def test_resolve_lan_active_probe_env_overrides_scene_default():
    assert (
        resolve_lan_active_probe(
            env={"DITING_LAN_PROBE": "1"}, scene_default=False,
        )
        is True
    )
    assert (
        resolve_lan_active_probe(
            env={"DITING_LAN_PROBE": "0"}, scene_default=True,
        )
        is False
    )


def test_resolve_lan_active_probe_env_blank_falls_through():
    # A user clearing the var with `DITING_LAN_PROBE= diting` must
    # land on the scene default.
    assert (
        resolve_lan_active_probe(
            env={"DITING_LAN_PROBE": ""}, scene_default=True,
        )
        is True
    )


def test_resolve_lan_active_probe_env_invalid_falls_through():
    # Anything not "0" / "1" / empty falls back to the scene default.
    # (The CLI wrapper additionally prints a stderr warning.)
    assert (
        resolve_lan_active_probe(
            env={"DITING_LAN_PROBE": "yes"}, scene_default=False,
        )
        is False
    )


def test_resolve_upnp_fetch_enabled_default_true():
    assert resolve_upnp_fetch_enabled(env={}) is True


def test_resolve_upnp_fetch_enabled_env_zero_disables():
    assert (
        resolve_upnp_fetch_enabled(env={"DITING_LAN_UPNP_FETCH": "0"})
        is False
    )


def test_resolve_upnp_fetch_enabled_env_one_enables():
    assert (
        resolve_upnp_fetch_enabled(env={"DITING_LAN_UPNP_FETCH": "1"})
        is True
    )


def test_resolve_upnp_fetch_enabled_env_invalid_falls_back_to_default():
    assert (
        resolve_upnp_fetch_enabled(env={"DITING_LAN_UPNP_FETCH": "yes"})
        is True
    )
