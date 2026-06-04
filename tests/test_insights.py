"""Live insight engine tests (add-insight-events).

The engine observes enriched wire payloads into bounded rolling windows and
collect(now) returns the insights that fired, debounced per code. Hermetic:
inject payloads + an explicit `now`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from diting.insights import InsightEngine, format_insight_summary

NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _arrival(seconds_ago=1.0, familiarity="first_time", etype="ble_device_seen",
             rssi=-55):
    # Default a NEAR rssi so BLE arrivals clear the cluster proximity gate;
    # tests that want a far / no-rssi device pass rssi explicitly / None.
    p = {"type": etype, "ts": _ts(seconds_ago), "familiarity": familiarity}
    if rssi is not None:
        p["rssi_dbm"] = rssi
    return p


def _codes(events):
    return {e.code for e in events}


# ---------- 2b: new_device_cluster ----------

def test_cluster_fires_on_three_first_time_arrivals():
    eng = InsightEngine()
    for i in range(3):
        eng.observe(_arrival(seconds_ago=i, etype="ble_device_seen"))
    fired = eng.collect(NOW)
    cluster = [e for e in fired if e.code == "new_device_cluster"]
    assert len(cluster) == 1
    assert cluster[0].severity == "note"
    assert cluster[0].detail["count"] == 3


def test_cluster_spans_device_kinds():
    eng = InsightEngine()
    eng.observe(_arrival(etype="ble_device_seen"))
    eng.observe(_arrival(etype="lan_host_seen"))
    eng.observe(_arrival(etype="bonjour_service_seen"))
    assert "new_device_cluster" in _codes(eng.collect(NOW))


def test_habitual_arrivals_do_not_cluster():
    eng = InsightEngine()
    for _ in range(5):
        eng.observe(_arrival(familiarity="habitual"))
    assert "new_device_cluster" not in _codes(eng.collect(NOW))


def test_two_arrivals_below_threshold_do_not_cluster():
    eng = InsightEngine()
    eng.observe(_arrival())
    eng.observe(_arrival())
    assert "new_device_cluster" not in _codes(eng.collect(NOW))


def test_arrivals_outside_cluster_window_excluded():
    eng = InsightEngine(cluster_window_s=120)
    eng.observe(_arrival(seconds_ago=5))
    eng.observe(_arrival(seconds_ago=5))
    eng.observe(_arrival(seconds_ago=500))  # too old
    assert "new_device_cluster" not in _codes(eng.collect(NOW))


def test_far_ble_arrivals_do_not_cluster():
    # Far-field office churn (weak RSSI) must NOT trip the cluster — this is
    # the over-firing fix.
    eng = InsightEngine()
    for i in range(4):
        eng.observe(_arrival(seconds_ago=i, rssi=-85))
    assert "new_device_cluster" not in _codes(eng.collect(NOW))


def test_ble_arrivals_without_rssi_do_not_cluster():
    eng = InsightEngine()
    for i in range(4):
        eng.observe(_arrival(seconds_ago=i, rssi=None))  # no proximity info
    assert "new_device_cluster" not in _codes(eng.collect(NOW))


def test_near_ble_arrivals_cluster():
    eng = InsightEngine()
    for i in range(3):
        eng.observe(_arrival(seconds_ago=i, rssi=-60))  # near
    assert "new_device_cluster" in _codes(eng.collect(NOW))


def test_lan_bonjour_arrivals_count_without_rssi():
    # Non-BLE arrivals have no proximity dimension and always count.
    eng = InsightEngine()
    eng.observe(_arrival(etype="lan_host_seen", rssi=None))
    eng.observe(_arrival(etype="bonjour_service_seen", rssi=None))
    eng.observe(_arrival(etype="lan_host_seen", seconds_ago=2, rssi=None))
    assert "new_device_cluster" in _codes(eng.collect(NOW))


# ---------- cooldown ----------

def test_cooldown_fires_once_per_window():
    eng = InsightEngine(cooldown_s=300)
    for _ in range(3):
        eng.observe(_arrival())
    assert "new_device_cluster" in _codes(eng.collect(NOW))
    # Immediate re-collect: still within cooldown → silent.
    assert eng.collect(NOW + timedelta(seconds=10)) == []
    # After cooldown, with fresh arrivals in window, fires again.
    for _ in range(3):
        eng.observe({"type": "ble_device_seen",
                     "ts": (NOW + timedelta(seconds=305)).isoformat(),
                     "familiarity": "first_time", "rssi_dbm": -55})
    assert "new_device_cluster" in _codes(eng.collect(NOW + timedelta(seconds=310)))


# ---------- 2c: live-ified analyze heuristics ----------

def test_repeated_disassociates_warns():
    eng = InsightEngine()
    for i in range(3):
        eng.observe({"type": "link_state", "state": "disassociated", "ts": _ts(i)})
    fired = [e for e in eng.collect(NOW) if e.code == "repeated_disassociates"]
    assert fired and fired[0].severity == "warn" and fired[0].detail["count"] == 3


def test_two_disassociates_below_threshold():
    eng = InsightEngine()
    for i in range(2):
        eng.observe({"type": "link_state", "state": "disassociated", "ts": _ts(i)})
    assert "repeated_disassociates" not in _codes(eng.collect(NOW))


def test_loss_observed_warns_with_peak():
    eng = InsightEngine()
    eng.observe({"type": "loss_burst", "ts": _ts(10), "loss_pct": 12.0})
    eng.observe({"type": "loss_burst", "ts": _ts(5), "loss_pct": 40.0})
    fired = [e for e in eng.collect(NOW) if e.code == "loss_observed"]
    assert fired and fired[0].severity == "warn"
    assert fired[0].detail["peak_loss_pct"] == 40.0


def test_latency_without_loss_is_a_note():
    eng = InsightEngine()
    eng.observe({"type": "latency_spike", "ts": _ts(5)})
    fired = [e for e in eng.collect(NOW) if e.code == "latency_without_loss"]
    assert fired and fired[0].severity == "note"


def test_latency_with_loss_suppresses_jitter_note():
    eng = InsightEngine()
    eng.observe({"type": "latency_spike", "ts": _ts(5)})
    eng.observe({"type": "loss_burst", "ts": _ts(5), "loss_pct": 10.0})
    codes = _codes(eng.collect(NOW))
    assert "latency_without_loss" not in codes  # loss present → not jitter
    assert "loss_observed" in codes


def test_band_steering_info():
    eng = InsightEngine()
    for i in range(6):
        eng.observe({"type": "roam", "ts": _ts(i), "kind": "band_switch"})
    fired = [e for e in eng.collect(NOW) if e.code == "band_steering"]
    assert fired and fired[0].severity == "info"
    assert fired[0].detail["roams"] == 6 and fired[0].detail["band_switches"] == 6


def test_mostly_inter_ap_roams_do_not_band_steer():
    eng = InsightEngine()
    for i in range(6):
        eng.observe({"type": "roam", "ts": _ts(i), "kind": "inter_ap"})
    assert "band_steering" not in _codes(eng.collect(NOW))


# ---------- robustness ----------

def test_ignores_insight_payloads():
    eng = InsightEngine()
    # Feeding an insight (its own output) must not be treated as an arrival etc.
    eng.observe({"type": "insight", "code": "x", "severity": "warn", "ts": _ts(1)})
    assert eng.collect(NOW) == []


def test_never_raises_on_malformed():
    eng = InsightEngine()
    eng.observe(None)                       # not a dict
    eng.observe({})                         # no type / ts
    eng.observe({"type": "ble_device_seen"})  # no ts
    eng.observe({"type": "ble_device_seen", "ts": "not-a-date", "familiarity": "first_time"})
    assert eng.collect(NOW) == []


def test_loss_burst_with_unparseable_pct_does_not_raise():
    # A valid loss_burst with a bad loss_pct field is still a loss event —
    # it fires loss_observed (peak coerced to 0.0), and must not raise.
    eng = InsightEngine()
    eng.observe({"type": "loss_burst", "ts": _ts(1), "loss_pct": "nan"})
    fired = [e for e in eng.collect(NOW) if e.code == "loss_observed"]
    assert fired and fired[0].detail["peak_loss_pct"] == 0.0


def test_old_events_pruned():
    eng = InsightEngine(window_s=600)
    for i in range(3):
        eng.observe({"type": "link_state", "state": "disassociated", "ts": _ts(5)})
    # Collect far in the future — everything aged out.
    assert eng.collect(NOW + timedelta(seconds=10_000)) == []


# ---------- summary formatting ----------

def test_format_summary_localised_keys():
    assert "3" in format_insight_summary("new_device_cluster", {"count": 3})
    assert format_insight_summary("latency_without_loss", None)
    # Unknown code falls back to the code itself.
    assert format_insight_summary("totally_unknown", None) == "totally_unknown"
