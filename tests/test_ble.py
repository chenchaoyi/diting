"""Tests for the BLE scanning layer.

Covers (1) line parsing, (2) vendor lookup, (3) service category
inference, (4) device TTL expiry, (5) UUID-rotation fuzzy merge,
(6) permission denied path, (7) helper subprocess crash, and (8)
malformed JSON line resilience.

The Swift helper itself is not exercised here — the tests inject a
fake stdout stream into BLEPoller via the ``_spawn`` constructor seam,
the same boundary mocked by ``test_helper.py`` for the existing
``scan`` subcommand. This keeps the suite hermetic on CI runners that
have neither Bluetooth hardware nor a built helper bundle.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from wifiscope import ble
from wifiscope.ble import (
    BLEDevice,
    BLEPoller,
    BLEScanUpdate,
    detect_advertisement,
    expire_devices,
    load_vendors,
    lookup_vendor,
    merge_for_display,
    service_category,
    update_from_line,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Realistic helper output line for an Apple device (company ID 76).
SAMPLE_AIRPODS = json.dumps({
    "ts": "2026-05-06T12:34:56.789Z",
    "id": "550E8400-E29B-41D4-A716-446655440000",
    "name": "AirPods Pro",
    "rssi_dbm": -52,
    "is_connectable": True,
    "service_uuids": ["180A", "FE9F"],
    "manufacturer_id": 76,
    "manufacturer_hex": "4c001907cafebabedeadbeef",
})

VENDORS = {76: "Apple, Inc.", 117: "Samsung Electronics Co. Ltd."}


# ------------------------------------------------------------------
# 1. JSON line parsing happy path
# ------------------------------------------------------------------

def test_parse_advertisement_populates_all_fields():
    """A well-formed JSONL event becomes a BLEDevice with every
    field populated and identifier lower-cased."""
    devices: dict[str, BLEDevice] = {}
    state = update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS)
    assert state is None
    assert len(devices) == 1
    d = next(iter(devices.values()))
    assert d.identifier == "550e8400-e29b-41d4-a716-446655440000"
    assert d.name == "AirPods Pro"
    assert d.vendor == "Apple, Inc."
    assert d.vendor_id == 76
    assert d.rssi_dbm == -52
    assert d.is_connectable is True
    assert d.services == ("180A", "FE9F")
    assert d.ad_count == 1
    assert d.merged_count == 1
    assert d.first_seen == d.last_seen


def test_parse_subsequent_advertisement_carries_history():
    """A repeat ad for the same identifier keeps first_seen and bumps
    ad_count; last_seen advances to the newer event."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=3)
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t0)
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t1)
    d = next(iter(devices.values()))
    assert d.ad_count == 2
    assert d.first_seen == t0
    assert d.last_seen == t1


def test_vendor_id_carries_forward_when_scan_response_omits_manufacturer_data():
    """Scan-response packets and probe-response packets routinely arrive
    without the manufacturer-data IE that the preceding primary
    advertisement carried. Without a carry-forward the vendor_id flips
    to None, the vendor column flickers Apple↔(unknown), and — worse —
    merge_for_display's (vendor_id, name) bucketing fragments rotated-
    UUID instances of the same physical device into separate rows. The
    fix mirrors the existing name / services carry-forward in
    _build_device.
    """
    primary_ad = SAMPLE_AIRPODS
    scan_response_no_mfg = json.dumps({
        "ts": "2026-05-06T12:34:57.123Z",
        "id": "550E8400-E29B-41D4-A716-446655440000",
        "name": "AirPods Pro",
        "rssi_dbm": -54,
        "is_connectable": True,
        "service_uuids": ["180A", "FE9F"],
        # No manufacturer_id, no manufacturer_hex — the field set a
        # CoreBluetooth scan-response routinely produces.
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, primary_ad, vendors=VENDORS)
    update_from_line(devices, scan_response_no_mfg, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.vendor_id == 76
    assert d.vendor == "Apple, Inc."


# ------------------------------------------------------------------
# 2. Vendor lookup
# ------------------------------------------------------------------

def test_lookup_vendor_known_company_id():
    """Apple's well-known SIG company ID resolves to the right vendor."""
    assert lookup_vendor(76, VENDORS) == "Apple, Inc."


def test_lookup_vendor_unknown_returns_none():
    """An unassigned company ID resolves to None — the renderer can
    then show the raw ID and let the user investigate."""
    assert lookup_vendor(99999, VENDORS) is None


def test_lookup_vendor_none_input_returns_none():
    """The 'no manufacturer data' case is the most common BLE state.
    Defensive: lookup must accept None silently."""
    assert lookup_vendor(None, VENDORS) is None


def test_load_vendors_ships_apple_id():
    """The bundled snapshot must contain Apple (company ID 76). If
    ``make update-vendors`` is ever broken or the file is missing,
    this fails loudly."""
    vendors = load_vendors()
    assert vendors.get(76) == "Apple, Inc."


# ------------------------------------------------------------------
# 3. Service category inference
# ------------------------------------------------------------------

def test_service_category_heart_rate():
    """Bluetooth SIG 16-bit UUID 180D is the Heart Rate service."""
    assert service_category("180D") == "Heart Rate"


def test_service_category_hid():
    """1812 is the Human Interface Device profile (keyboard / mouse)."""
    assert service_category("1812") == "HID"


def test_service_category_unknown_passthrough():
    """An unknown service UUID is returned unchanged — the user can
    look it up themselves rather than seeing a misleading label."""
    raw = "ABCD"
    assert service_category(raw) == raw


def test_service_category_long_form_normalised():
    """macOS sometimes reports 16-bit UUIDs in their full 128-bit form
    (Bluetooth SIG base UUID with the 16-bit code embedded). The
    lookup must match either form."""
    long_form = "0000180D-0000-1000-8000-00805F9B34FB"
    assert service_category(long_form) == "Heart Rate"


# ------------------------------------------------------------------
# 4. Decay / TTL
# ------------------------------------------------------------------

def test_expire_drops_unseen_devices():
    """A device whose last_seen is older than ttl_s is dropped from
    the snapshot. Keeps the TUI from hoarding stale rows after a
    device walks out of range."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t0)
    pruned = expire_devices(
        devices, now=t0 + timedelta(seconds=60), ttl_s=30.0,
    )
    assert pruned == {}


def test_expire_keeps_recent_devices():
    """A device seen within ttl_s is retained."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t0)
    pruned = expire_devices(
        devices, now=t0 + timedelta(seconds=10), ttl_s=30.0,
    )
    assert len(pruned) == 1


# ------------------------------------------------------------------
# 5. Fuzzy merge
# ------------------------------------------------------------------

def test_merge_folds_same_vendor_and_name_within_rssi_window():
    """Two records sharing (vendor_id, name) and within ±10 dB merge
    into one row. ad_count is summed; merged_count records how many
    folded so the renderer can show a (merged N) badge."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = _device("aaa", name="AirPods Pro", vendor_id=76, rssi=-52,
                ad_count=3, now=now)
    b = _device("bbb", name="AirPods Pro", vendor_id=76, rssi=-58,
                ad_count=2, now=now)
    merged = merge_for_display([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert m.merged_count == 2
    assert m.ad_count == 5
    assert m.name == "AirPods Pro"
    assert m.vendor_id == 76


def test_merge_keeps_distant_rssi_separate():
    """Two records sharing identity but with RSSIs > 10 dB apart stay
    separate — they are likely different physical devices in different
    rooms broadcasting under the same generic name."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = _device("aaa", name="generic", vendor_id=42, rssi=-40, now=now)
    b = _device("bbb", name="generic", vendor_id=42, rssi=-80, now=now)
    merged = merge_for_display([a, b])
    assert len(merged) == 2
    assert all(d.merged_count == 1 for d in merged)


def test_merge_does_not_combine_anonymous_devices():
    """Devices with both vendor_id and name None are too anonymous to
    safely merge — the heuristic would conflate every nameless beacon
    nearby. Spec calls this out under 'never silently fall back'."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = _device("aaa", name=None, vendor_id=None, rssi=-50, now=now)
    b = _device("bbb", name=None, vendor_id=None, rssi=-52, now=now)
    merged = merge_for_display([a, b])
    assert len(merged) == 2


def test_merge_sorts_by_rssi_descending():
    """The post-merge list is ordered by signal strength so the closest
    device is at the top of the panel."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    weak = _device("weak", name="A", vendor_id=1, rssi=-80, now=now)
    strong = _device("strong", name="B", vendor_id=2, rssi=-40, now=now)
    merged = merge_for_display([weak, strong])
    assert merged[0].identifier == "strong"
    assert merged[1].identifier == "weak"


# ------------------------------------------------------------------
# 6. Permission denied
# ------------------------------------------------------------------

def test_permission_denied_line_surfaces_state():
    """An error line with 'unauthorized' marker flips state to
    'permission_denied' without crashing."""
    devices: dict[str, BLEDevice] = {}
    line = json.dumps({"error": "bluetooth unauthorized"})
    state = update_from_line(devices, line, vendors=VENDORS)
    assert state == "permission_denied"
    assert devices == {}


def test_permission_denied_via_subprocess_exit_code():
    """Helper exiting with code 3 (CBManager .unauthorized) flips the
    poller's permission_state to 'denied' even when no error JSON
    line was emitted before the exit."""
    asyncio.run(_run_poller_with_stream(
        lines=[],
        return_code=3,
        assert_state="denied",
    ))


def test_incompatible_helper_via_subprocess_exit_code_64():
    """A 0.4.0-era helper bundle answers 'unknown subcommand ble-scan'
    and exits 64. The poller surfaces this as 'incompatible' so the
    panel can render a 'rebuild' hint instead of stranding the user
    on a silent 'scanning…' placeholder forever."""
    asyncio.run(_run_poller_with_stream(
        lines=[],
        return_code=64,
        assert_state="incompatible",
    ))


def test_bluetooth_off_via_subprocess_exit_code_4():
    """Bluetooth toggled off in Control Center makes the helper exit
    4 ('bluetooth powered off'). The poller surfaces 'error' so the
    panel can hint at the actual cause."""
    asyncio.run(_run_poller_with_stream(
        lines=[],
        return_code=4,
        assert_state="error",
    ))


def test_unsupported_hardware_via_subprocess_exit_code_5():
    """Hardware without BLE — exit 5 maps to 'error' for the same
    reason: better an explicit message than a silent 'scanning'."""
    asyncio.run(_run_poller_with_stream(
        lines=[],
        return_code=5,
        assert_state="error",
    ))


# ------------------------------------------------------------------
# 7. Subprocess crash
# ------------------------------------------------------------------

def test_subprocess_crash_does_not_raise():
    """Helper killed mid-stream (SIGKILL → 137) leaves the poller
    quiet: future snapshots are empty, no exception bubbles up to
    the consumer."""
    asyncio.run(_run_poller_with_stream(
        lines=[SAMPLE_AIRPODS],
        return_code=137,
        # We don't assert state because the spec only requires
        # "no exception bubbles up". Having parsed one ad before the
        # crash leaves state as 'granted', which is also fine.
        min_snapshots=2,
    ))


def test_helper_binary_missing_marks_unavailable():
    """If asyncio.create_subprocess_exec raises OSError (binary not
    found), the poller flips state to 'unavailable' and keeps yielding
    empty snapshots."""

    async def go() -> None:
        async def boom() -> Any:
            raise FileNotFoundError("no helper")
        poller = BLEPoller("/nonexistent", _spawn=boom,
                           snapshot_interval_s=0.05)
        snapshots: list[BLEScanUpdate] = []
        gen = poller.events()
        try:
            async for snap in gen:
                snapshots.append(snap)
                if len(snapshots) >= 2:
                    break
        finally:
            await gen.aclose()
        assert any(s.permission_state == "unavailable" for s in snapshots)

    asyncio.run(go())


# ------------------------------------------------------------------
# 8. Malformed JSON line
# ------------------------------------------------------------------

def test_malformed_line_skipped_subsequent_parsed():
    """One garbage line in the stream is skipped; subsequent valid
    lines parse into devices normally."""
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, "this is not json", vendors=VENDORS)
    assert devices == {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS)
    assert len(devices) == 1


def test_line_without_id_field_skipped():
    """Defensive: a JSON object without 'id' is skipped, not raised."""
    devices: dict[str, BLEDevice] = {}
    line = json.dumps({"rssi_dbm": -60, "name": "no-id-here"})
    update_from_line(devices, line, vendors=VENDORS)
    assert devices == {}


# ------------------------------------------------------------------
# 9. Schema-3 deep identification (v0.6.0+)
# ------------------------------------------------------------------

def test_detect_ibeacon_from_apple_manufacturer_payload():
    """Apple manufacturer-data starting with 4c00 (company ID) and the
    iBeacon signature byte 0x02 → type 'iBeacon'. The remaining bytes
    are the proximity UUID, major, minor, and tx power; we only need
    to recognise the signature."""
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": (
            "4c0002151234567890abcdef1234567890abcdef0001000200c5"
        ),
    }
    type_, dc = detect_advertisement(obj)
    assert type_ == "iBeacon"
    assert dc is None


def test_detect_airtag_apple_type_0x12_with_find_my_service():
    """Apple type 0x12 with an owner-paired length payload (>= 25 bytes
    of mfg data) is an AirTag. Find My target without that length
    degrades to the more general 'Find My target' label."""
    # 25 bytes (50 hex chars) — owner-paired AirTag payload size.
    payload = "4c0012191000" + "00" * 22
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": payload,
        "service_uuids": ["FD5A"],
    }
    type_, dc = detect_advertisement(obj)
    assert type_ == "AirTag"
    assert dc is None


def test_detect_find_my_target_short_payload():
    """A short Find My broadcast (lost-mode beacon) without the AirTag
    length signature is still recognisable, just less specific."""
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": "4c001202aabb",  # short 0x12 payload
    }
    type_, _ = detect_advertisement(obj)
    assert type_ == "Find My target"


def test_detect_eddystone_url_from_helper_supplied_type():
    """Eddystone-URL detection requires the service-data frame byte,
    which CoreBluetooth surfaces in CBAdvertisementDataServiceDataKey
    on the helper side — the JSON line carries the helper's resolved
    'type' string. Verify the schema-3 propagation: a JSON object
    with type='Eddystone-URL' parses cleanly and ends up on the
    BLEDevice."""
    line = json.dumps({
        "id": "AA000000-0000-0000-0000-000000000001",
        "rssi_dbm": -60,
        "service_uuids": ["FEAA"],
        "type": "Eddystone-URL",
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, line, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.type == "Eddystone-URL"


def test_detect_eddystone_generic_from_service_uuid_only():
    """Without a frame byte (service_data not in the line) the Python
    fallback collapses every Eddystone variant to the generic label.
    This is the back-compat path; helpers post-0.6.0 specialise."""
    obj = {"service_uuids": ["FEAA"]}
    type_, _ = detect_advertisement(obj)
    assert type_ == "Eddystone"


def test_detect_tile_from_feed_service_uuid():
    """Tile beacons advertise FEED (and some FEEC for legacy hardware).
    Either signals 'Tile'."""
    obj = {"service_uuids": ["FEED"]}
    type_, _ = detect_advertisement(obj)
    assert type_ == "Tile"

    obj2 = {"service_uuids": ["FEEC"]}
    type2, _ = detect_advertisement(obj2)
    assert type2 == "Tile"


def test_detect_smarttag_samsung_company_id_disambiguates_fd5a():
    """FD5A is shared by Apple Find My and Samsung SmartTag. The Samsung
    company ID (0x0075 = 117) flips the label so a SmartTag is not
    miscategorised as a Find My target."""
    obj = {
        "manufacturer_id": 117,
        "manufacturer_hex": "75000000",
        "service_uuids": ["FD5A"],
    }
    type_, _ = detect_advertisement(obj)
    assert type_ == "SmartTag"


def test_detect_swift_pair_microsoft_company_id_plus_leading_byte():
    """Microsoft Swift Pair beacons start with company ID 0x0006 and a
    leading 0x03 byte. Anything else from Microsoft is left unlabelled."""
    obj = {
        "manufacturer_id": 6,
        "manufacturer_hex": "06000380aabbccdd",
    }
    type_, _ = detect_advertisement(obj)
    assert type_ == "Swift Pair"


@pytest.mark.parametrize("action_byte_hex,expected_class", [
    ("10", "iPhone"),
    ("20", "iPad"),
    ("40", "Mac"),
    ("60", "Apple TV"),
    ("70", "HomePod"),
    ("90", "Apple Watch"),
])
def test_apple_nearby_info_device_class(action_byte_hex, expected_class):
    """Apple type 0x10 (Nearby Info) carries an unencrypted device-class
    nibble in the high half of byte 5 (after company ID, type, length,
    status flags). Each nibble maps to one of six recognised devices.
    Reverse-engineered from furiousMAC/continuity; the rest of the
    payload is encrypted and ignored."""
    # Layout: 4c00 (Apple) 10 (Nearby Info) 05 (length) 00 (status flags)
    # [actionByte] then 3 encrypted bytes.
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": f"4c001005 00 {action_byte_hex} 000000".replace(" ", ""),
    }
    type_, dc = detect_advertisement(obj)
    assert type_ is None
    assert dc == expected_class


def test_connected_line_routes_to_connected_dict_only():
    """A '{\"connected\": true, ...}' line goes to the connected dict
    and never to the advertising one. The two stores have distinct
    lifecycles; cross-talk would corrupt the panel's two-section
    layout."""
    devices: dict[str, BLEDevice] = {}
    connected: dict[str, BLEDevice] = {}
    line = json.dumps({
        "connected": True,
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Magic Keyboard",
        "service_uuids": ["1812", "180F"],
    })
    update_from_line(devices, line, vendors=VENDORS, connected=connected)
    assert devices == {}
    assert len(connected) == 1
    d = next(iter(connected.values()))
    assert d.is_connected is True
    assert d.name == "Magic Keyboard"
    assert d.rssi_dbm is None
    assert d.services == ("1812", "180F")


def test_connected_entries_skip_advertising_ttl():
    """expire_devices applies to the advertising dict only — connected
    entries are pruned by the helper's connected_snapshot sentinel,
    not by time-since-last-seen. Calling expire_devices on the
    advertising dict must not even see the connected dict."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    devices: dict[str, BLEDevice] = {}
    connected: dict[str, BLEDevice] = {}
    update_from_line(
        devices,
        json.dumps({
            "connected": True,
            "id": "aa000000-0000-0000-0000-000000000001",
            "name": "AirPods Pro",
        }),
        vendors=VENDORS, now=t0, connected=connected,
    )
    # An hour passes — well beyond ttl_s. The advertising-side expiry
    # leaves connected untouched.
    pruned = expire_devices(devices, now=t0 + timedelta(hours=1), ttl_s=30.0)
    assert pruned == {}
    assert len(connected) == 1


def test_connected_snapshot_sentinel_prunes_disappeared_entries():
    """The 'connected_snapshot' line carries the full set of currently-
    connected IDs. Entries not in that set were disconnected since the
    last snapshot and must be pruned. Otherwise a Magic Keyboard the
    user just turned off would linger forever."""
    connected: dict[str, BLEDevice] = {}
    devices: dict[str, BLEDevice] = {}
    keep_id = "11111111-2222-3333-4444-555555555555"
    drop_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    for ident, name in [(keep_id, "Magic Keyboard"), (drop_id, "Old AirPods")]:
        update_from_line(
            devices,
            json.dumps({"connected": True, "id": ident, "name": name}),
            vendors=VENDORS, connected=connected,
        )
    assert len(connected) == 2

    snapshot = json.dumps({
        "connected_snapshot": True,
        "count": 1,
        "ids": [keep_id],
    })
    update_from_line(devices, snapshot, vendors=VENDORS, connected=connected)
    assert set(connected.keys()) == {keep_id.lower()}


def test_schema_2_json_back_compat_type_and_device_class_default_none():
    """A schema-2 helper bundle (pre-0.6.0) emits advertisements without
    type / device_class fields. Those should parse cleanly with both
    fields defaulting to None — back-compat keeps a freshly-upgraded
    Python TUI happy when the user has not yet rebuilt the helper."""
    devices: dict[str, BLEDevice] = {}
    schema_2_line = json.dumps({
        "ts": "2026-05-06T12:34:56.789Z",
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "GenericThing",
        "rssi_dbm": -70,
        "is_connectable": True,
        # No service_uuids, no manufacturer data, no type, no device_class.
    })
    update_from_line(devices, schema_2_line, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.type is None
    assert d.device_class is None
    assert d.is_connected is False


def test_mixed_stream_routes_each_line_to_correct_bucket():
    """An interleaved stream of advertising and connected lines must
    route each one independently — advertising never leaks into the
    connected dict, and vice versa, regardless of arrival order."""
    devices: dict[str, BLEDevice] = {}
    connected: dict[str, BLEDevice] = {}
    lines = [
        SAMPLE_AIRPODS,  # advertising AirPods
        json.dumps({
            "connected": True,
            "id": "cc000000-0000-0000-0000-000000000001",
            "name": "Magic Keyboard",
            "service_uuids": ["1812"],
        }),
        json.dumps({
            "id": "ad000000-0000-0000-0000-000000000002",
            "name": "Some iBeacon",
            "rssi_dbm": -65,
            "manufacturer_id": 76,
            "manufacturer_hex": "4c0002150000000000000000000000000000000000010002c5",
        }),
        json.dumps({
            "connected": True,
            "id": "cc000000-0000-0000-0000-000000000002",
            "name": "AirPods Pro",
        }),
    ]
    for line in lines:
        update_from_line(devices, line, vendors=VENDORS, connected=connected)
    assert len(devices) == 2
    assert len(connected) == 2
    assert all(not d.is_connected for d in devices.values())
    assert all(d.is_connected for d in connected.values())
    # The iBeacon detection ran on the second advertising line too.
    ibeacon = next(d for d in devices.values() if d.name == "Some iBeacon")
    assert ibeacon.type == "iBeacon"


def test_ble_scan_update_propagates_connected_through_poller():
    """The poller's snapshot loop emits BLEScanUpdate objects whose
    `connected` list reflects the running connected dict — same channel
    as `devices`, just a different lifecycle. This is the field the
    BLEPanel reads to render its 'Connected' section."""

    async def go() -> None:
        connected_line = json.dumps({
            "connected": True,
            "id": "cc000000-0000-0000-0000-000000000001",
            "name": "Magic Keyboard",
            "service_uuids": ["1812"],
        })
        snapshot = json.dumps({
            "connected_snapshot": True,
            "count": 1,
            "ids": ["cc000000-0000-0000-0000-000000000001"],
        })
        encoded = [
            (connected_line + "\n").encode("utf-8"),
            (snapshot + "\n").encode("utf-8"),
        ]

        async def fake_spawn() -> Any:
            return _FakeProc(encoded, 0)

        poller = BLEPoller(
            "/fake/helper", _spawn=fake_spawn,
            snapshot_interval_s=0.02, ttl_s=30.0,
        )
        snapshots: list[BLEScanUpdate] = []
        gen = poller.events()
        try:
            async for snap in gen:
                snapshots.append(snap)
                if any(s.connected for s in snapshots):
                    break
                if len(snapshots) >= 30:
                    break
        finally:
            await gen.aclose()
        assert any(s.connected for s in snapshots), (
            "BLEScanUpdate.connected never populated"
        )
        last = next(s for s in snapshots if s.connected)
        assert last.connected[0].name == "Magic Keyboard"
        assert last.connected[0].is_connected is True
        # Advertising list stays empty — the connected line never
        # crossed over.
        assert last.devices == []

    asyncio.run(go())


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _device(
    identifier: str,
    *,
    name: str | None,
    vendor_id: int | None,
    rssi: int | None,
    ad_count: int = 1,
    now: datetime,
) -> BLEDevice:
    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor=lookup_vendor(vendor_id, VENDORS),
        vendor_id=vendor_id,
        services=(),
        rssi_dbm=rssi,
        is_connectable=False,
        first_seen=now,
        last_seen=now,
        ad_count=ad_count,
    )


class _FakeStdout:
    """Async-iterable stand-in for asyncio.StreamReader.

    Yields each pre-supplied byte line in turn, then completes. The
    poller's reader loop only relies on the async-iterator interface;
    we don't need to reach for the full StreamReader machinery.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __aiter__(self) -> "_FakeStdout":
        self._iter = iter(self._lines)
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeProc:
    """Mimics the subset of asyncio.subprocess.Process used by BLEPoller."""

    def __init__(self, stdout_lines: list[bytes], return_code: int) -> None:
        self.stdout = _FakeStdout(stdout_lines)
        self._return_code = return_code
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = self._return_code
        return self._return_code

    def terminate(self) -> None:
        # Cooperatively exit on terminate so stop() works correctly
        # even after the stream has drained.
        self.returncode = self._return_code


async def _run_poller_with_stream(
    *,
    lines: list[str],
    return_code: int,
    assert_state: str | None = None,
    min_snapshots: int = 2,
    max_snapshots: int = 30,
) -> None:
    encoded = [(line + "\n").encode("utf-8") for line in lines]

    async def fake_spawn() -> Any:
        return _FakeProc(encoded, return_code)

    poller = BLEPoller(
        "/fake/helper", _spawn=fake_spawn,
        snapshot_interval_s=0.02, ttl_s=30.0,
    )
    snapshots: list[BLEScanUpdate] = []
    gen = poller.events()
    try:
        async for snap in gen:
            snapshots.append(snap)
            done = len(snapshots) >= min_snapshots
            if assert_state is not None:
                done = done and any(
                    s.permission_state == assert_state for s in snapshots
                )
            if done or len(snapshots) >= max_snapshots:
                break
    finally:
        await gen.aclose()

    assert len(snapshots) >= min_snapshots
    if assert_state is not None:
        assert any(s.permission_state == assert_state for s in snapshots), (
            f"expected state {assert_state!r} in "
            f"{[s.permission_state for s in snapshots]!r}"
        )
