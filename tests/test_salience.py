"""Salience scorer tests (add-event-salience).

The scorer is pure + must never raise; it reads only authoritative payload
fields and ranks an event into noise < low < notable < high (or abstains).
"""

from __future__ import annotations

from diting.salience import (
    HIGH,
    LOW,
    NOISE,
    NOTABLE,
    meets_threshold,
    salience,
    tier_rank,
)


def _ble_seen(familiarity=None, rssi=-75, at_launch=False):
    p = {"type": "ble_device_seen", "identifier": "X", "rssi_dbm": rssi}
    if familiarity is not None:
        p["familiarity"] = familiarity
    if at_launch:
        p["at_launch"] = True
    return p


# ---------- tier ordering ----------

def test_tier_rank_is_ordered():
    assert tier_rank(NOISE) < tier_rank(LOW) < tier_rank(NOTABLE) < tier_rank(HIGH)


def test_unknown_or_missing_tier_ranks_below_noise():
    assert tier_rank(None) < tier_rank(NOISE)
    assert tier_rank("bogus") < tier_rank(NOISE)


def test_meets_threshold():
    assert meets_threshold(NOTABLE, LOW) is True
    assert meets_threshold(LOW, NOTABLE) is False
    assert meets_threshold(NOISE, LOW) is False
    # Absent tier meets nothing.
    assert meets_threshold(None, LOW) is False


# ---------- familiarity-weighted arrivals ----------

def test_habitual_arrival_is_noise():
    assert salience(_ble_seen("habitual")) == NOISE


def test_occasional_arrival_is_low():
    assert salience(_ble_seen("occasional")) == LOW


def test_returning_arrival_is_notable():
    assert salience(_ble_seen("returning")) == NOTABLE


def test_first_time_arrival_is_notable_when_far():
    assert salience(_ble_seen("first_time", rssi=-85)) == NOTABLE


def test_first_time_close_ble_is_high():
    assert salience(_ble_seen("first_time", rssi=-50)) == HIGH


def test_close_bump_is_ble_only():
    # A close first-time LAN host has no RSSI bump path → stays notable.
    assert salience({
        "type": "lan_host_seen", "mac": "aa", "familiarity": "first_time",
    }) == NOTABLE


def test_absent_familiarity_arrival_is_low_never_noise():
    assert salience(_ble_seen(None)) == LOW


def test_at_launch_caps_below_notable():
    # first_time + close would be high, but the at-launch warmup is capped.
    assert salience(_ble_seen("first_time", rssi=-50, at_launch=True)) == LOW


# ---------- intrinsic anomalies (familiarity-independent) ----------

def test_loss_burst_is_high():
    assert salience({"type": "loss_burst", "loss_pct": 12}) == HIGH


def test_latency_spike_is_notable():
    assert salience({"type": "latency_spike", "rtt_ms": 800}) == NOTABLE


def test_network_change_is_notable():
    assert salience({"type": "network_change", "new_router_ip": "10.0.0.1"}) == NOTABLE


def test_rf_stir_scales_with_confidence():
    assert salience({"type": "rf_stir", "confidence": "high"}) == HIGH
    assert salience({"type": "rf_stir", "confidence": "medium"}) == NOTABLE
    assert salience({"type": "rf_stir", "confidence": "low"}) == LOW


def test_link_state_disassociated_is_notable_associated_low():
    assert salience({"type": "link_state", "state": "disassociated"}) == NOTABLE
    assert salience({"type": "link_state", "state": "associated"}) == LOW


# ---------- roam ----------

def test_band_switch_roam_is_low():
    assert salience({
        "type": "roam", "kind": "band_switch", "new_bssid": "x",
        "familiarity": "first_time",
    }) == LOW


def test_inter_ap_roam_to_new_bssid_is_notable():
    assert salience({
        "type": "roam", "kind": "inter_ap", "new_bssid": "x",
        "familiarity": "first_time",
    }) == NOTABLE


# ---------- departures + abstentions ----------

def test_departures_are_noise():
    assert salience({"type": "ble_device_left", "identifier": "x"}) == NOISE
    assert salience({"type": "lan_host_left", "mac": "x"}) == NOISE


def test_dhcp_rotation_is_low():
    assert salience({"type": "lan_host_dhcp_rotation", "mac": "x"}) == LOW


def test_session_meta_abstains():
    assert salience({"type": "session_meta", "scene": "home"}) is None


def test_unknown_type_abstains():
    assert salience({"type": "totally_unknown"}) is None


def test_never_raises_on_malformed():
    assert salience({}) is None
    assert salience({"type": "ble_device_seen"}) == LOW  # no familiarity, no rssi
    # Non-dict input abstains rather than raising.
    assert salience(None) is None  # type: ignore[arg-type]


def test_critical_insight_is_high():
    # Phase 3 threats use the `critical` severity.
    assert salience({"type": "insight", "code": "evil_twin", "severity": "critical"}) == HIGH
