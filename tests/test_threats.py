"""Threat engine tests (add-threat-detections).

Defensive-security detectors over the enriched stream. Hermetic: feed payloads,
collect(now) with an injected clock. Threats are critical-severity InsightEvents.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from diting.threats import ThreatEngine

NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _assoc(ssid, vendor, bssid="aa:bb:cc:dd:ee:ff"):
    return {"type": "link_state", "state": "associated",
            "ssid": ssid, "bssid": bssid, "vendor": vendor, "ts": _ts(1)}


def _codes(events):
    return [e.code for e in events]


# ---------- evil_twin ----------

def test_evil_twin_fires_on_same_ssid_different_vendor():
    eng = ThreatEngine()
    eng.observe(_assoc("cafe", "Cisco Systems"))
    eng.observe(_assoc("cafe", "Espressif Inc."))
    fired = [e for e in eng.collect(NOW) if e.code == "evil_twin"]
    assert len(fired) == 1
    assert fired[0].severity == "critical"
    assert fired[0].detail["ssid"] == "cafe"
    assert fired[0].detail["new_vendor"] == "Espressif Inc."


def test_evil_twin_first_vendor_does_not_fire():
    eng = ThreatEngine()
    eng.observe(_assoc("cafe", "Cisco Systems"))
    assert "evil_twin" not in _codes(eng.collect(NOW))


def test_evil_twin_same_vendor_does_not_fire():
    eng = ThreatEngine()
    eng.observe(_assoc("cafe", "Cisco Systems", bssid="aa:11"))
    eng.observe(_assoc("cafe", "Cisco Systems", bssid="bb:22"))  # roam, same vendor
    assert "evil_twin" not in _codes(eng.collect(NOW))


def test_evil_twin_via_roam_new_vendor():
    eng = ThreatEngine()
    eng.observe(_assoc("cafe", "Cisco Systems"))
    eng.observe({
        "type": "roam", "new_ssid": "cafe", "new_bssid": "ff:ee",
        "new_vendor": "TP-Link", "ts": _ts(1),
    })
    assert "evil_twin" in _codes(eng.collect(NOW))


def test_evil_twin_none_vendor_cannot_fire():
    eng = ThreatEngine()
    eng.observe(_assoc("cafe", "Cisco Systems"))
    eng.observe(_assoc("cafe", None))   # unknown OUI → no comparison
    assert "evil_twin" not in _codes(eng.collect(NOW))


def test_evil_twin_distinct_ssids_independent_cooldown():
    eng = ThreatEngine()
    for ssid in ("cafe", "hotel"):
        eng.observe(_assoc(ssid, "Cisco Systems"))
        eng.observe(_assoc(ssid, "Netgear"))
    fired = [e for e in eng.collect(NOW) if e.code == "evil_twin"]
    assert {e.detail["ssid"] for e in fired} == {"cafe", "hotel"}


def test_evil_twin_cooldown_suppresses_repeat():
    eng = ThreatEngine(cooldown_s=300)
    eng.observe(_assoc("cafe", "Cisco Systems"))
    eng.observe(_assoc("cafe", "Netgear"))
    assert "evil_twin" in _codes(eng.collect(NOW))
    # A further different vendor within cooldown → suppressed.
    eng.observe(_assoc("cafe", "Aruba"))
    assert "evil_twin" not in _codes(eng.collect(NOW + timedelta(seconds=30)))


# ---------- deauth_storm ----------

def _disassoc(seconds_ago):
    return {"type": "link_state", "state": "disassociated", "ts": _ts(seconds_ago)}


def test_deauth_storm_fires_on_tight_burst():
    eng = ThreatEngine(storm_window_s=90, storm_min=4)
    for s in (1, 2, 3, 4):
        eng.observe(_disassoc(s))
    fired = [e for e in eng.collect(NOW) if e.code == "deauth_storm"]
    assert fired and fired[0].severity == "critical"
    assert fired[0].detail["count"] == 4


def test_deauth_storm_does_not_fire_when_spread_out():
    eng = ThreatEngine(storm_window_s=90, storm_min=4)
    # Three disconnects, all older than the tight window.
    for s in (300, 600, 900):
        eng.observe(_disassoc(s))
    assert "deauth_storm" not in _codes(eng.collect(NOW))


def test_deauth_storm_below_threshold_does_not_fire():
    eng = ThreatEngine(storm_window_s=90, storm_min=4)
    for s in (1, 2, 3):
        eng.observe(_disassoc(s))
    assert "deauth_storm" not in _codes(eng.collect(NOW))


# ---------- follows_you ----------

def _ble(ident, familiarity="first_time"):
    return {"type": "ble_device_seen", "identifier": ident,
            "familiarity": familiarity, "ts": _ts(1)}


def test_follows_you_fires_across_network_change():
    eng = ThreatEngine()
    eng.observe(_ble("dev-1"))
    eng.observe({"type": "network_change", "new_router_ip": "10.0.0.1", "ts": _ts(1)})
    eng.observe(_ble("dev-1"))
    fired = [e for e in eng.collect(NOW) if e.code == "follows_you"]
    assert fired and fired[0].severity == "critical"
    assert fired[0].detail["identifier"] == "dev-1"
    assert fired[0].detail["locations"] == 2


def test_follows_you_single_epoch_does_not_fire():
    eng = ThreatEngine()
    eng.observe(_ble("dev-1"))
    eng.observe(_ble("dev-1"))  # same epoch, no network_change
    assert "follows_you" not in _codes(eng.collect(NOW))


def test_follows_you_habitual_device_does_not_fire():
    eng = ThreatEngine()
    eng.observe(_ble("mine", familiarity="habitual"))
    eng.observe({"type": "network_change", "new_router_ip": "10.0.0.1", "ts": _ts(1)})
    eng.observe(_ble("mine", familiarity="habitual"))
    assert "follows_you" not in _codes(eng.collect(NOW))


# ---------- robustness ----------

def test_ignores_insight_payloads():
    eng = ThreatEngine()
    eng.observe({"type": "insight", "code": "evil_twin", "severity": "critical", "ts": _ts(1)})
    assert eng.collect(NOW) == []


def test_never_raises_on_malformed():
    eng = ThreatEngine()
    eng.observe(None)
    eng.observe({})
    eng.observe({"type": "link_state", "state": "disassociated"})  # no ts
    eng.observe({"type": "link_state", "state": "associated"})     # no ssid/vendor
    eng.observe({"type": "roam"})
    eng.observe({"type": "ble_device_seen"})
    assert eng.collect(NOW) == []
