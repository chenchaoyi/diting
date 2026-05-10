"""Tests for the EnvironmentMonitor RF-stir detector + calibration I/O.

We seed RSSI traces with explicit timestamps (``datetime`` arithmetic
on a fixed anchor) so the rolling-window math is deterministic and
the assertions reference exact thresholds rather than approximations.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from diting.environment import (
    DEFAULT_BASELINE_WINDOW_S,
    EnvironmentMonitor,
    load_calibration,
    write_calibration,
)
from diting.network import APEntry, NetworkInventory


_INV = NetworkInventory(
    aps=(
        APEntry(name="1F-living", mgmt_mac="aa:bb:cc:11:22:0f"),
        APEntry(name="1F-bedroom", mgmt_mac="aa:bb:cc:11:22:1f"),
        APEntry(name="2F-study", mgmt_mac="aa:bb:cc:33:44:0f"),
    ),
)


def _now() -> datetime:
    return datetime(2026, 5, 7, 9, 0, 0)


def _seed(monitor: EnvironmentMonitor, bssid: str, samples, *, t0=None):
    """Push a list of ``(seconds_offset, rssi)`` samples into the monitor."""
    base = t0 or _now()
    for offset, rssi in samples:
        monitor.ingest(bssid, rssi, base + timedelta(seconds=offset))


def test_sigma_above_threshold_fires_event():
    """A noisy 5 s window of an otherwise quiet AP fires an
    rf_stir event with a magnitude in the 5-15 dB band."""
    monitor = EnvironmentMonitor(
        inventory=_INV, cooldown_s=0.0,
    )
    bssid = "aa:bb:cc:11:22:10"  # 1F-living radio
    base = _now()
    # Seed 5 minutes of stable -55 dBm baseline (small jitter only).
    quiet = []
    for i in range(60):
        quiet.append((i * 5, -55 + ((i * 7) % 3 - 1)))
    _seed(monitor, bssid, quiet)
    # Now a 5-second burst of -45..-65 dBm: σ around 8 dB.
    burst_start = quiet[-1][0] + 5
    burst = [
        (burst_start + 0, -45),
        (burst_start + 1, -65),
        (burst_start + 2, -47),
        (burst_start + 3, -63),
        (burst_start + 4, -50),
    ]
    _seed(monitor, bssid, burst)
    fire_at = base + timedelta(seconds=burst_start + 4)
    events = monitor.fire_events(fire_at)
    assert len(events) == 1
    ev = events[0]
    assert ev.bssid == bssid
    assert ev.location == "1F-living"
    assert ev.magnitude_db >= 5.0
    assert ev.confidence in {"medium", "high"}


def test_sigma_below_threshold_no_event():
    """A flat -60 dBm trace stays quiet — no rf_stir."""
    monitor = EnvironmentMonitor(inventory=_INV)
    bssid = "aa:bb:cc:11:22:10"
    base = _now()
    flat = [(i * 1, -60) for i in range(30)]
    _seed(monitor, bssid, flat, t0=base)
    events = monitor.fire_events(base + timedelta(seconds=29))
    assert events == []


def test_co_located_vs_spatial_channel_classification():
    """RSSI determines the bucket. -55 dBm AP → co_located,
    -75 dBm AP → spatial_channel, -90 dBm AP → ignored."""
    monitor = EnvironmentMonitor(inventory=_INV)
    base = _now()
    monitor.ingest("aa:bb:cc:11:22:10", -55, base)
    monitor.ingest("aa:bb:cc:11:22:20", -75, base)
    monitor.ingest("aa:bb:cc:11:22:30", -90, base)
    summary = monitor.baseline_summary()
    by_bssid = {b.bssid: b.mode for b in summary}
    assert by_bssid["aa:bb:cc:11:22:10"] == "co_located"
    assert by_bssid["aa:bb:cc:11:22:20"] == "spatial_channel"
    assert by_bssid["aa:bb:cc:11:22:30"] == "ignored"


def test_redundancy_fusion_makes_two_co_located_events_high_confidence():
    """When two co-located APs both spike inside the same fire pass,
    every co_located event in that group is upgraded to high
    confidence. A single-AP spike stays medium."""
    monitor = EnvironmentMonitor(inventory=_INV, cooldown_s=0.0)
    base = _now()
    bssids = ["aa:bb:cc:11:22:10", "aa:bb:cc:11:22:20"]
    # Both APs see strong signal so they classify as co_located.
    quiet = [(i * 2, -50 + (i % 3 - 1)) for i in range(60)]
    for b in bssids:
        _seed(monitor, b, quiet, t0=base)
        burst_start = quiet[-1][0] + 2
        burst = [
            (burst_start + 0, -40),
            (burst_start + 1, -60),
            (burst_start + 2, -42),
            (burst_start + 3, -58),
            (burst_start + 4, -45),
        ]
        _seed(monitor, b, burst, t0=base)
    fire_at = base + timedelta(seconds=quiet[-1][0] + 6)
    events = monitor.fire_events(fire_at)
    assert len(events) == 2
    assert all(e.mode == "co_located" for e in events)
    assert all(e.confidence == "high" for e in events)


def test_single_co_located_event_is_medium_confidence():
    """A spike on exactly one co-located AP can't be cross-validated
    by a second AP in the same room → medium confidence."""
    monitor = EnvironmentMonitor(inventory=_INV, cooldown_s=0.0)
    base = _now()
    bssid = "aa:bb:cc:11:22:10"
    quiet = [(i * 2, -55 + (i % 3 - 1)) for i in range(60)]
    burst = [
        (quiet[-1][0] + 2 + j, v)
        for j, v in enumerate([-45, -65, -47, -63, -50])
    ]
    _seed(monitor, bssid, quiet + burst, t0=base)
    fire_at = base + timedelta(seconds=quiet[-1][0] + 6)
    events = monitor.fire_events(fire_at)
    assert len(events) == 1
    assert events[0].confidence == "medium"


def test_spatial_channel_event_uses_ap_location_label():
    """A weak (-75 dBm) AP's spike fires a spatial-channel event
    labelled with that AP's inventory name. This is the spec's
    'motion in 2F-书房' example."""
    monitor = EnvironmentMonitor(inventory=_INV, cooldown_s=0.0)
    base = _now()
    bssid = "aa:bb:cc:33:44:10"  # 2F-study
    quiet = [(i, -75 + (i % 3 - 1)) for i in range(60)]
    burst = [
        (quiet[-1][0] + 2 + j, v)
        for j, v in enumerate([-65, -85, -67, -83, -70])
    ]
    _seed(monitor, bssid, quiet + burst, t0=base)
    fire_at = base + timedelta(seconds=quiet[-1][0] + 6)
    events = monitor.fire_events(fire_at)
    assert len(events) == 1
    assert events[0].mode == "spatial_channel"
    assert events[0].location == "2F-study"


def test_calibration_overrides_adaptive_baseline():
    """When calibration declares the 'empty room' σ, that value is
    used in place of the rolling-median computation. A 4× spike over
    the calibrated σ triggers; a noisy adaptive baseline that would
    otherwise mask the spike no longer applies."""
    bssid = "aa:bb:cc:11:22:10"
    cal = {bssid: {"rssi_mean": -55, "rssi_stddev": 1.0, "sample_count": 200}}
    monitor = EnvironmentMonitor(
        inventory=_INV, calibration=cal, cooldown_s=0.0,
    )
    base = _now()
    # Six chunks of *very* noisy 8 dB σ — enough that the adaptive
    # baseline would itself be ~8 and the spike ratio of 2.5 would
    # not catch it. Calibration short-circuits that.
    samples = []
    for i in range(60):
        samples.append((i, -55 + (-1) ** i * 8))  # alternating
    _seed(monitor, bssid, samples, t0=base)
    fire_at = base + timedelta(seconds=59)
    events = monitor.fire_events(fire_at)
    # The σ over the spike window will be > 2.5 × calibrated 1.0 =
    # 2.5 dB AND > spike_min_db (3 dB), so we should fire.
    assert len(events) == 1


def test_baseline_summary_shape():
    """Sanity: APBaseline rows expose every diagnostic the modal needs."""
    monitor = EnvironmentMonitor(inventory=_INV)
    base = _now()
    bssid = "aa:bb:cc:11:22:10"
    _seed(monitor, bssid, [(i, -55 + i % 3) for i in range(20)], t0=base)
    summary = monitor.baseline_summary()
    assert summary
    row = summary[0]
    assert row.bssid == bssid
    assert row.location == "1F-living"
    assert row.mode in {"co_located", "spatial_channel", "ignored"}
    assert row.samples == 20
    assert row.last_rssi is not None


def test_aps_below_minus_85_excluded():
    """APs with a median RSSI worse than -85 are classified
    'ignored' and never fire events even when their σ would qualify.
    Verifies the noise-floor drop the spec mandates."""
    monitor = EnvironmentMonitor(inventory=_INV, cooldown_s=0.0)
    base = _now()
    bssid = "aa:bb:cc:11:22:10"
    samples = [(i, -90 + (-1) ** i * 10) for i in range(40)]
    _seed(monitor, bssid, samples, t0=base)
    fire_at = base + timedelta(seconds=39)
    events = monitor.fire_events(fire_at)
    assert events == []


def test_aggregate_sigma_label_active_when_above_floor():
    """The aggregate label is 'active' when at least one AP shows σ
    above the absolute floor. This is what the Diagnostics
    Environment line surfaces."""
    monitor = EnvironmentMonitor(inventory=_INV, cooldown_s=0.0)
    base = _now()
    bssid = "aa:bb:cc:11:22:10"
    samples = [(i, -55 + (-1) ** i * 10) for i in range(20)]
    _seed(monitor, bssid, samples, t0=base)
    label, sigma, _ = monitor.aggregate_sigma(base + timedelta(seconds=19))
    assert label == "active"
    assert sigma is not None and sigma >= 3.0


def test_aggregate_sigma_label_quiet_with_calibration():
    """With calibration in play and a flat trace, the label is
    'quiet' (not 'stable')."""
    bssid = "aa:bb:cc:11:22:10"
    cal = {bssid: {"rssi_mean": -55, "rssi_stddev": 1.0, "sample_count": 200}}
    monitor = EnvironmentMonitor(inventory=_INV, calibration=cal)
    base = _now()
    flat = [(i, -55) for i in range(20)]
    _seed(monitor, bssid, flat, t0=base)
    label, _, _ = monitor.aggregate_sigma(base + timedelta(seconds=19))
    assert label == "quiet"


def test_calibration_round_trip(tmp_path):
    """write_calibration writes a JSON file load_calibration round-
    trips into a usable mapping."""
    p = tmp_path / "diting-baseline.json"
    samples = {
        "aa:bb:cc:11:22:10": [-55, -54, -56, -55, -53],
        "aa:bb:cc:11:22:20": [-72, -73, -71, -72, -74],
    }
    written = write_calibration(samples, p)
    assert written == p
    loaded = load_calibration(p)
    assert "aa:bb:cc:11:22:10" in loaded
    assert loaded["aa:bb:cc:11:22:10"]["sample_count"] == 5
    assert "rssi_stddev" in loaded["aa:bb:cc:11:22:10"]


def test_load_calibration_returns_empty_dict_on_missing_file(tmp_path):
    assert load_calibration(tmp_path / "does-not-exist.json") == {}
