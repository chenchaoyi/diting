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
    build_llm_prompt,
    parse_jsonl,
    render,
    render_markdown,
    scene_summary,
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


# ------------------------------------------------------------------
# A2: long-timeline cross-session aggregators
# ------------------------------------------------------------------

from diting.analyze import (  # noqa: E402
    aggregate_daily_trend,
    aggregate_day_of_week_x_hour,
    aggregate_hour_of_day,
    aggregate_per_network,
    aggregate_top_contributors,
    filter_since,
    parse_since,
)


def _ev_a2(ts: str, type_: str, **extra) -> dict:
    return {"ts": ts, "type": type_, **extra}


def test_since_filter_parses_30d_24h_15m_etc():
    assert parse_since("30d") == timedelta(days=30)
    assert parse_since("7d") == timedelta(days=7)
    assert parse_since("24h") == timedelta(hours=24)
    assert parse_since("90m") == timedelta(minutes=90)
    assert parse_since("60s") == timedelta(seconds=60)


def test_since_filter_rejects_invalid_format():
    for bad in ("", "last week", "30days", "30D", "1.5h", "12 h"):
        with pytest.raises(ValueError):
            parse_since(bad)


def test_filter_since_drops_events_outside_window():
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev_a2("2026-05-21T11:30:00+00:00", "roam"),
        _ev_a2("2026-05-21T11:50:00+00:00", "rf_stir"),
        _ev_a2("2026-05-20T11:30:00+00:00", "roam"),  # outside 1h window
    ]
    out = filter_since(events, timedelta(hours=1), now=now)
    assert len(out) == 2


def test_aggregate_hour_of_day_buckets_events_into_24_slots():
    events = [
        _ev_a2("2026-05-21T09:30:00+08:00", "roam"),
        _ev_a2("2026-05-21T09:45:00+08:00", "roam"),
        _ev_a2("2026-05-21T15:00:00+08:00", "lan_host_seen", mac="aa"),
    ]
    buckets = aggregate_hour_of_day(events)
    assert len(buckets) == 24
    assert sum(buckets[9].values()) == 2


def test_aggregate_hour_of_day_carries_type_breakdown():
    events = [
        _ev_a2("2026-05-21T12:00:00+08:00", "lan_host_seen", mac="aa"),
        _ev_a2("2026-05-21T12:00:00+08:00", "lan_host_seen", mac="bb"),
        _ev_a2("2026-05-21T12:00:00+08:00", "roam"),
    ]
    buckets = aggregate_hour_of_day(events)
    h12 = buckets[12]
    assert h12.get("lan_host_seen") == 2
    assert h12.get("roam") == 1


def test_aggregate_day_of_week_x_hour_returns_7x24_grid():
    events = [
        _ev_a2("2026-05-19T09:30:00+08:00", "roam"),  # Tuesday
        _ev_a2("2026-05-19T15:00:00+08:00", "rf_stir"),
        _ev_a2("2026-05-20T14:00:00+08:00", "roam"),  # Wednesday
    ]
    grid = aggregate_day_of_week_x_hour(events)
    assert len(grid) == 7
    assert all(len(row) == 24 for row in grid)
    assert grid[1][9] == 1
    assert grid[2][14] == 1


def test_aggregate_per_network_groups_by_associated_bssid():
    events = [
        _ev_a2("2026-05-21T09:00:00+08:00", "connection_update",
            state="associated", bssid="aa:aa:aa:11:22:33", ssid="Home"),
        _ev_a2("2026-05-21T09:30:00+08:00", "rf_stir",
            bssid="aa:aa:aa:11:22:33", magnitude_db=8.0),
        _ev_a2("2026-05-21T09:45:00+08:00", "ble_device_seen", identifier="x"),
        _ev_a2("2026-05-21T10:00:00+08:00", "connection_update",
            state="associated", bssid="bb:bb:bb:11:22:33", ssid="Cafe"),
        _ev_a2("2026-05-21T10:30:00+08:00", "rf_stir",
            bssid="bb:bb:bb:11:22:33", magnitude_db=5.0),
    ]
    nets = aggregate_per_network(events)
    labels = [n.network_label for n in nets]
    assert any("Home" in lbl for lbl in labels)
    assert any("Cafe" in lbl for lbl in labels)


def test_aggregate_per_network_attributes_orphan_events_to_unknown():
    events = [
        _ev_a2("2026-05-21T09:30:00+08:00", "ble_device_seen", identifier="x"),
    ]
    nets = aggregate_per_network(events)
    assert any(n.network_label == "(unknown network)" for n in nets)


def test_aggregate_daily_trend_yields_per_day_counts():
    events = [
        _ev_a2("2026-05-19T09:00:00+08:00", "roam"),
        _ev_a2("2026-05-19T10:00:00+08:00", "roam"),
        _ev_a2("2026-05-20T09:00:00+08:00", "roam"),
        _ev_a2("2026-05-21T09:00:00+08:00", "roam"),
    ]
    daily = aggregate_daily_trend(events)
    by_date = {d.date: d.total for d in daily}
    assert by_date.get("2026-05-19") == 2
    assert by_date.get("2026-05-20") == 1
    assert by_date.get("2026-05-21") == 1


def test_aggregate_daily_trend_includes_rolling_avg():
    events = [
        _ev_a2(f"2026-05-{day:02d}T09:00:00+08:00", "roam")
        for day in range(15, 22)  # 7 days, 1 event each
    ]
    daily = aggregate_daily_trend(events)
    assert daily[-1].rolling_7d_avg == pytest.approx(1.0, abs=0.01)


def test_top_contributors_ranks_bssids_by_roam_plus_stir():
    events = [
        _ev_a2("2026-05-21T09:00:00+08:00", "roam", new_bssid="aa:11:22:33:44:55"),
        _ev_a2("2026-05-21T09:05:00+08:00", "roam", new_bssid="aa:11:22:33:44:55"),
        _ev_a2("2026-05-21T09:10:00+08:00", "roam", new_bssid="aa:11:22:33:44:55"),
        _ev_a2("2026-05-21T09:15:00+08:00", "rf_stir", bssid="aa:11:22:33:44:55"),
        _ev_a2("2026-05-21T09:20:00+08:00", "roam", new_bssid="bb:11:22:33:44:55"),
    ]
    top = aggregate_top_contributors(events)
    assert len(top.bssids) >= 2
    assert top.bssids[0].bssid == "aa:11:22:33:44:55"
    assert top.bssids[0].roam_count == 3
    assert top.bssids[0].stir_count == 1


def test_top_contributors_ranks_ble_identifiers_by_seen_count():
    events = [
        _ev_a2("2026-05-21T09:00:00+08:00", "ble_device_seen", identifier="abc",
            name="Magic Keyboard", vendor="Apple, Inc."),
        _ev_a2("2026-05-21T09:05:00+08:00", "ble_device_seen", identifier="abc"),
        _ev_a2("2026-05-21T09:10:00+08:00", "ble_device_seen", identifier="def",
            name="AirPods Pro", vendor="Apple, Inc."),
    ]
    top = aggregate_top_contributors(events)
    assert top.ble_identifiers[0].identifier == "abc"
    assert top.ble_identifiers[0].seen_count == 2


def test_top_contributors_ranks_lan_hosts_by_dhcp_rotation_count():
    events = [
        _ev_a2("2026-05-21T09:00:00+08:00", "lan_host_dhcp_rotation",
            mac="de:ad:be:ef:00:01", previous_ip="192.168.1.42",
            new_ip="192.168.1.77", vendor="Apple, Inc.",
            bonjour_name="my-mac"),
        _ev_a2("2026-05-21T09:30:00+08:00", "lan_host_dhcp_rotation",
            mac="de:ad:be:ef:00:01", previous_ip="192.168.1.77",
            new_ip="192.168.1.99"),
        _ev_a2("2026-05-21T09:45:00+08:00", "lan_host_dhcp_rotation",
            mac="aa:bb:cc:dd:ee:ff", previous_ip="192.168.1.10",
            new_ip="192.168.1.20"),
    ]
    top = aggregate_top_contributors(events)
    assert top.lan_hosts[0].mac == "de:ad:be:ef:00:01"
    assert top.lan_hosts[0].rotation_count == 2


def test_glob_expansion_via_multiple_paths_aggregates_into_single_report():
    from diting.analyze import analyze
    events = [
        _ev_a2("2026-05-19T09:00:00+08:00", "roam"),
        _ev_a2("2026-05-20T09:00:00+08:00", "roam"),
        _ev_a2("2026-05-21T09:00:00+08:00", "roam"),
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    assert len(report.source_paths) == 2
    assert report.total_events == 3
    assert sum(sum(b.values()) for b in report.hour_of_day.values()) == 3
    assert any(any(row) for row in report.day_of_week_x_hour)


def test_single_file_no_since_preserves_existing_layout():
    from diting.analyze import analyze, render
    events = [_ev_a2("2026-05-21T09:00:00+08:00", "roam")]
    report = analyze(events, source_path="single.jsonl")
    assert report.hour_of_day == {}
    assert report.day_of_week_x_hour == ()
    assert report.per_network == ()
    assert report.daily_trend == ()
    assert report.top_contributors is None
    rendered = render(report)
    assert "Scope:" not in rendered
    assert "Events by hour-of-day" not in rendered


def test_multi_file_or_since_appends_cross_session_blocks():
    from diting.analyze import analyze, render
    events = [
        _ev_a2("2026-05-20T09:00:00+08:00", "roam"),
        _ev_a2("2026-05-21T09:00:00+08:00", "roam"),
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    rendered = render(report)
    assert "Scope:" in rendered
    assert "Events by hour-of-day" in rendered

    report2 = analyze(events, source_path="a.jsonl", since=timedelta(days=7))
    rendered2 = render(report2)
    assert "Scope:" in rendered2
    assert "Events by hour-of-day" in rendered2


def test_scope_header_renders_single_file_no_since():
    from diting.analyze import analyze, render
    events = [_ev_a2("2026-05-21T09:00:00+08:00", "roam")]
    report = analyze(events, source_path="single.jsonl")
    assert "Scope:" not in render(report)


def test_scope_header_renders_multi_file_with_since():
    from diting.analyze import analyze, render
    events = [
        _ev_a2("2026-05-19T09:00:00+08:00", "roam"),
        _ev_a2("2026-05-21T09:00:00+08:00", "roam"),
    ]
    report = analyze(
        events,
        source_paths=["a.jsonl", "b.jsonl"],
        since=timedelta(days=30),
    )
    rendered = render(report)
    assert "Scope:" in rendered
    assert "2 files" in rendered


def test_render_day_x_hour_heatmap_normalises_to_block_chars():
    from diting.analyze import analyze, render
    events = [_ev_a2("2026-05-21T09:00:00+08:00", "roam") for _ in range(5)]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    rendered = render(report)
    # The heaviest cell renders as `█` or similar block.
    assert any(c in rendered for c in "▁▂▃▄▅▆▇█")


def test_render_daily_trend_emits_one_sparkline_per_family():
    from diting.analyze import analyze, render
    events = [
        _ev_a2(f"2026-05-{day:02d}T09:00:00+08:00", "roam")
        for day in range(15, 22)
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    rendered = render(report)
    assert "Daily trend" in rendered

# ------------------------------------------------------------------
# Track B: LLM-bridge export — anonymizer + markdown + prompt
# ------------------------------------------------------------------

from diting.analyze import (  # noqa: E402
    Anonymizer,
    _is_rfc1918,
    build_llm_prompt,
    render_markdown,
)


def test_is_rfc1918_recognises_private_ranges():
    assert _is_rfc1918("192.168.1.42") is True
    assert _is_rfc1918("10.0.0.1") is True
    assert _is_rfc1918("172.16.5.5") is True
    assert _is_rfc1918("172.31.255.255") is True
    assert _is_rfc1918("172.15.0.1") is False
    assert _is_rfc1918("172.32.0.1") is False
    assert _is_rfc1918("8.8.8.8") is False
    assert _is_rfc1918("1.1.1.1") is False
    assert _is_rfc1918("") is False


def test_anonymizer_assigns_stable_handles():
    a = Anonymizer()
    assert a.map("ssid", "home-5G") == "SSID_1"
    assert a.map("ssid", "Meituan") == "SSID_2"
    assert a.map("bssid", "aa:bb:cc:11:22:33") == "AP_1"
    assert a.map("bssid", "aa:bb:cc:99:88:77") == "AP_2"
    assert a.map("ble", "abc-def") == "BLE_1"
    assert a.map("mac", "de:ad:be:ef:00:01") == "MAC_1"
    assert a.map("host", "my-mac.local") == "HOST_1"


def test_anonymizer_same_value_returns_same_handle():
    a = Anonymizer()
    h1 = a.map("ssid", "Meituan")
    h2 = a.map("ssid", "Meituan")
    h3 = a.map("ssid", "Meituan")
    assert h1 == h2 == h3 == "SSID_1"


def test_anonymizer_preserves_public_ip_addresses():
    a = Anonymizer()
    assert a.map("ip", "8.8.8.8") == "8.8.8.8"
    assert a.map("ip", "1.1.1.1") == "1.1.1.1"
    assert a.map("ip", "114.114.114.114") == "114.114.114.114"


def test_anonymizer_replaces_rfc1918_addresses():
    a = Anonymizer()
    assert a.map("ip", "192.168.1.42") == "IP_1"
    assert a.map("ip", "10.0.0.5") == "IP_2"
    assert a.map("ip", "172.16.1.1") == "IP_3"


def test_anonymizer_passes_through_vendor_names():
    a = Anonymizer()
    assert a.map("vendor", "Apple, Inc.") == "Apple, Inc."
    assert a.map("category", "AirPlay") == "AirPlay"


def test_anonymizer_handles_none_and_empty():
    a = Anonymizer()
    assert a.map("ssid", None) is None
    assert a.map("ssid", "") == ""


def test_anonymizer_mapping_lists_in_kind_then_index_order():
    a = Anonymizer()
    a.map("bssid", "aa:bb:cc:11:22:33")
    a.map("ssid", "home")
    a.map("ssid", "office")
    a.map("bssid", "aa:bb:cc:44:55:66")
    mapping = a.mapping()
    handles = [h for h, _ in mapping]
    assert "AP_1" in handles
    assert "AP_2" in handles
    assert "SSID_1" in handles
    assert "SSID_2" in handles


def _ev_b(day: int, hour: int = 9, type_: str = "roam", **extra) -> dict:
    ts = f"2026-05-{day:02d}T{hour:02d}:00:00+08:00"
    return {"ts": ts, "type": type_, **extra}


def test_render_markdown_includes_glossary():
    events = [_ev_b(20), _ev_b(21)]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    md = render_markdown(report)
    assert "## Glossary" in md
    assert "rf_stir" in md
    assert "lan_host_seen" in md


def test_render_markdown_wraps_ascii_in_fenced_blocks():
    events = [_ev_b(20), _ev_b(21)]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    md = render_markdown(report)
    assert "```text" in md


def test_render_markdown_renders_per_network_as_table():
    events = [
        _ev_b(20, type_="link_state", state="associated",
              bssid="aa:bb:cc:11:22:33", ssid="Meituan"),
        _ev_b(20, type_="roam", new_bssid="aa:bb:cc:11:22:33"),
        _ev_b(20, type_="roam", new_bssid="aa:bb:cc:11:22:33"),
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    md = render_markdown(report)
    assert "## Top networks by event volume" in md
    assert "| Network | Events | Breakdown |" in md


def test_render_markdown_anonymization_section_is_placeholder():
    a = Anonymizer()
    events = [
        _ev_b(20, type_="link_state", state="associated",
              bssid="aa:bb:cc:11:22:33", ssid="uniqueSSID42"),
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    md = render_markdown(report, anonymizer=a)
    assert "## Anonymization" in md
    assert "uniqueSSID42" not in md.split("## Anonymization")[1]


def test_render_markdown_without_anonymizer_keeps_identifiers():
    events = [
        _ev_b(20, type_="link_state", state="associated",
              bssid="aa:bb:cc:11:22:33", ssid="home-5G"),
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    md = render_markdown(report)
    assert "## Anonymization" not in md


def test_render_markdown_with_anonymize_replaces_identifiers():
    a = Anonymizer()
    events = [
        _ev_b(20, type_="link_state", state="associated",
              bssid="aa:bb:cc:11:22:33", ssid="uniqueSSID42"),
        _ev_b(20, type_="roam", new_bssid="aa:bb:cc:11:22:33"),
        _ev_b(20, type_="ble_device_seen", identifier="xyz",
              vendor="Apple, Inc.", name="Magic Keyboard"),
    ]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    md = render_markdown(report, anonymizer=a)
    assert "uniqueSSID42" not in md
    assert "aa:bb:cc:11:22:33" not in md
    # At least one handle appears in the body.
    assert "SSID_" in md or "AP_" in md or "BLE_" in md


def test_build_llm_prompt_includes_all_five_sections():
    events = [_ev_b(20), _ev_b(21)]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    prompt = build_llm_prompt(report)
    assert "diting" in prompt
    assert "analyst" in prompt
    for n in ("1.", "2.", "3.", "4.", "5."):
        assert n in prompt
    assert "markdown" in prompt.lower()
    assert "speculate" in prompt.lower() or "hypothesis" in prompt.lower()
    assert "Anonymization" in prompt or "handles" in prompt.lower()


def test_build_llm_prompt_substitutes_span_and_files():
    events = [_ev_b(20), _ev_b(21)]
    report = analyze(events, source_paths=["a.jsonl", "b.jsonl"])
    prompt = build_llm_prompt(report)
    assert "2026-05-20" in prompt
    assert "2026-05-21" in prompt
    assert "2 session" in prompt


# ------------------------------------------------------------------
# session_meta consumption + scene context
# ------------------------------------------------------------------

def _ev_sm(scene: str, source: str = "cli", ts_iso: str = "2026-05-22T13:00:00+08:00") -> dict:
    """Build a session_meta event dict the way the JSONL reader sees one."""
    return {
        "type": "session_meta",
        "ts": ts_iso,
        "scene": scene,
        "scene_source": source,
        "diting_version": "1.6.0",
        "ssid": "TestNet",
        "gateway_ip": "192.168.1.1",
        "hostname": "test-host",
    }


def test_analyze_collects_scene_from_session_meta():
    """A JSONL containing a session_meta line populates Report.scenes
    and Report.scene_sources."""
    events = [
        _ev_sm("office", "cli"),
        _ev_b(20),
    ]
    report = analyze(events)
    assert report.scenes == ("office",)
    assert report.scene_sources == {"office": "cli"}


def test_analyze_multi_scene_mix_recorded_in_order_seen():
    """Three session_meta lines (one per file in a glob) populate
    Report.scenes with all three names; scene_summary then folds
    them into a count-descending string."""
    events = [
        _ev_sm("home", "default"),
        _ev_sm("home", "default"),
        _ev_sm("office", "cli"),
    ]
    report = analyze(events)
    assert sorted(report.scenes) == ["home", "home", "office"]
    summary = scene_summary(report)
    assert "2 × home" in summary
    assert "1 × office" in summary


def test_analyze_missing_session_meta_leaves_scenes_empty():
    """Pre-scene-aware JSONL has no session_meta line. Report.scenes
    is an empty tuple; scene_summary surfaces the gap explicitly."""
    events = [_ev_b(20)]
    report = analyze(events)
    assert report.scenes == ()
    assert "unknown" in scene_summary(report)
    assert "pre-scene" in scene_summary(report)


def test_scene_summary_single_scene_names_source():
    """`home (cli)` style — gives the LLM context about whether the
    scene was the user's deliberate choice or a default fallback."""
    events = [_ev_sm("home", "env")]
    report = analyze(events)
    assert scene_summary(report) == "home (env)"


def test_scene_summary_source_promotion_uses_strongest():
    """If the same scene appears with multiple sources across the
    input, the most-specific source wins (cli > env > default)."""
    events = [
        _ev_sm("office", "default"),
        _ev_sm("office", "cli"),
        _ev_sm("office", "env"),
    ]
    report = analyze(events)
    # cli is the strongest of the three sources observed.
    assert "(cli)" in scene_summary(report)


def test_render_markdown_includes_scene_line():
    """The Markdown report header surfaces the scene immediately
    after the title."""
    events = [_ev_sm("office", "cli"), _ev_b(20)]
    report = analyze(events)
    md = render_markdown(report)
    assert "**Scene:** office (cli)" in md


def test_render_markdown_pre_scene_aware_shows_unknown():
    events = [_ev_b(20)]
    report = analyze(events)
    md = render_markdown(report)
    assert "**Scene:** unknown" in md
    assert "pre-scene-aware capture" in md


def test_build_llm_prompt_starts_with_scene_context():
    """`[Scene context]` is the first paragraph the LLM sees — the
    role / tasks / output-format sections come after."""
    events = [_ev_sm("office", "cli"), _ev_b(20)]
    report = analyze(events)
    prompt = build_llm_prompt(report)
    assert prompt.startswith("[Scene context]")
    assert "office" in prompt.split("\n\n", 1)[0]
    assert "departures from this baseline" in prompt


def test_build_llm_prompt_includes_observed_counts_when_available():
    """The scene-context paragraph backfills with concrete numbers
    so the LLM can calibrate (e.g. `observed BSSID count 1`)."""
    events = [
        _ev_sm("office", "cli"),
        {"type": "roam", "ts": "2026-05-22T13:00:00+08:00",
         "from_bssid": "aa:bb:cc:11:22:33",
         "to_bssid": "aa:bb:cc:11:22:44",
         "bssid": "aa:bb:cc:11:22:44",
         "ssid": "X", "kind": "inter_ap"},
    ]
    report = analyze(events)
    prompt = build_llm_prompt(report)
    assert "BSSID count" in prompt


def test_build_llm_prompt_multi_scene_acknowledges_mix():
    events = [
        _ev_sm("home", "default"),
        _ev_sm("office", "cli"),
        _ev_b(20),
    ]
    report = analyze(events)
    prompt = build_llm_prompt(report)
    # Multi-scene prompt explicitly tells the LLM to compare across.
    assert "multiple scenes" in prompt
    assert "Compare across" in prompt


def test_build_llm_prompt_pre_scene_aware_falls_back_to_general_priors():
    events = [_ev_b(20)]
    report = analyze(events)
    prompt = build_llm_prompt(report)
    assert prompt.startswith("[Scene context]")
    assert "pre-scene-aware capture" in prompt
    assert "general priors" in prompt
