"""Familiarity store — key derivation, class thresholds, dwell EWMA,
persistence round-trip, fail-soft read, and bounds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from diting.familiarity import (
    FIRST_TIME, OCCASIONAL, HABITUAL, RETURNING,
    FamiliarityStore, familiarity_key,
)


def _t(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=timezone.utc)


# ---------- key derivation (authoritative, never a name) ----------

def test_ble_key_prefers_payload_not_uuid_or_name():
    k = familiarity_key("ble", manufacturer_hex="9904aabbccdd", vendor_id=0x0499, name="RuuviTag")
    assert k == "ble:9904aabbccdd"  # payload, not the name


def test_ble_key_falls_back_to_vendor_name_without_payload():
    assert familiarity_key("ble", vendor_id=76, name="Magic Keyboard") == "ble:vn:76/Magic Keyboard"


def test_ble_apple_payload_is_not_used_as_key():
    # Apple Continuity payloads are generic → fall back to (vendor, name).
    k = familiarity_key("ble", manufacturer_hex="4c00120200010000", vendor_id=0x004C, name=None)
    assert k == "ble:vn:76/"


def test_other_kinds_key_on_address_not_name():
    assert familiarity_key("ap", bssid="aa:bb:cc:dd:ee:ff") == "ap:aa:bb:cc:dd:ee:ff"
    assert familiarity_key("lan", mac="AA:BB:CC:00:11:22") == "lan:aa:bb:cc:00:11:22"
    assert familiarity_key("bonjour", service="_airplay._tcp/Office") == "bonjour:_airplay._tcp/Office"


def test_key_is_none_without_stable_identity():
    assert familiarity_key("ble") is None
    assert familiarity_key("ap") is None


# ---------- classification (pre-sighting state) ----------

def test_first_ever_is_first_time(tmp_path):
    s = FamiliarityStore(tmp_path / "f.json")
    assert s.observe_seen("ble:x", "ble", _t(1)) == FIRST_TIME


def test_second_sighting_same_day_is_occasional(tmp_path):
    s = FamiliarityStore(tmp_path / "f.json")
    s.observe_seen("ble:x", "ble", _t(1, 9))
    assert s.observe_seen("ble:x", "ble", _t(1, 10)) == OCCASIONAL


def test_habitual_after_three_distinct_days(tmp_path):
    s = FamiliarityStore(tmp_path / "f.json")
    s.observe_seen("ble:x", "ble", _t(1))  # first_time
    s.observe_seen("ble:x", "ble", _t(2))  # occasional (1 day)
    s.observe_seen("ble:x", "ble", _t(3))  # occasional (2 days)
    # Now seen on 3 distinct days → next sighting classifies habitual.
    assert s.observe_seen("ble:x", "ble", _t(4)) == HABITUAL


def test_returning_after_long_absence(tmp_path):
    s = FamiliarityStore(tmp_path / "f.json")
    for d in (1, 2, 3):
        s.observe_seen("ble:x", "ble", _t(d))
    # Habitual, then absent > 7 days, then back → returning.
    assert s.observe_seen("ble:x", "ble", _t(15)) == RETURNING


def test_dwell_ewma_folds(tmp_path):
    s = FamiliarityStore(tmp_path / "f.json")
    s.observe_seen("ble:x", "ble", _t(1))
    s.observe_left("ble:x", 100.0)
    assert s.record("ble:x").dwell_ewma_s == 100.0
    s.observe_left("ble:x", 200.0)
    # 0.3*200 + 0.7*100 = 130
    assert abs(s.record("ble:x").dwell_ewma_s - 130.0) < 1e-6


# ---------- persistence + fail-soft + bounds ----------

def test_persistence_round_trip(tmp_path):
    p = tmp_path / "f.json"
    s = FamiliarityStore(p)
    s.observe_seen("ap:bss", "ap", _t(1))
    s.flush(now=_t(1))
    reopened = FamiliarityStore(p)
    assert reopened.observe_seen("ap:bss", "ap", _t(1, 13)) == OCCASIONAL  # remembered


def test_corrupt_file_is_failsoft(tmp_path):
    p = tmp_path / "f.json"
    p.write_text("not json at all {{{")
    s = FamiliarityStore(p)  # must not raise
    assert len(s) == 0
    assert s.observe_seen("ble:x", "ble", _t(1)) == FIRST_TIME


def test_corrupt_record_skipped_valid_kept(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(
        '{"ble:good": {"kind":"ble","first_seen_ever":"2026-06-01T00:00:00+00:00",'
        '"last_seen":"2026-06-01T00:00:00+00:00","total_sightings":1,"days":["2026-06-01"]},'
        '"ble:bad": {"oops": true}}'
    )
    s = FamiliarityStore(p)
    assert s.record("ble:good") is not None
    assert s.record("ble:bad") is None


def test_age_out_on_flush(tmp_path):
    p = tmp_path / "f.json"
    s = FamiliarityStore(p)
    s.observe_seen("ble:old", "ble", _t(1))
    s.observe_seen("ble:new", "ble", _t(1))
    # Flush "now" 40 days later → ble:old (last seen day 1) ages out (>30d).
    s.flush(now=_t(1) + timedelta(days=40))
    reopened = FamiliarityStore(p)
    assert reopened.record("ble:new") is None  # both aged out (seen day 1)
    # Re-seeing within retention keeps it.
    s2 = FamiliarityStore(p)
    s2.observe_seen("ble:fresh", "ble", _t(1))
    s2.flush(now=_t(2))
    assert FamiliarityStore(p).record("ble:fresh") is not None


# ---------- extended BLE key ladder (extend-ble-familiarity-identity) ----------

def test_ble_key_uses_service_data_id_when_no_payload():
    # Payload-less / nameless device with a decoded service-data id → ble:sd.
    assert familiarity_key(
        "ble", service_data_id="mibeacon:aa:bb:cc:dd:ee:ff",
        vendor="Anhui Huami...",
    ) == "ble:sd:mibeacon:aa:bb:cc:dd:ee:ff"


def test_ble_key_vendor_group_last_resort():
    # No payload, no service-data id, no vendor_id, no name — but a confidently
    # attributed vendor → coarse vendor-group key.
    assert familiarity_key("ble", vendor="Huawei Technologies Co., Ltd.") \
        == "ble:vg:Huawei Technologies Co., Ltd."


def test_ble_key_precedence_payload_over_service_data():
    # A real manufacturer payload still wins (existing behaviour preserved).
    assert familiarity_key(
        "ble", manufacturer_hex="0157a1b2", vendor_id=343,
        service_data_id="mibeacon:aa:bb:cc:dd:ee:ff", vendor="X",
    ) == "ble:0157a1b2"


def test_ble_key_precedence_service_data_over_vendor_name_and_group():
    assert familiarity_key(
        "ble", service_data_id="mibeacon:1", vendor_id=999, name="Band",
        vendor="V",
    ) == "ble:sd:mibeacon:1"


def test_ble_key_vendor_name_over_vendor_group():
    assert familiarity_key("ble", vendor_id=999, vendor="V") == "ble:vn:999/"


def test_ble_key_none_when_nothing_identifying():
    # Truly anonymous (no payload, no sd id, no vendor_id, no name, no vendor).
    assert familiarity_key("ble") is None
