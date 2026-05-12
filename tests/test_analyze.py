"""analyze.py — rule-based JSONL log reader tests.

Each heuristic gets one positive and (where it makes sense) one
negative test so adding new rules later doesn't break existing
trigger conditions.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from diting.analyze import (
    Insight,
    Report,
    analyze,
    parse_jsonl,
    render,
)


def _ev(type_: str, ts: str, **fields) -> dict:
    return {"type": type_, "ts": ts, **fields}


def _t(minute: int, second: int = 0) -> str:
    """Build an ISO-8601 UTC timestamp at 22:MM:SS.000Z so tests
    can write '_t(45)' for a stir event a minute later."""
    return f"2026-05-07T22:{minute:02d}:{second:02d}+00:00"


# ---------- parsing ----------

def test_parse_jsonl_skips_blank_and_garbage(tmp_path):
    """Hard-killed runs leave a partial trailing line; the parser
    must ignore garbage instead of erroring out the whole report."""
    path = tmp_path / "log.jsonl"
    path.write_text(
        '{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:00+00:00"}\n'
        "\n"  # blank
        '{"type":"rf_st  -- truncated\n'  # broken JSON
        "not json at all\n"
        '{"type":"rf_stir","ts":"2026-05-07T22:01:00+00:00","magnitude_db":3.5,"confidence":"medium","mode":"co_located"}\n'
    )
    events = parse_jsonl(path)
    assert len(events) == 2
    assert events[0]["type"] == "link_state"
    assert events[1]["type"] == "rf_stir"


def test_parse_jsonl_returns_empty_for_missing_file(tmp_path):
    assert parse_jsonl(tmp_path / "nope.jsonl") == []


# ---------- aggregate counts ----------

def test_analyze_counts_events_by_type():
    events = [
        _ev("link_state", _t(0), state="associated", bssid="aa:bb:cc:11:22:33", ssid="X"),
        _ev("rf_stir", _t(1), magnitude_db=3.5, mode="co_located", confidence="medium", location="L"),
        _ev("rf_stir", _t(2), magnitude_db=4.0, mode="co_located", confidence="medium", location="L"),
        _ev("latency_spike", _t(3), target="router", target_ip="1.1.1.1", rtt_ms=300, loss_pct=0),
    ]
    r = analyze(events)
    assert r.total_events == 4
    assert r.counts_by_type == {
        "link_state": 1, "rf_stir": 2, "latency_spike": 1,
    }
    assert r.stir_count == 2
    assert r.latency_spike_count == 1
    assert r.latency_spike_max_rtt == 300


def test_analyze_records_associations_and_roams():
    events = [
        _ev("link_state", _t(0), state="associated", bssid="aa:bb:cc:11:22:33", ssid="X"),
        _ev("roam", _t(1), kind="band_switch",
            previous_bssid="aa:bb:cc:11:22:33", new_bssid="aa:bb:cc:11:22:34",
            previous_channel=36, new_channel=1),
        _ev("roam", _t(2), kind="inter_ap",
            previous_bssid="aa:bb:cc:11:22:34", new_bssid="aa:bb:cc:99:88:77",
            previous_channel=1, new_channel=149),
    ]
    r = analyze(events)
    assert r.associations == [("X", "aa:bb:cc:11:22:33")]
    assert r.roams == 2
    assert r.band_switches == 1
    assert r.inter_ap_roams == 1


def test_analyze_stir_sigma_stats_use_real_values():
    events = [
        _ev("rf_stir", _t(1), magnitude_db=3.0, mode="co_located",
            confidence="medium", location="L"),
        _ev("rf_stir", _t(2), magnitude_db=4.0, mode="co_located",
            confidence="medium", location="L"),
        _ev("rf_stir", _t(3), magnitude_db=5.0, mode="co_located",
            confidence="medium", location="L"),
    ]
    r = analyze(events)
    assert r.stir_sigma_min == 3.0
    assert r.stir_sigma_max == 5.0
    assert r.stir_sigma_p50 == 4.0


# ---------- heuristics ----------

def _titles(insights: list[Insight]) -> set[str]:
    return {i.title for i in insights}


def test_empty_log_warns():
    r = analyze([])
    assert any(i.severity == "warn" for i in r.insights)


def test_timezone_mismatch_heuristic_triggers_on_hour_jump():
    """A naive datetime mislabelled as UTC produces an exact-hour
    gap between adjacent events. The heuristic catches this so the
    user knows their existing data is suspect."""
    events = [
        _ev("link_state", "2026-05-07T14:44:06+00:00",
            state="associated", bssid="aa:bb:cc:11:22:33", ssid="X"),
        _ev("rf_stir", "2026-05-07T22:44:07+00:00",
            magnitude_db=3.5, mode="co_located",
            confidence="medium", location="L"),
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert "Timezone" in titles or "时区" in titles


def test_timezone_mismatch_heuristic_quiet_on_normal_log():
    """Tightly-packed events from a clean run must NOT trigger
    the warning."""
    events = [
        _ev("rf_stir", _t(0, 0), magnitude_db=3.5, mode="co_located",
            confidence="medium", location="L"),
        _ev("rf_stir", _t(0, 30), magnitude_db=3.7, mode="co_located",
            confidence="medium", location="L"),
        _ev("rf_stir", _t(1, 5), magnitude_db=3.6, mode="co_located",
            confidence="medium", location="L"),
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert "Timezone" not in titles
    assert "时区" not in titles


def test_single_ap_medium_only_triggers_redundancy_hint():
    """The user's actual case: 5+ stir events all medium-conf on
    one location → the analyser surfaces the 'add a second AP for
    redundancy' hint."""
    events = [
        _ev("rf_stir", _t(i), magnitude_db=3.5 + 0.1 * i,
            mode="co_located", confidence="medium",
            location="AX51-E_3-2F")
        for i in range(6)
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert (
        "medium-confidence" in titles
        or "中等" in titles
    )


def test_single_ap_redundancy_hint_silent_with_high_confidence():
    """If at least one stir reached high confidence, redundancy
    is already working — no need for the 'add a second AP' hint."""
    events = [
        _ev("rf_stir", _t(i), magnitude_db=8.0,
            mode="co_located",
            confidence=("high" if i == 0 else "medium"),
            location="L")
        for i in range(6)
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert "medium-confidence" not in titles
    assert "中等置信" not in titles


def test_latency_without_loss_triggers_jitter_hint():
    events = [
        _ev("latency_spike", _t(1), target="router", target_ip="1.1.1.1",
            rtt_ms=400, loss_pct=0),
        _ev("latency_spike", _t(2), target="wan", target_ip="2.2.2.2",
            rtt_ms=550, loss_pct=0),
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert "without loss" in titles or "无丢包" in titles


def test_loss_burst_present_warns_real_loss():
    events = [
        _ev("loss_burst", _t(1), target="router", target_ip="1.1.1.1",
            loss_pct=80, lost_in_window=4),
    ]
    r = analyze(events)
    matched = [i for i in r.insights
               if "Real packet loss" in i.title or "真正" in i.title]
    assert matched
    assert matched[0].severity == "warn"


def test_repeated_disassociates_warns():
    events = [
        _ev("link_state", _t(i), state="disassociated",
            bssid=None, ssid=None)
        for i in range(4)
    ]
    r = analyze(events)
    matched = [i for i in r.insights
               if "disassociation" in i.title.lower()
               or "断开" in i.title]
    assert matched


def test_short_session_triggers_low_data_hint():
    """A log spanning < 10 min should surface the 'too little
    data' note so users don't over-interpret one-off readings."""
    events = [
        _ev("link_state", _t(0), state="associated",
            bssid="aa:bb:cc:11:22:33", ssid="X"),
        _ev("rf_stir", _t(2), magnitude_db=3.5, mode="co_located",
            confidence="medium", location="L"),
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert "Short" in titles or "短" in titles


def test_long_session_does_not_trigger_short_warning():
    events = [
        _ev("link_state", _t(0), state="associated",
            bssid="aa:bb:cc:11:22:33", ssid="X"),
        _ev("rf_stir", "2026-05-08T01:00:00+00:00", magnitude_db=3.5,
            mode="co_located", confidence="medium", location="L"),
    ]
    r = analyze(events)
    titles = " | ".join(_titles(r.insights))
    assert "Short" not in titles
    assert "短" not in titles


# ---------- render ----------

def test_render_includes_path_and_event_counts():
    events = [
        _ev("link_state", _t(0), state="associated",
            bssid="aa:bb:cc:11:22:33", ssid="tedo_5G"),
        _ev("rf_stir", _t(1), magnitude_db=3.5, mode="co_located",
            confidence="medium", location="L"),
    ]
    r = analyze(events, source_path="/tmp/x.jsonl")
    out = render(r)
    assert "/tmp/x.jsonl" in out
    assert "Total events" in out or "事件总数" in out or "事件" in out
    # We should see the summarised insight about short session.
    assert "[i]" in out or "[*]" in out or "[!]" in out


def test_render_handles_zero_events():
    """A truly empty log still produces a coherent report instead
    of crashing on missing time-range fields."""
    r = analyze([], source_path="/tmp/empty.jsonl")
    out = render(r)
    assert "/tmp/empty.jsonl" in out
    assert "[!]" in out  # the empty-log warning


def test_render_time_range_omits_end_date_when_same_day():
    """Single-day logs read cleaner without the date repeated on the
    end of the time range — `09:00 → 09:05` is enough context."""
    events = [
        _ev("link_state", "2026-05-07T09:00:00+00:00",
            state="associated", bssid="aa:bb:cc:11:22:33", ssid="x"),
        _ev("link_state", "2026-05-07T09:05:00+00:00",
            state="disassociated"),
    ]
    out = render(analyze(events, source_path="/tmp/x.jsonl"))
    # Find the Time range line (allow EN or ZH catalog).
    line = next(
        (l for l in out.splitlines()
         if "Time range" in l or "时间范围" in l),
        "",
    )
    assert line  # the row exists
    # Same day → end shown as bare HH:MM:SS, no second YYYY-MM-DD.
    # The arrow separator splits start (with date) from end (without).
    _, _, after = line.partition("→")
    assert "2026-05-" not in after


def test_render_time_range_includes_end_date_when_cross_day():
    """A log spanning past midnight previously rendered as
    `22:04:21 → 13:01:33 (14h 57m)` — the end's date is missing so
    the user has to do mental arithmetic against the duration to
    figure out what day '13:01:33' refers to. Now the end keeps its
    YYYY-MM-DD when it differs from the start.

    Uses a ≥ 25-hour span so the local dates differ in every
    timezone, keeping the assertion robust under any CI tz config.
    """
    events = [
        _ev("link_state", "2026-05-07T00:00:00+00:00",
            state="associated", bssid="aa:bb:cc:11:22:33", ssid="x"),
        _ev("link_state", "2026-05-08T02:00:00+00:00",
            state="disassociated"),
    ]
    out = render(analyze(events, source_path="/tmp/x.jsonl"))
    line = next(
        (l for l in out.splitlines()
         if "Time range" in l or "时间范围" in l),
        "",
    )
    assert line
    _, _, after = line.partition("→")
    import re
    assert re.search(r"\b2026-\d\d-\d\d\b", after), (
        f"expected YYYY-MM-DD in end portion, got: {after!r}"
    )