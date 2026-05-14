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

from diting import _helper


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
# checked-out diting.
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
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
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
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
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
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
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
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
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
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    assert results[0].ssid is None
    assert results[0].bssid is None
    # but other useful fields still flow through
    assert results[0].rssi_dbm == -60


def test_scan_malformed_json_returns_empty():
    with patch("diting._helper.subprocess.run", return_value=_mock_run("not json")):
        results, meta = _helper.scan("/fake/binary")
    assert results == []
    assert meta == {}


def test_scan_nonzero_exit_returns_empty():
    raw = json.dumps(SCHEMA_V2)
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw, returncode=2)):
        results, meta = _helper.scan("/fake/binary")
    assert results == []
    assert meta == {}


def test_scan_subprocess_timeout_returns_empty():
    import subprocess
    with patch(
        "diting._helper.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1),
    ):
        results, meta = _helper.scan("/fake/binary")
    assert results == []
    assert meta == {}


# --- has_permission --------------------------------------------------

def test_has_permission_true_when_any_bssid_populated():
    raw = json.dumps(SCHEMA_V2)
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
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
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
        assert _helper.has_permission("/fake/binary") is False


def test_has_permission_false_on_subprocess_error():
    with patch("diting._helper.subprocess.run", side_effect=OSError):
        assert _helper.has_permission("/fake/binary") is False


# --- has_ble_scan_subcommand ----------------------------------------

# A representative --help string from the 0.5.0 helper. Anything
# containing "ble-scan" should pass the probe; anything that does not
# (notably the 0.4.0 release's two-line --help) must fail it so the
# stale-bundle detection in _ensure_helper_ready can fall back to a
# rebuild.
_HELP_05 = b"""\
diting-tianer

  (no args)   Launch the bundle UI ...
  scan        Perform a CoreWLAN scan ...
  ble-scan    Scan nearby BLE advertisements ...
"""

_HELP_04 = b"""\
diting-tianer

  (no args)   Launch the bundle UI ...
  scan        Perform a CoreWLAN scan ...
"""


def test_has_ble_scan_subcommand_true_when_help_lists_it():
    """0.5.0+ helper bundle: --help mentions ble-scan, probe returns True."""
    with patch("diting._helper.subprocess.run",
               return_value=_mock_run(_HELP_05)):
        assert _helper.has_ble_scan_subcommand("/fake/binary") is True


def test_has_ble_scan_subcommand_false_for_pre_0_5_helper():
    """A 0.4.0-era bundle in /Applications/ would still answer scan but
    has no ble-scan; the probe must spot that and return False so the
    upgrade path can rebuild a 0.5.0-capable bundle in-repo."""
    with patch("diting._helper.subprocess.run",
               return_value=_mock_run(_HELP_04)):
        assert _helper.has_ble_scan_subcommand("/fake/binary") is False


def test_has_ble_scan_subcommand_false_on_timeout():
    """Hung --help (binary corrupt, signing problem, etc.) is treated
    as 'cannot determine' which we conservatively flag as not capable
    so the user sees an explicit incompatible-helper hint instead of a
    silent BLE wedge."""
    import subprocess
    with patch("diting._helper.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
        assert _helper.has_ble_scan_subcommand("/fake/binary") is False


def test_has_bluetooth_permission_true_on_zero_exit():
    """The helper's bluetooth-status subcommand exits 0 only when
    CBCentralManager resolves to .poweredOn — i.e. TCC granted and
    radio is on. Probe wraps that as a clean True/False."""
    with patch("diting._helper.subprocess.run",
               return_value=_mock_run("", returncode=0)):
        assert _helper.has_bluetooth_permission("/fake/binary") is True


def test_has_bluetooth_permission_false_on_unauthorized():
    """Exit 3 (.unauthorized) — user has not granted Bluetooth.
    Treated as False so the launcher routes through the open-helper
    flow to prompt."""
    with patch("diting._helper.subprocess.run",
               return_value=_mock_run("", returncode=3)):
        assert _helper.has_bluetooth_permission("/fake/binary") is False


def test_has_bluetooth_permission_false_on_timeout():
    """If TCC silently denies, the helper sits in .unknown forever and
    its own 2 s timeout fires, exiting 2. The Python timeout (8 s) is
    a backstop. Either path is "no" from the launcher."""
    import subprocess
    with patch("diting._helper.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="x", timeout=8)):
        assert _helper.has_bluetooth_permission("/fake/binary") is False


def test_has_bluetooth_permission_false_on_oserror():
    """Defensive: missing / non-executable binary."""
    with patch("diting._helper.subprocess.run", side_effect=OSError):
        assert _helper.has_bluetooth_permission("/fake/binary") is False


def test_has_ble_scan_subcommand_reads_stderr_too():
    """Some Swift command-line tools route --help to stderr instead of
    stdout. The probe concatenates both streams so the detection is
    independent of where the message lands."""
    class _Proc:
        pass
    p = _Proc()
    p.stdout = b""
    p.stderr = _HELP_05
    p.returncode = 0
    with patch("diting._helper.subprocess.run", return_value=p):
        assert _helper.has_ble_scan_subcommand("/fake/binary") is True


# --- bundle_path -----------------------------------------------------

def test_bundle_path_extracts_app_dir(tmp_path):
    bundle = tmp_path / "diting-tianer.app"
    binary = bundle / "Contents" / "MacOS" / "diting-tianer"
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
    binary = parent / "diting-tianer.app" / "Contents" / "MacOS" / "diting-tianer"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
    return binary


def test_find_helper_env_override_wins(tmp_path, monkeypatch):
    """DITING_HELPER must beat any candidate path on disk."""
    binary = _make_bundle(tmp_path)
    monkeypatch.setenv("DITING_HELPER", str(binary.parent.parent.parent))
    assert _helper.find_helper() == str(binary)


def test_find_helper_env_override_can_point_at_binary(tmp_path, monkeypatch):
    """For dev convenience the env var may also point at the binary
    directly (skipping the .app/Contents/MacOS dance)."""
    binary = tmp_path / "anywhere"
    binary.write_text("")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("DITING_HELPER", str(binary))
    assert _helper.find_helper() == str(binary)


def test_find_helper_returns_none_when_nothing_present(tmp_path, monkeypatch):
    monkeypatch.delenv("DITING_HELPER", raising=False)
    # Point all standard locations at empty dirs by overriding HOME
    monkeypatch.setenv("HOME", str(tmp_path))
    # We cannot un-publish /Applications, but the test still proves the
    # env-override path returns None when env is unset and no override
    # bundle exists at the override path.
    monkeypatch.setenv("DITING_HELPER", str(tmp_path / "missing.app"))
    assert _helper.find_helper() is None


def _redirect_search_locations(tmp_path, monkeypatch):
    """Steer `find_helper()` away from the real repo + the user's
    real `/Applications` so we can assert resolution against a
    controlled tmp directory.

    The function builds its candidate list from two roots:
    - `Path(_helper.__file__).resolve().parents[2]` for the in-repo
      dev build — we re-point `_helper.__file__` at a tmp location
      so that walk resolves into `tmp_path/fake_repo/`.
    - `Path("~/...")` expansions for `~/Applications` and
      `~/Library/Application Support/diting/` — we override HOME.

    `/Applications/diting-tianer.app` is the one path we can't
    redirect — but in CI / contributor environments that path is
    almost never present, and even if it is, the in-repo dev path
    is checked first, so a bundle in the tmp "repo" root shadows
    it. Callers create only the bundles they want present in the
    locations they want to test.
    """
    monkeypatch.delenv("DITING_HELPER", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    fake_repo = tmp_path / "fake_repo"
    (fake_repo / "src" / "diting").mkdir(parents=True)
    fake_helper_py = fake_repo / "src" / "diting" / "_helper.py"
    fake_helper_py.write_text("")
    monkeypatch.setattr(_helper, "__file__", str(fake_helper_py))
    return fake_repo


def test_find_helper_picks_up_application_support_bundle(tmp_path, monkeypatch):
    """The curl-bash one-line installer drops the helper at
    ~/Library/Application Support/diting/diting-tianer.app.
    find_helper() walks to that path when no other candidate
    location holds a bundle."""
    _redirect_search_locations(tmp_path, monkeypatch)
    app_support_dir = tmp_path / "Library" / "Application Support" / "diting"
    binary = _make_bundle(app_support_dir)
    assert _helper.find_helper() == str(binary)


def test_find_helper_repo_dev_build_shadows_application_support(
    tmp_path, monkeypatch,
):
    """A contributor with both the in-repo dev build AND the
    one-line installer's drop in Application Support MUST see the
    in-repo bundle resolved — the dev path is pinned first in the
    search order so a freshly-`make helper`ed bundle always wins."""
    fake_repo = _redirect_search_locations(tmp_path, monkeypatch)
    repo_helper_dir = fake_repo / "helper"
    dev_binary = _make_bundle(repo_helper_dir)
    # Also create a bundle in Application Support — without the
    # priority pin both candidates would match, and we'd be relying
    # on dict-iteration order. The assertion below verifies the
    # contract: the repo dev build wins.
    app_support_dir = tmp_path / "Library" / "Application Support" / "diting"
    _make_bundle(app_support_dir)
    resolved = _helper.find_helper()
    assert resolved == str(dev_binary)
    assert "Library/Application Support" not in resolved


# --- schema-3 IE fields (v0.7.0) ------------------------------------

def test_scan_v3_parses_bss_load_and_station_count():
    """Schema-3 helpers populate bss_load_pct and bss_station_count
    when the AP advertises a BSS Load IE; the Python parser surfaces
    them as ints on the ScanResult dataclass."""
    payload = {
        "schema": 3,
        "interface": {"name": "en0"},
        "networks": [
            {
                "ssid": "office",
                "bssid": "aa:bb:cc:00:11:22",
                "rssi_dbm": -55,
                "channel": 36,
                "bss_load_pct": 78,
                "bss_station_count": 12,
            }
        ],
    }
    raw = json.dumps(payload)
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    assert results[0].bss_load_pct == 78
    assert results[0].bss_station_count == 12


def test_scan_v3_parses_802_11r_capability_flag():
    """Mobility Domain IE → supports_802_11r=True. Other capability
    flags stay None when their IE was absent (defensive: the helper
    only emits keys it positively detected)."""
    payload = {
        "schema": 3,
        "interface": {"name": "en0"},
        "networks": [
            {
                "ssid": "office",
                "bssid": "aa:bb:cc:00:11:22",
                "rssi_dbm": -55,
                "supports_802_11r": True,
            }
        ],
    }
    raw = json.dumps(payload)
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    assert results[0].supports_802_11r is True
    assert results[0].supports_802_11k is None
    assert results[0].supports_802_11v is None


def test_scan_v2_keeps_ie_fields_none():
    """A v2 helper output (no IE keys at all) still parses cleanly;
    every IE-derived field arrives as None so the new dataclass slots
    are forward-compatible."""
    raw = json.dumps(SCHEMA_V2)
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    r = results[0]
    assert r.bss_load_pct is None
    assert r.bss_station_count is None
    assert r.supports_802_11r is None
    assert r.supports_802_11k is None
    assert r.supports_802_11v is None


def test_scan_v3_rejects_malformed_ie_values():
    """Defensive: a helper that emits the wrong type for an IE field
    (string instead of int, 0/1 instead of bool) must not corrupt the
    dataclass — the Python side coerces unsafe values to None and
    keeps the row otherwise valid."""
    payload = {
        "schema": 3,
        "interface": {"name": "en0"},
        "networks": [
            {
                "ssid": "office",
                "bssid": "aa:bb:cc:00:11:22",
                "rssi_dbm": -55,
                "bss_load_pct": "high",   # nonsense
                "bss_station_count": 1.5,   # nonsense
                "supports_802_11r": 1,    # 1 is not a bool — coerce to None
                "supports_802_11k": True,
            }
        ],
    }
    raw = json.dumps(payload)
    with patch("diting._helper.subprocess.run", return_value=_mock_run(raw)):
        results, _ = _helper.scan("/fake/binary")
    r = results[0]
    assert r.bss_load_pct is None
    assert r.bss_station_count is None
    assert r.supports_802_11r is None
    assert r.supports_802_11k is True
    # Sanity: row itself is still populated; just the unsafe fields
    # were dropped.
    assert r.bssid == "aa:bb:cc:00:11:22"
    assert r.rssi_dbm == -55


# ---------- bundle branding ----------

def test_helper_bundle_declares_appicon_and_ships_iconset():
    """The helper bundle MUST ship the diting logo as its AppIcon.
    Info.plist declares `CFBundleIconFile=AppIcon`, and the iconset
    source covers the macOS standard sizes so `iconutil --convert
    icns` (run by helper/build.sh) produces a usable .icns."""
    repo_root = Path(__file__).resolve().parent.parent
    info_plist = repo_root / "helper" / "Info.plist"
    assert info_plist.exists(), "helper/Info.plist must exist"
    content = info_plist.read_text(encoding="utf-8")
    assert "<key>CFBundleIconFile</key>" in content
    assert "<string>AppIcon</string>" in content

    iconset = repo_root / "helper" / "Resources" / "AppIcon.iconset"
    assert iconset.is_dir(), (
        "helper/Resources/AppIcon.iconset must be committed so "
        "helper/build.sh can run `iconutil --convert icns` against it"
    )
    required = {
        "icon_16x16.png",      "icon_16x16@2x.png",
        "icon_32x32.png",      "icon_32x32@2x.png",
        "icon_128x128.png",    "icon_128x128@2x.png",
        "icon_256x256.png",    "icon_256x256@2x.png",
        "icon_512x512.png",    "icon_512x512@2x.png",
    }
    present = {p.name for p in iconset.iterdir() if p.suffix == ".png"}
    missing = required - present
    assert not missing, f"AppIcon.iconset is missing sizes: {sorted(missing)}"
