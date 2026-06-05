"""Unit tests for the seven BLE / Bonjour / LAN transition events.

Round-trips each event through `event_to_jsonl` AND through the
corresponding `EventLogger.emit_*` method, plus dataclass-shape
assertions, the None-field-omission convention, and the
empty-tuple-as-`[]` semantics from the spec.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from diting.event_log import EventLogger
from diting.events import (
    BLEDeviceLeftEvent,
    BLEDeviceSeenEvent,
    BonjourServiceLeftEvent,
    BonjourServiceSeenEvent,
    LANActiveProbeConsentedEvent,
    LANHostDHCPRotationEvent,
    LANHostLeftEvent,
    LANHostSeenEvent,
    event_to_jsonl,
)


def _read_jsonl(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


_T = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)


# ---------- BLE ----------

def test_ble_device_seen_carries_identity():
    ev = BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=("HID",),
    )
    assert ev.identifier == "abc"
    assert ev.name == "Magic Keyboard"
    assert ev.vendor == "Apple, Inc."
    assert ev.rssi_dbm == -55
    assert ev.service_categories == ("HID",)


def test_ble_device_seen_round_trip():
    ev = BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=("HID",),
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "ble_device_seen"
    assert payload["identifier"] == "abc"
    assert payload["name"] == "Magic Keyboard"
    assert payload["vendor"] == "Apple, Inc."
    assert payload["rssi_dbm"] == -55
    assert payload["service_categories"] == ["HID"]


def test_ble_device_left_carries_seen_for_seconds():
    ev = BLEDeviceLeftEvent(
        timestamp=_T, identifier="abc",
        name=None, vendor=None, last_rssi_dbm=-80,
        service_categories=(), seen_for_seconds=120.5,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "ble_device_left"
    assert payload["identifier"] == "abc"
    assert payload["last_rssi_dbm"] == -80
    # None fields omitted
    assert "name" not in payload
    assert "vendor" not in payload
    # Empty tuple → []
    assert payload["service_categories"] == []
    assert payload["seen_for_seconds"] == 120.5


def test_ble_device_left_round_trip():
    ev = BLEDeviceLeftEvent(
        timestamp=_T, identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        last_rssi_dbm=-55, service_categories=("HID",),
        seen_for_seconds=3600.0,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "ble_device_left"
    assert payload["seen_for_seconds"] == 3600.0


def test_ble_device_seen_carries_device_type_class_and_at_launch():
    # An anonymous-named iPhone seen at launch: the event carries the
    # decoded class so downstream rendering need not reduce it to
    # (anonymous), plus the at-launch census flag.
    ev = BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name=None, vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=(),
        device_type="Find My target", device_class="iPhone",
        at_launch=True,
    )
    assert ev.device_type == "Find My target"
    assert ev.device_class == "iPhone"
    assert ev.at_launch is True
    payload = json.loads(event_to_jsonl(ev))
    # Continuity type lands under `device_type`, NEVER colliding with
    # the envelope's `type` (the event kind).
    assert payload["type"] == "ble_device_seen"
    assert payload["device_type"] == "Find My target"
    assert payload["device_class"] == "iPhone"
    assert payload["at_launch"] is True

    # Defaults omit all three keys → legacy log lines stay diff-stable.
    plain = BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=("HID",),
    )
    plain_payload = json.loads(event_to_jsonl(plain))
    assert "device_type" not in plain_payload
    assert "device_class" not in plain_payload
    assert "at_launch" not in plain_payload


def test_ble_device_left_carries_device_type_class():
    ev = BLEDeviceLeftEvent(
        timestamp=_T, identifier="abc",
        name=None, vendor="Apple, Inc.",
        last_rssi_dbm=-80, service_categories=(),
        seen_for_seconds=12.0,
        device_type="Find My target", device_class="iPhone",
    )
    assert ev.device_type == "Find My target"
    assert ev.device_class == "iPhone"
    payload = json.loads(event_to_jsonl(ev))
    assert payload["device_type"] == "Find My target"
    assert payload["device_class"] == "iPhone"
    # A left is never part of the at-launch census.
    assert "at_launch" not in payload


# ---------- Bonjour ----------

def test_bonjour_service_seen_carries_addresses():
    ev = BonjourServiceSeenEvent(
        timestamp=_T,
        service_type="_airplay._tcp.local.",
        name="Blue Pod._airplay._tcp.local.",
        host="Blue-Pod", category="AirPlay", vendor="Apple, Inc.",
        addresses=("192.168.1.42",),
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "bonjour_service_seen"
    assert payload["service_type"] == "_airplay._tcp.local."
    assert payload["addresses"] == ["192.168.1.42"]


def test_bonjour_service_seen_round_trip():
    ev = BonjourServiceSeenEvent(
        timestamp=_T,
        service_type="_googlecast._tcp.local.",
        name="Office Display._googlecast._tcp.local.",
        host=None, category="Chromecast", vendor=None,
        addresses=(),
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "bonjour_service_seen"
    assert "host" not in payload  # None omitted
    assert "vendor" not in payload
    assert payload["addresses"] == []  # empty tuple → []


def test_bonjour_service_left_carries_seen_for_seconds():
    ev = BonjourServiceLeftEvent(
        timestamp=_T,
        service_type="_raop._tcp.local.",
        name="HomePod._raop._tcp.local.",
        host="HomePod", category="AirPlay audio", vendor="Apple, Inc.",
        seen_for_seconds=86400.0,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "bonjour_service_left"
    assert payload["seen_for_seconds"] == 86400.0


def test_bonjour_service_left_round_trip():
    ev = BonjourServiceLeftEvent(
        timestamp=_T,
        service_type="_raop._tcp.local.",
        name="HomePod._raop._tcp.local.",
        host="HomePod", category="AirPlay audio", vendor="Apple, Inc.",
        seen_for_seconds=300.0,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "bonjour_service_left"


# ---------- LAN ----------

def test_lan_host_seen_carries_mac_identity():
    ev = LANHostSeenEvent(
        timestamp=_T,
        mac="de:ad:be:ef:00:01", ip="192.168.1.42",
        vendor="Apple, Inc.", hostname="my-mac.local",
        bonjour_name="ccy-MBP24-M4-Office",
        is_randomised_mac=False,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "lan_host_seen"
    assert payload["mac"] == "de:ad:be:ef:00:01"
    assert payload["ip"] == "192.168.1.42"
    assert payload["is_randomised_mac"] is False


def test_lan_host_seen_round_trip():
    ev = LANHostSeenEvent(
        timestamp=_T,
        mac="02:11:22:33:44:55", ip="192.168.1.99",
        vendor=None, hostname=None, bonjour_name=None,
        is_randomised_mac=True,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "lan_host_seen"
    assert payload["is_randomised_mac"] is True
    # None fields stripped
    assert "vendor" not in payload
    assert "hostname" not in payload
    assert "bonjour_name" not in payload


def test_lan_host_dhcp_rotation_carries_previous_and_new_ip():
    ev = LANHostDHCPRotationEvent(
        timestamp=_T,
        mac="de:ad:be:ef:00:01",
        previous_ip="192.168.1.42", new_ip="192.168.1.77",
        vendor="Apple, Inc.", hostname=None,
        bonjour_name="ccy-MBP24-M4-Office",
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "lan_host_dhcp_rotation"
    assert payload["previous_ip"] == "192.168.1.42"
    assert payload["new_ip"] == "192.168.1.77"


def test_lan_host_dhcp_rotation_round_trip():
    ev = LANHostDHCPRotationEvent(
        timestamp=_T,
        mac="aa:bb:cc:dd:ee:ff",
        previous_ip="10.0.0.5", new_ip="10.0.0.99",
        vendor=None, hostname=None, bonjour_name=None,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["mac"] == "aa:bb:cc:dd:ee:ff"


def test_lan_host_left_carries_last_reachable_ago():
    ev = LANHostLeftEvent(
        timestamp=_T,
        mac="de:ad:be:ef:00:01", ip="192.168.1.42",
        vendor="Apple, Inc.", hostname=None,
        bonjour_name="ccy-MBP24-M4-Office",
        is_randomised_mac=False,
        seen_for_seconds=7200.5,
        last_reachable_ago_seconds=305.0,
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["type"] == "lan_host_left"
    assert payload["seen_for_seconds"] == 7200.5
    assert payload["last_reachable_ago_seconds"] == 305.0


def test_lan_host_left_round_trip():
    ev = LANHostLeftEvent(
        timestamp=_T,
        mac="aa:bb:cc:dd:ee:ff", ip="192.168.1.99",
        vendor=None, hostname=None, bonjour_name=None,
        is_randomised_mac=True,
        seen_for_seconds=600.0,
        last_reachable_ago_seconds=None,
    )
    payload = json.loads(event_to_jsonl(ev))
    # last_reachable_ago_seconds is None → omitted
    assert "last_reachable_ago_seconds" not in payload


# ---------- None omission + empty-tuple-as-array ----------

def test_new_events_omit_none_fields_from_jsonl():
    """Fields whose value is None SHALL NOT appear in the JSONL line.
    Tuple-valued fields whose value is `()` SHALL appear as `[]`."""
    ev = BLEDeviceSeenEvent(
        timestamp=_T, identifier="anon",
        name=None, vendor=None, rssi_dbm=None,
        service_categories=(),
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload == {
        "ts": payload["ts"],
        "type": "ble_device_seen",
        "identifier": "anon",
        "service_categories": [],
    }


def test_new_events_serialise_empty_tuple_as_empty_list():
    """`addresses=()` survives as `[]` so consumers can distinguish
    'no addresses advertised' from 'field absent'."""
    ev = BonjourServiceSeenEvent(
        timestamp=_T, service_type="_airplay._tcp.local.",
        name="x._airplay._tcp.local.",
        host=None, category=None, vendor=None, addresses=(),
    )
    payload = json.loads(event_to_jsonl(ev))
    assert payload["addresses"] == []


# ---------- EventLogger emit methods + no-op contract ----------

def test_emit_ble_device_seen_writes_locale_stable_type(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_ble_device_seen(BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=("HID",),
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["type"] == "ble_device_seen"
    assert row["identifier"] == "abc"
    assert row["name"] == "Magic Keyboard"


def test_emit_ble_device_left_includes_seen_for_seconds(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_ble_device_left(BLEDeviceLeftEvent(
        timestamp=_T, identifier="abc",
        name=None, vendor=None, last_rssi_dbm=-80,
        service_categories=(), seen_for_seconds=12.0,
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["type"] == "ble_device_left"
    assert row["seen_for_seconds"] == 12.0
    assert row["service_categories"] == []
    assert "name" not in row
    assert "vendor" not in row


def test_emit_ble_device_seen_writes_device_type_class_at_launch(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_ble_device_seen(BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name=None, vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=(),
        device_type="Find My target", device_class="iPhone",
        at_launch=True,
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    # `type` stays the event kind; the Continuity type is `device_type`.
    assert row["type"] == "ble_device_seen"
    assert row["device_type"] == "Find My target"
    assert row["device_class"] == "iPhone"
    assert row["at_launch"] is True


def test_emit_ble_device_seen_omits_device_type_when_none_and_at_launch_when_false(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_ble_device_seen(BLEDeviceSeenEvent(
        timestamp=_T, identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=("HID",),
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert "device_type" not in row
    assert "device_class" not in row
    assert "at_launch" not in row


def test_emit_ble_device_left_writes_device_type_under_device_type_key(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_ble_device_left(BLEDeviceLeftEvent(
        timestamp=_T, identifier="abc",
        name=None, vendor="Apple, Inc.", last_rssi_dbm=-80,
        service_categories=(), seen_for_seconds=12.0,
        device_type="Find My target", device_class=None,
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["type"] == "ble_device_left"
    assert row["device_type"] == "Find My target"
    assert "device_class" not in row  # None-omitted
    assert "at_launch" not in row     # left never carries it


def test_emit_bonjour_service_seen_writes_locale_stable_type(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_bonjour_service_seen(BonjourServiceSeenEvent(
        timestamp=_T,
        service_type="_airplay._tcp.local.",
        name="Blue Pod._airplay._tcp.local.",
        host="Blue-Pod", category="AirPlay", vendor="Apple, Inc.",
        addresses=("192.168.1.42",),
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["type"] == "bonjour_service_seen"
    assert row["category"] == "AirPlay"


def test_emit_lan_host_dhcp_rotation_writes_previous_and_new_ip(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_lan_host_dhcp_rotation(LANHostDHCPRotationEvent(
        timestamp=_T,
        mac="de:ad:be:ef:00:01",
        previous_ip="192.168.1.42", new_ip="192.168.1.77",
        vendor="Apple, Inc.", hostname=None,
        bonjour_name="ccy-MBP24-M4-Office",
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["type"] == "lan_host_dhcp_rotation"
    assert row["previous_ip"] == "192.168.1.42"
    assert row["new_ip"] == "192.168.1.77"


def test_disabled_logger_swallows_all_seven_new_methods():
    """A no-op logger (sink=None) accepts every new emit method
    without opening a file or raising."""
    logger = EventLogger(None)
    logger.emit_ble_device_seen(BLEDeviceSeenEvent(
        timestamp=_T, identifier="x",
        name=None, vendor=None, rssi_dbm=None,
        service_categories=(),
    ))
    logger.emit_ble_device_left(BLEDeviceLeftEvent(
        timestamp=_T, identifier="x",
        name=None, vendor=None, last_rssi_dbm=None,
        service_categories=(), seen_for_seconds=0.0,
    ))
    logger.emit_bonjour_service_seen(BonjourServiceSeenEvent(
        timestamp=_T,
        service_type="_x._tcp.local.", name="x._x._tcp.local.",
        host=None, category=None, vendor=None, addresses=(),
    ))
    logger.emit_bonjour_service_left(BonjourServiceLeftEvent(
        timestamp=_T,
        service_type="_x._tcp.local.", name="x._x._tcp.local.",
        host=None, category=None, vendor=None,
        seen_for_seconds=0.0,
    ))
    logger.emit_lan_host_seen(LANHostSeenEvent(
        timestamp=_T, mac="aa:bb:cc:dd:ee:ff", ip="0.0.0.0",
        vendor=None, hostname=None, bonjour_name=None,
        is_randomised_mac=False,
    ))
    logger.emit_lan_host_left(LANHostLeftEvent(
        timestamp=_T, mac="aa:bb:cc:dd:ee:ff", ip="0.0.0.0",
        vendor=None, hostname=None, bonjour_name=None,
        is_randomised_mac=False,
        seen_for_seconds=0.0,
        last_reachable_ago_seconds=None,
    ))
    logger.emit_lan_host_dhcp_rotation(LANHostDHCPRotationEvent(
        timestamp=_T, mac="aa:bb:cc:dd:ee:ff",
        previous_ip="0.0.0.0", new_ip="0.0.0.1",
        vendor=None, hostname=None, bonjour_name=None,
    ))


# ---------- LANActiveProbeConsentedEvent ----------


def test_lan_active_probe_consented_dataclass_carries_required_fields():
    ev = LANActiveProbeConsentedEvent(
        timestamp=_T,
        scene="public",
        ssid="HotelGuest",
        nbns_packets=8,
        ssdp_packets=1,
        mdns_packets=1,
    )
    assert ev.scene == "public"
    assert ev.ssid == "HotelGuest"
    assert ev.nbns_packets == 8
    assert ev.ssdp_packets == 1
    assert ev.mdns_packets == 1


def test_lan_active_probe_consented_logger_writes_jsonl(tmp_path):
    path = tmp_path / "consent.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_lan_active_probe_consented(LANActiveProbeConsentedEvent(
        timestamp=_T,
        scene="public",
        ssid="HotelGuest",
        nbns_packets=8,
        ssdp_packets=1,
        mdns_packets=1,
    ))
    logger.close()
    [row] = _read_jsonl(path)
    assert row["type"] == "lan_active_probe_consented"
    assert row["scene"] == "public"
    assert row["ssid"] == "HotelGuest"
    assert row["nbns_packets"] == 8
    assert row["ssdp_packets"] == 1
    assert row["mdns_packets"] == 1


def test_lan_active_probe_consented_omits_ssid_when_none(tmp_path):
    path = tmp_path / "consent.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_lan_active_probe_consented(LANActiveProbeConsentedEvent(
        timestamp=_T,
        scene="public",
        ssid=None,
        nbns_packets=0,
        ssdp_packets=1,
        mdns_packets=1,
    ))
    logger.close()
    [row] = _read_jsonl(path)
    assert "ssid" not in row
    assert row["scene"] == "public"
    assert row["nbns_packets"] == 0


def test_lan_active_probe_consented_logger_with_none_path_is_noop():
    """Constructed with path=None, every emit_* must be a silent
    no-op. The TUI uses this shape when --log is absent."""
    logger = EventLogger(None)
    # Must NOT raise.
    logger.emit_lan_active_probe_consented(LANActiveProbeConsentedEvent(
        timestamp=_T,
        scene="public",
        ssid="x",
        nbns_packets=1,
        ssdp_packets=1,
        mdns_packets=1,
    ))


# ---- expand-event-ring: the ring's size bound ----

def _seen(i: int) -> BLEDeviceSeenEvent:
    return BLEDeviceSeenEvent(
        timestamp=_T, identifier=f"id-{i}", name=None, vendor=None,
        rssi_dbm=-60, service_categories=(),
    )


def test_ring_default_capacity_overflow_drops_oldest():
    from diting.events import EventRing

    ring = EventRing()
    for i in range(1001):
        ring.push(_seen(i))
    snap = ring.snapshot()
    assert len(snap) == 1000
    # Newest-first: the 1001st event leads, the very first rolled off.
    assert snap[0].identifier == "id-1000"
    assert all(ev.identifier != "id-0" for ev in snap)


def test_ring_custom_capacity_honored():
    from diting.events import EventRing

    ring = EventRing(capacity=5)
    for i in range(6):
        ring.push(_seen(i))
    snap = ring.snapshot()
    assert len(snap) == 5
    assert snap[0].identifier == "id-5"
    assert all(ev.identifier != "id-0" for ev in snap)
