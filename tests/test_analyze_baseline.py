"""Baseline characterization test for `analyze`, run against a real
13 h overnight office capture (anonymized).

`tests/fixtures/analyze-baseline.jsonl` is a scrubbed copy of a real
diting capture (`scripts/scrub_capture.py`): every BSSID / SSID / IP /
MAC / device name / hostname is a stable handle, but vendors,
timestamps, dwell, familiarity, magnitudes, counts, and name/identifier
DISTINCTNESS are preserved — so the analyser sees the same structure as
the original log (verified: identical aggregates).

This pins `analyze` to a real-world-shaped input so continued iteration
on the analyser is checked against a known baseline rather than only
synthetic fixtures. When a deliberate change shifts these numbers,
update the asserted values in the same PR — the diff is the record of
what the change did to a real log.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from diting.analyze import analyze, parse_jsonl

_FIXTURE = Path(__file__).parent / "fixtures" / "analyze-baseline.jsonl"


@pytest.fixture(scope="module")
def report():
    return analyze(parse_jsonl(_FIXTURE), source_path=str(_FIXTURE))


def test_fixture_carries_no_obvious_pii():
    """Guard the asset itself: the committed baseline must stay scrubbed.
    A real BSSID / employer SSID / personal device name slipping back in
    is a privacy regression, not just a test failure."""
    text = _FIXTURE.read_text("utf-8")
    for needle in (
        "Meituan", "Chaoyi", "ccy", "Magic Keyboard", "Trackpad",
        "AirPods", "MBP2024", "a8:5b:f7", "11.10.",
    ):
        assert needle not in text, f"PII leaked into the fixture: {needle!r}"


def test_baseline_scope_and_counts(report):
    assert report.total_events == 4442
    assert report.counts_by_type["ble_device_seen"] == 2224
    assert report.counts_by_type["ble_device_left"] == 2203
    assert report.counts_by_type["loss_burst"] == 5
    # 13 h span → the long-span gate fires, temporal analysis enabled.
    assert report.hourly_rhythms


def test_baseline_population_by_stable_identity(report):
    """79 distinct PHYSICAL devices — NOT the ~2200 rotating identifiers.
    This is the headline guard: a regression to identifier-keyed counting
    would blow this number up by ~28×."""
    pop = report.ble_population
    assert pop.distinct_devices == 79
    assert pop.residents == 7
    assert pop.passersby == 57
    assert pop.unkeyable_sightings == 135


def test_baseline_dwell_is_high_transient(report):
    dw = report.ble_dwell
    assert dw.n == 2203
    assert dw.p50_s == pytest.approx(9.4, abs=0.5)
    assert dw.transient == 1675       # 76% under 2 min
    assert dw.resident == 8


def test_baseline_arrival_rhythm(report):
    rh = report.hourly_rhythms["ble_device_seen"]
    assert rh.peak_hour == 20         # evening peak
    assert rh.quiet_hour == 0         # overnight floor


def test_baseline_insights_present(report):
    titles = {i.title for i in report.insights}
    assert "BLE arrival rhythm" in titles
    assert "BLE dwell — foot-traffic vs residents" in titles
    assert "Device population" in titles
    # The morning loss bursts coincide with the busy arrival hours.
    assert "Signals coinciding in time" in titles
    co = next(i for i in report.insights if i.title == "Signals coinciding in time")
    assert "hypothesis, not a cause" in co.detail


def test_baseline_loss_warning_still_fires(report):
    # The pre-existing health heuristic must keep firing on real loss.
    assert any(i.title == "Real packet loss observed" for i in report.insights)
