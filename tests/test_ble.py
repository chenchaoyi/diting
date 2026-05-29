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

from diting import ble
from diting.ble import (
    BLEDevice,
    BLEHistory,
    BLEPoller,
    BLEScanUpdate,
    detect_advertisement,
    expire_devices,
    load_gatt_services,
    load_member_uuids,
    load_ouis,
    load_vendors,
    lookup_member_vendor,
    lookup_name_vendor,
    lookup_oui_vendor,
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


def test_schema_4_raw_passthrough_fields_populate():
    """Schema-4 fields (service_data / tx_power_dbm / solicited /
    overflow service UUIDs) plumb through from the helper JSON line
    onto the BLEDevice dataclass. These are raw-passthrough so
    downstream sensor / beacon decoders can read CoreBluetooth's
    advertisementData dict without re-implementing the bridge.
    """
    line = json.dumps({
        "ts": "2026-05-09T10:00:00.000Z",
        "id": "AA000000-0000-0000-0000-000000000001",
        "rssi_dbm": -55,
        "is_connectable": True,
        "service_uuids": ["FEAA"],
        "service_data": {
            "FEAA": "10aa00abcdef",  # Eddystone-URL frame
            "FCD2": "deadbeef",       # vendor-private payload
        },
        "tx_power_dbm": -22,
        "solicited_service_uuids": ["1812"],
        "overflow_service_uuids": ["FE9F"],
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, line, vendors=VENDORS)
    d = next(iter(devices.values()))
    sd = dict(d.service_data)
    assert sd == {"FEAA": "10aa00abcdef", "FCD2": "deadbeef"}
    assert d.tx_power_dbm == -22
    assert d.solicited_service_uuids == ("1812",)
    assert d.overflow_service_uuids == ("FE9F",)


def test_schema_4_fields_default_when_helper_omits():
    """A schema-3 helper bundle omits the new fields; the BLEDevice
    still builds, with empty / None defaults. Required for backward
    compat — users running an older helper.app must not break.
    """
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.service_data == ()
    assert d.tx_power_dbm is None
    assert d.solicited_service_uuids == ()
    assert d.overflow_service_uuids == ()


def test_service_data_uuid_resolves_vendor_when_service_uuids_empty():
    """Real-world rows from Xiaomi MiBeacon / Google Fast Pair devices
    advertise their SIG-assigned member UUID only inside `service_data`
    keys, leaving `service_uuids` empty. Vendor lookup must consult
    service_data keys as a fallback so these rows don't dead-end at
    `(unknown)`. Verified against actual helper output: an SMI-M14
    Mi Band variant with FE95 service_data and no other identifying
    fields previously rendered as unknown.
    """
    line = json.dumps({
        "ts": "2026-05-09T11:00:00.000Z",
        "id": "B1ED3117-1909-E3AE-5AFE-0FD2984A9AB9",
        "rssi_dbm": -74,
        "is_connectable": True,
        "name": "SMI-M14",
        # No manufacturer_id, no service_uuids — only service_data carries
        # the SIG member UUID.
        "service_data": {"FE95": "b054452d00b25aca754dcc080e00"},
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, line, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.vendor == "Xiaomi Inc."


def test_schema_4_fields_carry_forward_on_scan_response():
    """Same flicker-protection as vendor_id / name / services: a
    scan-response packet that omits the schema-4 fields should not
    blank values established by the primary advertisement.
    """
    primary = json.dumps({
        "ts": "2026-05-09T10:00:00.000Z",
        "id": "AA000000-0000-0000-0000-000000000002",
        "rssi_dbm": -50,
        "is_connectable": True,
        "service_data": {"FEAA": "10aa00"},
        "tx_power_dbm": -22,
    })
    scan_response = json.dumps({
        "ts": "2026-05-09T10:00:01.000Z",
        "id": "AA000000-0000-0000-0000-000000000002",
        "rssi_dbm": -52,
        "is_connectable": True,
        # No service_data, no tx_power_dbm — typical scan response.
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, primary, vendors=VENDORS)
    update_from_line(devices, scan_response, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert dict(d.service_data) == {"FEAA": "10aa00"}
    assert d.tx_power_dbm == -22


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


# --- OUI lookup (connected peripherals) -----------------------------

OUIS = {
    "38:09:fb": "Apple, Inc.",
    "8c:85:90": "Apple, Inc.",
    "00:50:f2": "Microsoft",
}


def test_lookup_oui_vendor_dash_separated_mac():
    """Helper emits MACs as ``38-09-fb-0b-be-60`` (IOBluetooth's native
    addressString form). The lookup normalises through to the colon-
    separated ``aa:bb:cc`` key the bundled OUI JSON uses."""
    assert lookup_oui_vendor("38-09-fb-0b-be-60", OUIS) == "Apple, Inc."


def test_lookup_oui_vendor_colon_separated_mac():
    """Same MAC in colon-separated form must resolve identically — no
    helper-format coupling on the lookup side."""
    assert lookup_oui_vendor("8c:85:90:f1:d0:cd", OUIS) == "Apple, Inc."


def test_lookup_oui_vendor_unknown_oui_returns_none():
    """An OUI not in the bundled subset stays None — the panel renders
    "(unknown)" rather than fabricating a vendor."""
    assert lookup_oui_vendor("aa:bb:cc:dd:ee:ff", OUIS) is None


def test_lookup_oui_vendor_invalid_input_returns_none():
    """Defensive: empty / non-hex / too-short inputs must not raise."""
    assert lookup_oui_vendor(None, OUIS) is None
    assert lookup_oui_vendor("", OUIS) is None
    assert lookup_oui_vendor("not-a-mac", OUIS) is None
    assert lookup_oui_vendor("01:02", OUIS) is None  # too short for an OUI


def test_load_ouis_ships_apple_magic_keyboard_oui():
    """Pin a known-Apple-OUI present in the bundled JSON to catch
    accidental file truncation. 38:09:fb is one of Apple's many MA-L
    allocations; their Magic Keyboard ships with it."""
    ouis = load_ouis()
    assert ouis.get("38:09:fb") == "Apple, Inc."


def test_rssi_unavailable_sentinel_filtered():
    """CoreBluetooth uses RSSI = 127 as the 'no reading available'
    sentinel. The helper should filter at the source, but the Python
    side keeps a defensive guard so older helper bundles cannot leak
    the sentinel through and corrupt RSSI-sorted lists or the
    diagnostic-panel Closest line. Any non-negative value is
    implausible for received-signal-strength dBm and is dropped."""
    devices: dict[str, BLEDevice] = {}
    sentinel_line = json.dumps({
        "ts": "2026-05-07T08:00:00Z",
        "id": "8000-0000-0000-0000-AAAAAAAAAAAA",
        "rssi_dbm": 127,                           # the sentinel
        "manufacturer_id": 76,
        "is_connectable": True,
    })
    update_from_line(devices, sentinel_line, vendors=VENDORS)
    assert len(devices) == 1
    d = next(iter(devices.values()))
    assert d.rssi_dbm is None


def test_rssi_zero_or_positive_dbm_treated_as_invalid():
    """Edge cases: 0 dBm is theoretically possible but physically
    implausible for BLE receive (means antenna touching transmitter).
    Treat all non-negative values as the sentinel space rather than
    inventing a tighter cutoff that might mask real edge cases."""
    devices: dict[str, BLEDevice] = {}
    line = json.dumps({
        "ts": "2026-05-07T08:00:00Z",
        "id": "AAAA-1111-2222-3333-CCCCCCCCCCCC",
        "rssi_dbm": 0,
        "manufacturer_id": 76,
        "is_connectable": True,
    })
    update_from_line(devices, line, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.rssi_dbm is None


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


def test_rssi_smooth_seeds_from_first_sample():
    """The very first observed RSSI must seed rssi_smooth so the
    device's first appearance lands in its real signal bucket
    instead of being held back by a non-existent prior value."""
    line = json.dumps({
        "id": "AA000000-0000-0000-0000-000000000001",
        "rssi_dbm": -55,
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, line, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.rssi_smooth == -55


def test_rssi_smooth_dampens_packet_jitter():
    """A 5–15 dB single-packet swing (typical BLE radio behaviour) is
    smoothed so the sort order does not flip on every snapshot. With
    α=0.4 a 10 dB transient nudges the EMA by 4 dB, not 10. Two
    successive readings should converge towards the average."""
    line1 = json.dumps({
        "id": "BB000000-0000-0000-0000-000000000002",
        "rssi_dbm": -55,
    })
    line2 = json.dumps({
        "id": "BB000000-0000-0000-0000-000000000002",
        "rssi_dbm": -65,
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, line1, vendors=VENDORS)
    update_from_line(devices, line2, vendors=VENDORS)
    d = next(iter(devices.values()))
    # Display still uses the latest packet (-65) so the user sees
    # live signal; sort uses the EMA which lands at 0.4*(-65) +
    # 0.6*(-55) = -59.
    assert d.rssi_dbm == -65
    assert d.rssi_smooth == -59


def test_merge_sort_key_uses_smoothed_rssi():
    """When two devices have similar EMA-smoothed RSSI but big single-
    packet jitter, the row order follows the smoothed values, not the
    snapshot RSSI. Guards against the row-swap-every-second flapping
    the user reported with bare-RSSI sorting."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    # Device A: live RSSI dropped to -65 this packet but its EMA is
    # holding at -52. Device B: live RSSI is -50 (stronger) but its
    # EMA is at -58 because it just walked into range. Sort by EMA
    # → A above B; sort by raw RSSI → B above A.
    a = BLEDevice(
        identifier="aaa", name="X", vendor=None, vendor_id=1,
        services=(), rssi_dbm=-65, rssi_smooth=-52,
        is_connectable=False, first_seen=now, last_seen=now, ad_count=4,
    )
    b = BLEDevice(
        identifier="bbb", name="Y", vendor=None, vendor_id=2,
        services=(), rssi_dbm=-50, rssi_smooth=-58,
        is_connectable=False, first_seen=now, last_seen=now, ad_count=4,
    )
    merged = merge_for_display([a, b])
    assert [d.identifier for d in merged] == ["aaa", "bbb"]


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


@pytest.mark.parametrize("type_hex,expected_label", [
    ("05", "AirDrop"),
    ("07", "AirPods"),
    ("09", "AirPlay target"),
    ("0a", "AirPlay source"),
    ("0b", "Watch pairing"),
    ("0c", "Handoff"),
    ("0d", "Tethering target"),
    ("0e", "Tethering source"),
    ("0f", "Nearby Action"),
])
def test_apple_continuity_extended_type_bytes(type_hex, expected_label):
    """Apple Continuity type bytes beyond iBeacon / Nearby Info / Find
    My each carry a stable broadcast-intent label. Resolves the bulk of
    the "Apple, Inc. (unknown)" rows the BLE panel used to show — Apple
    devices broadcasting Continuity packets never populate the local-
    name field, so without these rules the row had nothing to say."""
    # Layout: 4c00 (Apple) <type> <length=04> <four payload bytes>.
    # The payload after type is opaque; we just need >= 3 bytes total
    # for the parser to read the type byte.
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": f"4c00{type_hex}04aabbccdd",
    }
    type_, dc = detect_advertisement(obj)
    assert type_ == expected_label
    assert dc is None


def test_apple_type_0x12_with_localname_is_find_my_not_airtag():
    """AirPods Pro / Apple Watch / etc. broadcast Find My beacons
    with the same length signature as an owner-paired AirTag, so the
    length-only heuristic mislabelled them as 'AirTag' (the user
    saw 'AirTag' next to 'Chaoyi's AirPods Pro' on real hardware).
    A real AirTag never broadcasts a localName by design — so the
    presence of a name is the deciding signal. Devices with a name
    drop to 'Find My target' instead of guessing AirTag."""
    obj_with_name = {
        "name": "Chaoyi's AirPods Pro",
        "manufacturer_id": 76,
        # 25 bytes of payload — same length signature as AirTag.
        "manufacturer_hex": "4c0012191000" + "00" * 22,
    }
    type_, _ = detect_advertisement(obj_with_name)
    assert type_ == "Find My target"

    # Anonymous owner-paired payload (real AirTag) still gets the
    # AirTag label so the existing tag-finder UX continues to work.
    obj_anonymous = {
        "manufacturer_id": 76,
        "manufacturer_hex": "4c0012191000" + "00" * 22,
    }
    type_, _ = detect_advertisement(obj_anonymous)
    assert type_ == "AirTag"


def test_apple_continuity_type_0x16_apple_proximity():
    """Apple type 0x16 is the dominant Continuity type seen in
    real-Mac scans (~30% of unlabelled Apple rows). Generic
    "Apple Proximity" label so the row is no longer just "Apple
    Inc. (unknown)"."""
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": "4c001608abcdef0123456789",
    }
    type_, _ = detect_advertisement(obj)
    assert type_ == "Apple Proximity"


def test_microsoft_cdp_type_0x01_device_beacon():
    """Microsoft CDP type 0x01 is the general device-discovery
    beacon used by Phone Link / Nearby Sharing — common in any
    office with Windows laptops nearby. Previously left
    unlabelled (only 0x03 Swift Pair was decoded)."""
    obj = {
        "manufacturer_id": 6,
        "manufacturer_hex": "060001ab1234cd5678ef",
    }
    type_, _ = detect_advertisement(obj)
    assert type_ == "MS device beacon"


def test_apple_continuity_unknown_type_byte_passes_through():
    """Type bytes outside the documented set return (None, None) so
    the row falls back to vendor + service-category like before. This
    is the non-regression guard against expanding the table to too
    many guesses."""
    obj = {
        "manufacturer_id": 76,
        "manufacturer_hex": "4c00ff04aabbccdd",  # type 0xFF is unassigned
    }
    type_, dc = detect_advertisement(obj)
    assert type_ is None
    assert dc is None


# ------------------------------------------------------------------
# 8. SIG GATT + member-UUID resolution
# ------------------------------------------------------------------

def test_load_gatt_services_ships_battery_and_device_info():
    """Sanity check that the bundled GATT services file made it into
    the wheel and contains the well-known 16-bit assignments the BLE
    panel calls out by name."""
    gatt = load_gatt_services()
    assert gatt.get("180A") == "Device Information"
    assert gatt.get("180F") == "Battery"


def test_load_member_uuids_ships_xiaomi_and_sony():
    """Sanity check for the bundled SIG member-UUIDs map. Used both
    for the service column and as the vendor fallback when the
    advertisement omits manufacturer_data."""
    members = load_member_uuids()
    assert members.get("FDAA") == "Xiaomi Inc."
    assert "Sony" in (members.get("FD2A") or "")


def test_service_category_falls_through_to_gatt_services():
    """Battery (0x180F) is not in the hand-curated friendly-names map
    but IS in the bundled SIG GATT-services file. Resolution must
    fall through cleanly so the service column reads "Battery"
    instead of "180F"."""
    assert service_category("180F") == "Battery"
    assert service_category("180A") == "Device Information"


def test_service_category_category_only_excludes_protocol_services():
    """The aggregate Categories diagnostic uses ``category_only=True``;
    it must not count protocol-utility GATT services as device kinds —
    those are advertised by virtually every BLE peripheral with
    bonding and drown out actually-meaningful categories. Per-row
    service rendering (default ``category_only=False``) must still
    resolve them to their friendly GATT labels. Heart Rate (0x180D)
    is a real device-class service and stays counted under both flags."""
    # Aggregate Categories: the three protocol-utility services drop out
    assert service_category("180A", category_only=True) is None  # Device Information
    assert service_category("1800", category_only=True) is None  # GAP
    assert service_category("1801", category_only=True) is None  # GATT
    # Per-row Services column: default behaviour unchanged — these
    # labels come from the bundled SIG GATT-services table.
    assert service_category("180A") == "Device Information"
    assert service_category("1800") == "GAP"
    assert service_category("1801") == "GATT"
    # Sanity: a real device-class GATT service (Heart Rate) is unaffected
    assert service_category("180D", category_only=True) == "Heart Rate"
    assert service_category("180D") == "Heart Rate"


def test_service_category_falls_through_to_member_uuids():
    """16-bit member-assigned UUIDs (FDAA → Xiaomi, FD2A → Sony) are
    the last fallback before passing through the raw UUID. Resolves
    the user-facing case where the service column showed "FDAA"."""
    assert service_category("FDAA") == "Xiaomi Inc."
    assert "Sony" in service_category("FD2A")


def test_service_category_unknown_uuid_still_passes_through():
    """A UUID that is in none of the three layers must surface raw —
    the user can still copy-paste it into a search engine."""
    raw = "1234"
    assert service_category(raw) == raw


def test_service_category_strict_skips_member_uuid_layer():
    """``category_only=True`` is the mode the BLE Categories
    diagnostic row uses: it must NOT return vendor names from the
    member-UUID layer (FDAA → "Xiaomi Inc.") because those would
    pollute a row meant to read as device-class buckets only.
    Returns None instead of the vendor name; categories of layers
    1+2 (HID, Heart Rate, Battery, …) still resolve normally."""
    # Vendor name from member layer → None in strict mode.
    assert service_category("FDAA", category_only=True) is None
    assert service_category("FD2A", category_only=True) is None
    # Hand-curated and SIG-GATT layers still resolve.
    assert service_category("180D", category_only=True) == "Heart Rate"
    assert service_category("1812", category_only=True) == "HID"
    assert service_category("180F", category_only=True) == "Battery"
    # Unknown UUID → None (don't leak the raw hex into the categories
    # breakdown).
    assert service_category("1234", category_only=True) is None
    # Default mode unchanged.
    assert service_category("FDAA") == "Xiaomi Inc."


def test_lookup_name_vendor_jabra_pattern():
    """Jabra advertises cid 14666 which SIG hasn't published —
    manufacturer_id lookup misses. The localName carries
    "LE-Jabra Elite 8 Active" which the name-pattern fallback
    must resolve to "Jabra (GN Audio)"."""
    assert lookup_name_vendor("LE-Jabra Elite 8 Active") == "Jabra (GN Audio)"
    assert lookup_name_vendor("Jabra Evolve 75") == "Jabra (GN Audio)"


def test_lookup_name_vendor_xiaomi_band():
    """Mi Smart Band 6 broadcasts only a localName + a private
    128-bit service UUID; no manufacturer-data, no SIG member
    UUID. Name-pattern catches the "Mi " prefix."""
    assert lookup_name_vendor("Mi Smart Band 6") == "Xiaomi"
    assert lookup_name_vendor("Mi Band 7") == "Xiaomi"


def test_lookup_name_vendor_sony_audio():
    """Sony WH-1000XM5 / WF-1000XM5 advertise their model name.
    The pattern matches both prefixes."""
    assert lookup_name_vendor("WH-1000XM5") == "Sony"
    assert lookup_name_vendor("WF-1000XM4") == "Sony"
    assert lookup_name_vendor("LE_WH-1000XM5") == "Sony"


def test_lookup_name_vendor_apple_localnames():
    """Apple devices that surface a useful localName (some
    iPhones / iPads / MacBooks) resolve to Apple even when the
    manufacturer-data field is absent on the scan-response packet
    (CoreBluetooth is inconsistent about which advertisement
    carries which fields)."""
    assert lookup_name_vendor("iPhone 15 Pro") == "Apple, Inc."
    assert lookup_name_vendor("iPad Air") == "Apple, Inc."
    assert lookup_name_vendor("MacBook Pro") == "Apple, Inc."


def test_lookup_name_vendor_no_pattern():
    """Random / generic names return None — the fallback must
    not over-claim. A custom-renamed peripheral ("My Headset")
    or an empty name should produce no result."""
    assert lookup_name_vendor(None) is None
    assert lookup_name_vendor("") is None
    assert lookup_name_vendor("My Headset") is None
    assert lookup_name_vendor("Random-Name-1234") is None


def test_lookup_name_vendor_anchored_at_start():
    """Patterns are anchored at start of name to prevent over-
    claiming. "Apple-Pie-Recipe" must NOT resolve to Apple just
    because it contains the word."""
    # "iPhone" is the anchored prefix, not the substring
    assert lookup_name_vendor("My iPhone is great") is None
    # But case-insensitive at the start works:
    assert lookup_name_vendor("iphone 15") == "Apple, Inc."


def test_advertising_vendor_falls_back_to_name_pattern(tmp_path):
    """End-to-end: an advertisement with no manufacturer_id, no
    services, just a name like "LE-Jabra Elite 8 Active" should
    surface vendor='Jabra (GN Audio)' via the name-pattern
    fallback. Real-Mac case from the dogfood capture."""
    line = json.dumps({
        "id": "AA000000-0000-0000-0000-000000000000",
        "name": "LE-Jabra Elite 8 Active",
        "rssi_dbm": -52,
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, line, vendors=VENDORS)
    d = next(iter(devices.values()))
    assert d.vendor == "Jabra (GN Audio)"


def test_lookup_member_vendor_returns_none_for_no_match():
    """When the advertisement carries only random / private UUIDs,
    the member-UUID fallback must abstain rather than guess."""
    members = {"FDAA": "Xiaomi Inc."}
    assert lookup_member_vendor(("0000", "1234"), members) is None


def test_lookup_member_vendor_picks_first_matching_uuid():
    """Multiple UUIDs in the advertisement: take the first that
    resolves to a member-UUID company name. Order in the
    advertisement is preserved by the helper; first-wins keeps the
    label stable across consecutive packets."""
    members = {"FDAA": "Xiaomi Inc.", "FD2A": "Sony Corporation"}
    assert lookup_member_vendor(("FDAA", "FD2A"), members) == "Xiaomi Inc."
    assert lookup_member_vendor(("FD2A", "FDAA"), members) == "Sony Corporation"


def test_vendor_fallback_via_member_uuid_when_manufacturer_id_absent():
    """The screenshot case: a Sony / Xiaomi / SIANA accessory broadcasts
    a SIG-assigned member-UUID service but no manufacturer_data. The
    vendor column should still surface the company name instead of
    sitting at "(unknown)"."""
    line = json.dumps({
        "id": "AA000000-0000-0000-0000-000000000099",
        "rssi_dbm": -62,
        "service_uuids": ["FDAA"],
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(
        devices, line,
        vendors={},  # no manufacturer ID resolution available
        member_uuids={"FDAA": "Xiaomi Inc."},
    )
    d = next(iter(devices.values()))
    assert d.vendor == "Xiaomi Inc."
    assert d.vendor_id is None  # genuinely no company ID was carried


def test_manufacturer_id_takes_priority_over_member_uuid_vendor():
    """If both a manufacturer_id AND a member-UUID service are present,
    manufacturer_id wins. The two can disagree in the wild (a Sony
    accessory built on a Nordic SoC) and the manufacturer_id is the
    authoritative signal."""
    line = json.dumps({
        "id": "AA000000-0000-0000-0000-0000000000aa",
        "rssi_dbm": -55,
        "service_uuids": ["FDAA"],  # would resolve to Xiaomi alone
        "manufacturer_id": 89,       # 89 is Nordic Semiconductor
        "manufacturer_hex": "5900",
    })
    devices: dict[str, BLEDevice] = {}
    update_from_line(
        devices, line,
        vendors={89: "Nordic Semiconductor ASA"},
        member_uuids={"FDAA": "Xiaomi Inc."},
    )
    d = next(iter(devices.values()))
    assert d.vendor == "Nordic Semiconductor ASA"


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


# ------------------------------------------------------------------
# BLEHistory ring buffer
# ------------------------------------------------------------------


def test_history_records_and_returns_samples_in_order():
    h = BLEHistory()
    t0 = datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc)
    h.record("dev-1", t0, -50)
    h.record("dev-1", t0 + timedelta(seconds=2), -52)
    h.record("dev-1", t0 + timedelta(seconds=4), -55)
    out = h.get("dev-1")
    assert [r for _, r in out] == [-50, -52, -55]


def test_history_drops_none_rssi():
    """Connected peripherals have rssi=None — the buffer must not
    accept those, otherwise the sparkline would render garbage."""
    h = BLEHistory()
    t0 = datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc)
    h.record("dev-1", t0, None)
    h.record("dev-1", t0 + timedelta(seconds=1), -55)
    out = h.get("dev-1")
    assert [r for _, r in out] == [-55]


def test_history_caps_at_maxlen():
    """Long-running session must not leak: oldest samples roll off
    once we hit ``maxlen``."""
    h = BLEHistory(maxlen=4)
    t0 = datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc)
    for i in range(10):
        h.record("dev-1", t0 + timedelta(seconds=i), -60 - i)
    out = h.get("dev-1")
    assert len(out) == 4
    # The four samples retained should be the four newest.
    assert [r for _, r in out] == [-66, -67, -68, -69]


def test_history_get_unknown_device_returns_empty():
    h = BLEHistory()
    assert h.get("never-seen") == []


def test_history_expire_drops_devices_not_in_set():
    """Once a device leaves the snapshot we should not keep its
    history forever — busy environments rotate through hundreds of
    distinct random-MAC iPhones in an hour."""
    h = BLEHistory()
    t0 = datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc)
    h.record("dev-A", t0, -50)
    h.record("dev-B", t0, -60)
    h.record("dev-C", t0, -70)
    # Snapshot only sees A and C now; B has gone.
    h.expire({"dev-A", "dev-C"})
    assert h.get("dev-A") != []
    assert h.get("dev-B") == []
    assert h.get("dev-C") != []


# ------------------------------------------------------------------
# Transition events: BLEDeviceSeenEvent / BLEDeviceLeftEvent
#
# These tests exercise `_detect_transitions` directly — the sync
# helper extracted from `_snapshot_loop` — by populating
# `_devices` / `_connected` manually. That avoids the full async
# events() pipeline (reader_loop + snapshot_loop + queue plumbing)
# and keeps the tests fast and deterministic.
# ------------------------------------------------------------------


def _build_ble_device(
    identifier: str,
    *,
    name: str | None = "Magic Keyboard",
    vendor: str | None = "Apple, Inc.",
    rssi_dbm: int | None = -55,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    services: tuple[str, ...] = (),
) -> BLEDevice:
    t = first_seen or datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    t_last = last_seen or t
    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor=vendor,
        vendor_id=76,
        services=services,
        rssi_dbm=rssi_dbm,
        is_connectable=True,
        first_seen=t,
        last_seen=t_last,
        ad_count=1,
    )


def test_poller_emits_seen_event_on_first_observation():
    """First-time observation of an identifier in `_devices` →
    exactly one `BLEDeviceSeenEvent` on `_pending_transitions`."""
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake")
    poller._devices["MAC_A"] = _build_ble_device("MAC_A")
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    poller._detect_transitions(now)

    seen = [t for t in poller.drain_transitions() if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seen) == 1
    assert seen[0].identifier == "MAC_A"
    assert seen[0].vendor == "Apple, Inc."


def test_poller_seen_carries_device_type_and_class_from_representative():
    from dataclasses import replace
    from diting.events import BLEDeviceSeenEvent

    # presence_gate_s=0 so the anonymous (name=None) advert graduates
    # immediately instead of holding in PENDING.
    poller = BLEPoller("/fake", presence_gate_s=0.0)
    poller._devices["MAC_A"] = replace(
        _build_ble_device("MAC_A", name=None),
        type="Find My target", device_class="iPhone",
    )
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    poller._detect_transitions(now)
    seen = [t for t in poller.drain_transitions()
            if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seen) == 1
    assert seen[0].device_type == "Find My target"
    assert seen[0].device_class == "iPhone"


def test_poller_left_carries_device_type_and_class():
    from dataclasses import replace
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent

    poller = BLEPoller("/fake", ttl_s=30.0)
    t0 = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["MAC_A"] = replace(
        _build_ble_device(
            "MAC_A", first_seen=t0, last_seen=t0 + timedelta(seconds=5),
        ),
        type="Find My target", device_class="iPhone",
    )
    poller._detect_transitions(t0 + timedelta(seconds=10))  # seen
    poller.drain_transitions()
    poller._detect_transitions(t0 + timedelta(seconds=40))  # TTL evict → left
    left = [t for t in poller.drain_transitions()
            if isinstance(t, BLEDeviceLeftEvent)]
    assert len(left) == 1
    assert left[0].device_type == "Find My target"
    assert left[0].device_class == "iPhone"


def test_poller_seen_at_launch_true_inside_warmup_window():
    from datetime import timedelta
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake")
    t0 = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    # First tick anchors the launch window; nothing present yet.
    poller._detect_transitions(t0)
    poller.drain_transitions()
    # A named device appears at t0+4 (inside the 12 s window).
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", first_seen=t0 + timedelta(seconds=4),
        last_seen=t0 + timedelta(seconds=4),
    )
    poller._detect_transitions(t0 + timedelta(seconds=4))
    seen = [t for t in poller.drain_transitions()
            if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seen) == 1
    assert seen[0].at_launch is True


def test_poller_seen_at_launch_false_after_warmup_window():
    from datetime import timedelta
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake")
    t0 = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    poller._detect_transitions(t0)  # anchor launch window at t0
    poller.drain_transitions()
    # A device appears at t0+30 — well past the 12 s warmup.
    poller._devices["MAC_LATE"] = _build_ble_device(
        "MAC_LATE", first_seen=t0 + timedelta(seconds=30),
        last_seen=t0 + timedelta(seconds=30),
    )
    poller._detect_transitions(t0 + timedelta(seconds=30))
    seen = [t for t in poller.drain_transitions()
            if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seen) == 1
    assert seen[0].at_launch is False


def test_poller_connected_peripheral_seen_never_at_launch():
    from dataclasses import replace
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake")
    t0 = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    # A bonded peripheral present at t0 (inside the warmup window) must
    # NOT be folded into the census — it is high-signal.
    poller._connected["CONN"] = replace(
        _build_ble_device("CONN", name="ccy's AirPods"), is_connected=True,
    )
    poller._detect_transitions(t0)
    seen = [t for t in poller.drain_transitions()
            if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seen) == 1
    assert seen[0].identifier == "CONN"
    assert seen[0].at_launch is False


def test_poller_does_not_re_emit_seen_for_known_identifier():
    """`_seen_identifiers` guards against re-emit on subsequent ticks."""
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake")
    poller._devices["MAC_A"] = _build_ble_device("MAC_A")
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    poller._detect_transitions(now)
    poller.drain_transitions()  # discard first seen

    # Second tick with the same identifier still in state.
    poller._detect_transitions(now)
    seen = [t for t in poller.drain_transitions() if isinstance(t, BLEDeviceSeenEvent)]
    assert seen == []


def test_poller_emits_left_event_on_ttl_eviction():
    """A tracked device whose `last_seen` exceeds TTL is removed
    and emits `BLEDeviceLeftEvent` with seen_for_seconds."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent

    poller = BLEPoller("/fake", ttl_s=30.0)
    t0 = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Device first seen at t0, last_seen at t0 + 5s
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", first_seen=t0, last_seen=t0 + timedelta(seconds=5),
    )
    # First tick: device is still within TTL → emits seen, no left.
    poller._detect_transitions(t0 + timedelta(seconds=10))
    poller.drain_transitions()
    # Second tick: now > last_seen + ttl → device evicted.
    poller._detect_transitions(t0 + timedelta(seconds=40))
    out = poller.drain_transitions()
    left = [t for t in out if isinstance(t, BLEDeviceLeftEvent)]
    assert len(left) == 1
    assert left[0].identifier == "MAC_A"
    assert left[0].seen_for_seconds == 5.0


def test_poller_does_not_re_emit_left_after_identifier_returns_and_evicts_again():
    """Once an identifier emits its `left`, subsequent flap cycles
    in the same session are silent. Models the edge-of-range case
    observed in a 5.6 h capture where one identifier produced
    229 left events from a single seen — TTL evicted, an advert
    re-populated `_devices`, TTL evicted again, repeat. The fix
    gates left-emission on a per-identifier "departed" set so the
    second eviction (and every subsequent one) produces nothing.
    """
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent, BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0)
    t0 = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

    # Tick 1: device arrives → emits seen.
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    out_1 = poller.drain_transitions()
    assert any(isinstance(t, BLEDeviceSeenEvent) for t in out_1)

    # Tick 2: TTL evicts → emits left.
    poller._detect_transitions(t0 + timedelta(seconds=40))
    out_2 = poller.drain_transitions()
    left_2 = [t for t in out_2 if isinstance(t, BLEDeviceLeftEvent)]
    assert len(left_2) == 1

    # Tick 3: a fresh advert from the same identifier re-populates
    # `_devices`. This is what the helper does when CoreBluetooth
    # rediscovers the same peripheral after a brief radio gap.
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A",
        first_seen=t0 + timedelta(seconds=60),
        last_seen=t0 + timedelta(seconds=60),
    )
    poller._detect_transitions(t0 + timedelta(seconds=61))
    out_3 = poller.drain_transitions()
    # No fresh seen: identifier is in `_seen_identifiers`.
    assert [t for t in out_3 if isinstance(t, BLEDeviceSeenEvent)] == []

    # Tick 4: TTL evicts the re-introduced entry. Pre-fix this
    # emitted ANOTHER left. Post-fix: silent.
    poller._detect_transitions(t0 + timedelta(seconds=100))
    out_4 = poller.drain_transitions()
    assert [t for t in out_4 if isinstance(t, BLEDeviceLeftEvent)] == []
    assert [t for t in out_4 if isinstance(t, BLEDeviceSeenEvent)] == []


def test_poller_connected_peripheral_does_not_re_emit_seen():
    """A connected peripheral fires its seen event once and stays
    in `_connected` across subsequent ticks."""
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake")
    poller._connected["UUID_1"] = _build_ble_device(
        "UUID_1", name="Magic Keyboard",
    )
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    poller._detect_transitions(now)
    first = poller.drain_transitions()
    # Second tick — same connected peripheral.
    poller._detect_transitions(now)
    second = poller.drain_transitions()

    seen_first = [t for t in first if isinstance(t, BLEDeviceSeenEvent)]
    seen_second = [t for t in second if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seen_first) == 1
    assert seen_second == []


# ------------------------------------------------------------------
# Presence gate: anonymous adverts hold in PENDING until they've
# been observed for `presence_gate_s` seconds. Named devices and
# connected peripherals bypass the gate.
# ------------------------------------------------------------------


def test_poller_anonymous_advert_below_gate_emits_no_seen_no_left():
    """An anonymous identifier that ages out before the gate
    elapses leaves NO transition events behind. Models the
    single-packet ghost flicker that motivated the gate."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent, BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=3.0, presence_gate_s=5.0)
    t0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    # Anonymous: name=None
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name=None, first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    out_1 = poller.drain_transitions()
    assert [t for t in out_1 if isinstance(t, BLEDeviceSeenEvent)] == []
    # `MAC_A` is in PENDING.
    assert "MAC_A" in poller._pending_seen

    # Advance past TTL (3s) but before gate (5s). Device is evicted.
    poller._detect_transitions(t0 + timedelta(seconds=4))
    out_2 = poller.drain_transitions()
    assert [t for t in out_2 if isinstance(t, BLEDeviceSeenEvent)] == []
    assert [t for t in out_2 if isinstance(t, BLEDeviceLeftEvent)] == []
    # PENDING cleared, no graduation.
    assert "MAC_A" not in poller._pending_seen
    assert "MAC_A" not in poller._seen_identifiers


def test_poller_anonymous_advert_graduates_after_gate_elapses():
    """An anonymous identifier kept alive past the gate threshold
    fires seen with the device's first_seen timestamp, then on TTL
    eviction fires left with the full seen_for duration."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent, BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=5.0)
    t0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name=None, first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    poller.drain_transitions()  # discard
    # Refresh last_seen, simulating subsequent adverts arriving.
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name=None,
        first_seen=t0, last_seen=t0 + timedelta(seconds=5),
    )
    poller._detect_transitions(t0 + timedelta(seconds=6))
    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 1
    # Timestamp matches the device's original first_seen, NOT the
    # wall-clock at graduation.
    assert seens[0].timestamp == t0

    # Now age out and assert left fires (gate-graduated → present →
    # eligible for left).
    poller._detect_transitions(t0 + timedelta(seconds=60))
    out2 = poller.drain_transitions()
    lefts = [t for t in out2 if isinstance(t, BLEDeviceLeftEvent)]
    assert len(lefts) == 1
    assert lefts[0].seen_for_seconds == 5.0


def test_poller_named_first_advert_bypasses_gate():
    """A first advert that carries a `name` fires seen on the
    same tick, regardless of presence_gate_s. The events log
    must not lag the BLE list for paired peripherals."""
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=60.0)
    t0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name="Magic Keyboard", first_seen=t0,
    )
    poller._detect_transitions(t0)
    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 1
    # Did NOT pass through PENDING.
    assert "MAC_A" not in poller._pending_seen


def test_poller_connected_peripheral_bypasses_gate():
    """A connected peripheral (entry in `_connected`) fires seen
    on the same tick regardless of gate setting. Bonded
    peripherals are by-definition high-confidence."""
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=60.0)
    poller._connected["UUID_1"] = _build_ble_device(
        "UUID_1", name="AirPods", vendor="Apple, Inc.",
    )
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    poller._detect_transitions(now)
    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 1
    assert "UUID_1" not in poller._pending_seen


def test_poller_presence_gate_zero_restores_no_debounce():
    """`presence_gate_s = 0` returns to the A1 contract: every
    first observation (even anonymous) fires seen immediately,
    with no PENDING state."""
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=0.0)
    t0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name=None, first_seen=t0,
    )
    poller._detect_transitions(t0)
    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 1
    assert "MAC_A" not in poller._pending_seen


def test_poller_pending_identifier_graduates_when_name_appears_in_later_advert():
    """If an identifier's first advert is anonymous but a later
    advert (e.g. a scan-response) carries a name before the gate
    elapses, the identifier graduates immediately. `_build_device`
    already carries the name forward via `prior`."""
    from datetime import timedelta
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=10.0)
    t0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name=None, first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    assert "MAC_A" in poller._pending_seen
    # Later advert carries the name.
    poller._devices["MAC_A"] = _build_ble_device(
        "MAC_A", name="Magic Keyboard",
        first_seen=t0, last_seen=t0 + timedelta(seconds=3),
    )
    poller._detect_transitions(t0 + timedelta(seconds=4))
    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 1
    assert seens[0].name == "Magic Keyboard"
    # Out of PENDING, into PRESENT.
    assert "MAC_A" not in poller._pending_seen
    assert "MAC_A" in poller._seen_identifiers


# ---------- v1.8.0 cluster-keyed transition events ----------
#
# The merger applies merge_for_display's fingerprint to the
# transition emitter so one physical device's rotation through N
# privacy-rotated identifiers fires ONE BLEDeviceSeenEvent + ONE
# BLEDeviceLeftEvent across the cluster's session, not N+N.


def _build_ble_device_anon(
    identifier: str,
    *,
    vendor_id: int | None = 76,  # Apple
    name: str | None = None,
    rssi_dbm: int | None = -55,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    services: tuple[str, ...] = (),
) -> BLEDevice:
    """Variant of `_build_ble_device` for clustering tests — defaults
    to anonymous (name=None) so the cluster fingerprint exercises
    the common Apple Continuity / Microsoft CDP rotation shape."""
    t = first_seen or datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    t_last = last_seen or t
    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor="Apple, Inc." if vendor_id == 76 else None,
        vendor_id=vendor_id,
        services=services,
        rssi_dbm=rssi_dbm,
        is_connectable=True,
        first_seen=t,
        last_seen=t_last,
        ad_count=1,
    )


def test_cluster_one_iphone_rotating_four_identifiers_fires_one_seen_one_left():
    """Single physical device rotates through 4 identifiers in one
    session. Fingerprint matches (same vendor, same name=None,
    RSSI within ±10 dB). Exactly one seen + one left across the
    whole rotation; both events carry the FIRST identifier as
    their representative."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent, BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=0.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    # Identifier 1 arrives.
    poller._devices["ID_1"] = _build_ble_device_anon(
        "ID_1", rssi_dbm=-50, first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    # Identifier 2 arrives at t+10 (rotation), within RSSI window.
    poller._devices["ID_2"] = _build_ble_device_anon(
        "ID_2", rssi_dbm=-52,
        first_seen=t0 + timedelta(seconds=10),
        last_seen=t0 + timedelta(seconds=10),
    )
    poller._detect_transitions(t0 + timedelta(seconds=11))
    # Identifier 3 arrives at t+20.
    poller._devices["ID_3"] = _build_ble_device_anon(
        "ID_3", rssi_dbm=-48,
        first_seen=t0 + timedelta(seconds=20),
        last_seen=t0 + timedelta(seconds=20),
    )
    poller._detect_transitions(t0 + timedelta(seconds=21))
    # Identifier 4 arrives at t+30, ID_1 ages out (TTL exceeded
    # since last_seen=t0). Partial departure — no left expected.
    poller._devices["ID_4"] = _build_ble_device_anon(
        "ID_4", rssi_dbm=-51,
        first_seen=t0 + timedelta(seconds=30),
        last_seen=t0 + timedelta(seconds=30),
    )
    poller._detect_transitions(t0 + timedelta(seconds=31))

    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    lefts = [t for t in out if isinstance(t, BLEDeviceLeftEvent)]
    assert len(seens) == 1, f"expected one cluster seen, got {len(seens)}"
    assert seens[0].identifier == "ID_1", "representative is the first graduated"
    assert lefts == [], "partial cluster departure must be silent"

    # Now age out all remaining identifiers — cluster fires its left.
    # Don't clear() (that would empty the `before` snapshot inside
    # _detect_transitions); just advance the clock past TTL so the
    # internal expire pass evicts naturally.
    poller._detect_transitions(t0 + timedelta(seconds=120))
    out = poller.drain_transitions()
    lefts = [t for t in out if isinstance(t, BLEDeviceLeftEvent)]
    assert len(lefts) == 1, "exactly one left when last cluster member evicts"
    assert lefts[0].identifier == "ID_1", "left identifier matches the cluster representative"


def test_cluster_two_devices_at_different_rssi_buckets_fire_separately():
    """Two physically distinct devices at -50 dBm and -75 dBm
    (>10 dB apart) form two clusters; two seens fire."""
    from datetime import timedelta
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake", presence_gate_s=0.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["NEAR"] = _build_ble_device_anon("NEAR", rssi_dbm=-50, first_seen=t0)
    poller._devices["FAR"] = _build_ble_device_anon("FAR", rssi_dbm=-75, first_seen=t0)
    poller._detect_transitions(t0 + timedelta(seconds=1))

    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 2
    idents = {s.identifier for s in seens}
    assert idents == {"NEAR", "FAR"}
    # Two clusters in the index.
    assert len(poller._clusters) == 2


def test_cluster_presence_gate_failing_flit_does_not_claim_cluster():
    """Anonymous identifier evicted before its presence-gate window
    matures must not create or join any cluster."""
    from datetime import timedelta

    poller = BLEPoller("/fake", ttl_s=2.0, presence_gate_s=5.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["FLIT"] = _build_ble_device_anon(
        "FLIT", first_seen=t0, last_seen=t0,
    )
    # Observe at t+1 — gate still pending.
    poller._detect_transitions(t0 + timedelta(seconds=1))
    # At t+3, TTL evicts (last_seen=t0, ttl=2s).
    poller._detect_transitions(t0 + timedelta(seconds=3))

    out = poller.drain_transitions()
    assert out == [], "no transitions for gate-failing flit"
    assert "FLIT" not in poller._identifier_to_cluster
    assert poller._clusters == {}


def test_cluster_disabled_via_env_restores_per_identifier_semantics():
    """`enable_cluster_merger=False` makes every identifier graduation
    fire its own seen and every TTL eviction fire its own left."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent, BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=0.0,
                       enable_cluster_merger=False)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["ID_1"] = _build_ble_device_anon("ID_1", rssi_dbm=-50, first_seen=t0)
    poller._devices["ID_2"] = _build_ble_device_anon("ID_2", rssi_dbm=-50, first_seen=t0)
    poller._detect_transitions(t0 + timedelta(seconds=1))

    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 2, "per-identifier semantics: one seen per identifier"


def test_cluster_partial_departure_silent():
    """A cluster with 3 active identifiers losing one to TTL must
    NOT fire a left event; the cluster persists with 2 members."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=0.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    for ident in ("ID_1", "ID_2", "ID_3"):
        poller._devices[ident] = _build_ble_device_anon(
            ident, rssi_dbm=-50, first_seen=t0, last_seen=t0,
        )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    poller.drain_transitions()  # discard the one cluster seen

    # ID_1 ages out (last_seen=t0, ttl=30s, now=t0+40 evicts).
    # ID_2 + ID_3 are refreshed at t0+30 so they survive.
    poller._devices["ID_2"] = _build_ble_device_anon(
        "ID_2", rssi_dbm=-50, first_seen=t0,
        last_seen=t0 + timedelta(seconds=30),
    )
    poller._devices["ID_3"] = _build_ble_device_anon(
        "ID_3", rssi_dbm=-50, first_seen=t0,
        last_seen=t0 + timedelta(seconds=30),
    )
    poller._detect_transitions(t0 + timedelta(seconds=40))

    out = poller.drain_transitions()
    lefts = [t for t in out if isinstance(t, BLEDeviceLeftEvent)]
    assert lefts == [], "partial cluster departure must be silent"
    # Cluster still exists.
    assert len(poller._clusters) == 1
    cluster = next(iter(poller._clusters.values()))
    assert cluster.active_members == {"ID_2", "ID_3"}


def test_cluster_lifetime_ends_then_device_returns_fires_fresh_seen():
    """When a cluster's last member evicts and the cluster is
    destroyed, a later identifier matching the same fingerprint
    creates a NEW cluster and fires a fresh seen event."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent, BLEDeviceSeenEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=0.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)

    # Phase 1: device shows up.
    poller._devices["ID_1"] = _build_ble_device_anon(
        "ID_1", rssi_dbm=-50, first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    # Phase 2: TTL evicts naturally (last_seen=t0, ttl=30, now=t0+60).
    poller._detect_transitions(t0 + timedelta(seconds=60))
    # Phase 3: device returns 20 min later under a fresh identifier.
    later = t0 + timedelta(seconds=20 * 60)
    poller._devices["ID_2"] = _build_ble_device_anon(
        "ID_2", rssi_dbm=-50, first_seen=later, last_seen=later,
    )
    poller._detect_transitions(later + timedelta(seconds=1))

    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    lefts = [t for t in out if isinstance(t, BLEDeviceLeftEvent)]
    # Two clusters' worth of events: original session + return.
    assert len(seens) == 2
    assert len(lefts) == 1
    assert seens[0].identifier == "ID_1"
    assert seens[1].identifier == "ID_2"
    assert lefts[0].identifier == "ID_1"


def test_cluster_fully_anonymous_devices_each_get_own_cluster():
    """Devices with both `vendor_id=None` AND `name=None` are
    unmergeable per `merge_for_display`'s rule — each gets its
    own single-member cluster and fires its own seen."""
    from datetime import timedelta
    from diting.events import BLEDeviceSeenEvent

    poller = BLEPoller("/fake", presence_gate_s=0.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["A1"] = _build_ble_device_anon(
        "A1", vendor_id=None, name=None, rssi_dbm=-50, first_seen=t0,
    )
    poller._devices["A2"] = _build_ble_device_anon(
        "A2", vendor_id=None, name=None, rssi_dbm=-50, first_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))

    out = poller.drain_transitions()
    seens = [t for t in out if isinstance(t, BLEDeviceSeenEvent)]
    assert len(seens) == 2, "fully-anonymous devices do not merge"


def test_cluster_fingerprint_constants_shared_with_merge_for_display():
    """Both the BLE-panel merger and the transition emitter MUST
    read the same threshold constants from `diting.ble` — prevents
    silent drift between the live view and the events stream."""
    from diting.ble import _RSSI_WINDOW_DB, _JACCARD_THRESHOLD, merge_for_display
    import inspect

    assert isinstance(_RSSI_WINDOW_DB, int)
    assert isinstance(_JACCARD_THRESHOLD, float)
    # `merge_for_display`'s default rssi_window_db must equal the
    # module-level constant (not a literal). Inspecting the
    # signature catches a future contributor hard-coding `10` in
    # the default and drifting from the cluster merger.
    sig = inspect.signature(merge_for_display)
    assert sig.parameters["rssi_window_db"].default == _RSSI_WINDOW_DB


def test_cluster_representative_id_survives_when_first_member_evicts():
    """Cluster's stored `representative_id` is the FIRST graduated
    identifier and does not rotate even if that identifier itself
    is the first to TTL-evict."""
    from datetime import timedelta
    from diting.events import BLEDeviceLeftEvent

    poller = BLEPoller("/fake", ttl_s=30.0, presence_gate_s=0.0)
    t0 = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    poller._devices["FIRST"] = _build_ble_device_anon(
        "FIRST", rssi_dbm=-50, first_seen=t0, last_seen=t0,
    )
    poller._detect_transitions(t0 + timedelta(seconds=1))
    # SECOND joins the cluster at t+10 and gets refreshed beyond
    # FIRST's TTL window.
    poller._devices["SECOND"] = _build_ble_device_anon(
        "SECOND", rssi_dbm=-50,
        first_seen=t0 + timedelta(seconds=10),
        last_seen=t0 + timedelta(seconds=10),
    )
    poller._detect_transitions(t0 + timedelta(seconds=11))
    # FIRST evicts at t+40 (last_seen=t0, ttl=30s), SECOND refreshed.
    poller._devices["SECOND"] = _build_ble_device_anon(
        "SECOND", rssi_dbm=-50,
        first_seen=t0 + timedelta(seconds=10),
        last_seen=t0 + timedelta(seconds=40),
    )
    poller._detect_transitions(t0 + timedelta(seconds=41))
    # Cluster persists; representative is still FIRST.
    cluster = next(iter(poller._clusters.values()))
    assert cluster.representative_id == "FIRST"
    assert cluster.active_members == {"SECOND"}
    # SECOND evicts at t+80 (last_seen=t0+40, ttl=30, now=t0+80
    # → 40 s past, TTL exceeded) → cluster fires left under FIRST.
    poller._detect_transitions(t0 + timedelta(seconds=80))
    out = poller.drain_transitions()
    lefts = [t for t in out if isinstance(t, BLEDeviceLeftEvent)]
    assert len(lefts) == 1
    assert lefts[0].identifier == "FIRST", (
        "cluster left event carries the cluster's representative ID, "
        "not the most-recently-evicted member"
    )
