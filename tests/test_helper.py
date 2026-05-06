"""Tests for the Swift-helper subprocess protocol — JSON parsing,
schema v1 / v2 compatibility, find_helper search order, and
has_permission detection. The Swift binary itself is not exercised
here (it requires a built bundle on disk and the macOS Location
Services state); we mock subprocess.run with realistic payloads
captured from real helper output during development.
"""
from __future__ import annotations

import json
import os
import stat
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from wifiscope import _helper


# Realistic schema-v2 payload from a working helper run
SCHEMA_V2 = {
    "schema": 2,
    "interface": {
        "name": "en0",
        "country_code": "CN",
        "hardware_address": "84:2f:57:9b:15:59",
    },
    "timestamp": "2026-05-06T01:23:45Z",
    "networks": [
        {
            "ssid": "tedo_5G",
            "bssid": "40:fe:95:89:c7:e3",
            "rssi_dbm": -54,
            "noise_dbm": -94,
            "channel": 48,
            "channel_width_raw": 3,
            "channel_band_raw": 2,
            "security_raw": 4,
        },
        {
            "ssid": "tedo",
            "bssid": "40:fe:95:89:c7:e0",
            "rssi_dbm": -50,
            "noise_dbm": 0,
            "channel": 6,
            "channel_width_raw": 2,
            "channel_band_raw": 1,
            "security_raw": 4,
        },
    ],
}

# Schema v1 used a string for the interface field. Older helpers may
# still be installed in /Applications when the user runs a freshly
# checked-out wifiscope.
SCHEMA_V1 = {
    "schema": 1,
    "interface": "en0",
    "timestamp": "2026-05-05T12:00:00Z",
    "networks": SCHEMA_V2["networks"],
}


def _mock_run(stdout, returncode=0):
    """Build a mock subprocess.CompletedProcess-like object."""
    class _Proc:
        pass
    p = _Proc()
    p.stdout = stdout if isinstance(stdout, bytes) else stdout.encode()
    p.stderr = b""
    p.returncode = returncode
    return p


# --- scan() parsing --------------------------------------------------

def test_scan_v2_returns_networks_and_iface_meta():
    raw = json.dumps(SCHEMA_V2)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        results, meta = _helper.scan("/fake/binary")
    assert len(results) == 2
    r = results[0]
    assert r.ssid == "tedo_5G"
    assert r.bssid == "40:fe:95:89:c7:e3"
    assert r.rssi_dbm == -54
    assert r.channel == 48
    assert r.channel_band == "5 GHz"
    assert r.channel_width_mhz == 80
    assert r.security == "WPA2 Personal"
    assert meta["country_code"] == "CN"
    assert meta["hardware_address"] == "84:2f:57:9b:15:59"


def test_scan_v1_iface_string_yields_empty_meta():
    """v1's interface field was a plain string; the parser must not
    confuse it with a meta dict."""
    raw = json.dumps(SCHEMA_V1)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        results, meta = _helper.scan("/fake/binary")
    assert len(results) == 2
    assert meta == {}


def test_scan_zero_noise_and_zero_rssi_become_none():
    """The helper passes the raw CoreWLAN integer through; '0' from
    that API means 'no measurement', not '0 dBm'. The Python side
    normalises so the UI shows '?' instead of a misleading 0."""
    payload = {
        "schema": 2,
        "interface": {"name": "en0"},
        "networks": [{"bssid": "aa:bb:cc:dd:ee:ff", "rssi_dbm": 0,
                       "noise_dbm": 0}],
    }
    raw = json.dumps(payload)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    assert results[0].rssi_dbm is None
    assert results[0].noise_dbm is None


def test_scan_lowercases_bssid():
    payload = {
        "schema": 2,
        "interface": {"name": "en0"},
        "networks": [{"ssid": "x", "bssid": "AA:BB:CC:DD:EE:FF",
                       "rssi_dbm": -50}],
    }
    raw = json.dumps(payload)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    assert results[0].bssid == "aa:bb:cc:dd:ee:ff"


def test_scan_redacted_row_keeps_bssid_none():
    """When the helper has no permission, ssid/bssid keys are absent
    from each network. The dataclass slots stay None."""
    payload = {
        "schema": 2,
        "interface": {"name": "en0"},
        "networks": [{"rssi_dbm": -60, "channel": 36}],
    }
    raw = json.dumps(payload)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    assert results[0].ssid is None
    assert results[0].bssid is None
    # but other useful fields still flow through
    assert results[0].rssi_dbm == -60


def test_scan_malformed_json_returns_empty():
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run("not json")):
        results, meta = _helper.scan("/fake/binary")
    assert results == []
    assert meta == {}


def test_scan_nonzero_exit_returns_empty():
    raw = json.dumps(SCHEMA_V2)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw, returncode=2)):
        results, meta = _helper.scan("/fake/binary")
    assert results == []
    assert meta == {}


def test_scan_subprocess_timeout_returns_empty():
    import subprocess
    with patch(
        "wifiscope._helper.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1),
    ):
        results, meta = _helper.scan("/fake/binary")
    assert results == []
    assert meta == {}


# --- has_permission --------------------------------------------------

def test_has_permission_true_when_any_bssid_populated():
    raw = json.dumps(SCHEMA_V2)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        assert _helper.has_permission("/fake/binary") is True


def test_has_permission_false_when_all_redacted():
    payload = {
        "schema": 2,
        "interface": {"name": "en0"},
        "networks": [
            {"rssi_dbm": -50, "channel": 36},
            {"rssi_dbm": -60, "channel": 6},
        ],
    }
    raw = json.dumps(payload)
    with patch("wifiscope._helper.subprocess.run", return_value=_mock_run(raw)):
        assert _helper.has_permission("/fake/binary") is False


def test_has_permission_false_on_subprocess_error():
    with patch("wifiscope._helper.subprocess.run", side_effect=OSError):
        assert _helper.has_permission("/fake/binary") is False


# --- bundle_path -----------------------------------------------------

def test_bundle_path_extracts_app_dir(tmp_path):
    bundle = tmp_path / "wifiscope-helper.app"
    binary = bundle / "Contents" / "MacOS" / "wifiscope-helper"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    assert _helper.bundle_path(str(binary)) == str(bundle)


def test_bundle_path_none_for_loose_binary(tmp_path):
    binary = tmp_path / "loose-binary"
    binary.write_text("")
    assert _helper.bundle_path(str(binary)) is None


# --- find_helper search order ----------------------------------------

def _make_bundle(parent: Path) -> Path:
    """Create a minimal executable that looks like a helper bundle binary."""
    binary = parent / "wifiscope-helper.app" / "Contents" / "MacOS" / "wifiscope-helper"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
    return binary


def test_find_helper_env_override_wins(tmp_path, monkeypatch):
    """WIFISCOPE_HELPER must beat any candidate path on disk."""
    binary = _make_bundle(tmp_path)
    monkeypatch.setenv("WIFISCOPE_HELPER", str(binary.parent.parent.parent))
    assert _helper.find_helper() == str(binary)


def test_find_helper_env_override_can_point_at_binary(tmp_path, monkeypatch):
    """For dev convenience the env var may also point at the binary
    directly (skipping the .app/Contents/MacOS dance)."""
    binary = tmp_path / "anywhere"
    binary.write_text("")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("WIFISCOPE_HELPER", str(binary))
    assert _helper.find_helper() == str(binary)


def test_find_helper_returns_none_when_nothing_present(tmp_path, monkeypatch):
    monkeypatch.delenv("WIFISCOPE_HELPER", raising=False)
    # Point all standard locations at empty dirs by overriding HOME
    monkeypatch.setenv("HOME", str(tmp_path))
    # We cannot un-publish /Applications, but the test still proves the
    # env-override path returns None when env is unset and no override
    # bundle exists at the override path.
    monkeypatch.setenv("WIFISCOPE_HELPER", str(tmp_path / "missing.app"))
    assert _helper.find_helper() is None
