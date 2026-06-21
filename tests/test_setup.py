"""`diting setup` tests — drive/verify with fake probes (no real TCC).

The permission probes and the bundle / Settings openers are patched, so
these exercise the orchestration (non-interactive, JSON, denied routing,
helper-missing) without touching macOS.
"""
from __future__ import annotations

import json as _json

import pytest

from diting import cli
from diting import permission as perm


@pytest.fixture
def fake_helper(monkeypatch):
    """A located, bundled helper by default."""
    monkeypatch.setattr("diting._helper.find_helper", lambda: "/x/diting-tianer.app/Contents/MacOS/diting-tianer")
    monkeypatch.setattr("diting._helper.bundle_path", lambda b: "/x/diting-tianer.app")
    monkeypatch.setattr("diting._helper.try_build", lambda: None)


def _set_state(monkeypatch, *, location, bluetooth, notifications):
    monkeypatch.setattr(perm, "detect_caps", lambda b: {
        "location_status": True, "bluetooth_auth": True, "notification_status": True,
    })
    monkeypatch.setattr(perm, "probe", lambda b, *, caps=None: {
        "location": location, "bluetooth": bluetooth, "notifications": notifications,
    })


# ---------- permission model ----------

def test_is_ready_requires_location_and_bluetooth():
    assert perm.is_ready({"location": True, "bluetooth": True, "notifications": False})
    assert not perm.is_ready({"location": True, "bluetooth": False, "notifications": True})


def test_settings_pane_url_per_permission():
    assert "Privacy_LocationServices" in perm.settings_pane_url("location")
    assert "Privacy_Bluetooth" in perm.settings_pane_url("bluetooth")
    assert "Privacy_Notifications" in perm.settings_pane_url("notifications")


# ---------- non-interactive / JSON ----------

def test_setup_json_emits_state(monkeypatch, capsys, fake_helper):
    _set_state(monkeypatch, location=True, bluetooth=True, notifications=False)
    with pytest.raises(SystemExit) as ei:
        cli._run_setup(["--json"])
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc == {"location": True, "bluetooth": True,
                   "notifications": False, "ready": True}


def test_setup_json_notifications_unknown(monkeypatch, capsys, fake_helper):
    _set_state(monkeypatch, location=True, bluetooth=True, notifications=None)
    with pytest.raises(SystemExit):
        cli._run_setup(["--json"])
    doc = _json.loads(capsys.readouterr().out)
    assert doc["notifications"] is None and doc["ready"] is True


def test_setup_json_never_opens_bundle(monkeypatch, capsys, fake_helper):
    opened = {"n": 0}
    monkeypatch.setattr(perm, "open_bundle", lambda b, *, lang: opened.__setitem__("n", opened["n"] + 1))
    _set_state(monkeypatch, location=False, bluetooth=False, notifications=False)
    with pytest.raises(SystemExit):
        cli._run_setup(["--json"])
    assert opened["n"] == 0  # non-interactive must not open/block


def test_setup_noninteractive_exit_1_when_not_ready(monkeypatch, capsys, fake_helper):
    # stdout isn't a TTY under capsys → non-interactive even without --json
    _set_state(monkeypatch, location=False, bluetooth=True, notifications=True)
    with pytest.raises(SystemExit) as ei:
        cli._run_setup([])
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "Location" in out


# ---------- helper missing ----------

def test_setup_helper_missing_exits_1(monkeypatch, capsys):
    monkeypatch.setattr("diting._helper.find_helper", lambda: None)
    monkeypatch.setattr("diting._helper.try_build", lambda: None)
    with pytest.raises(SystemExit) as ei:
        cli._run_setup(["--json"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert _json.loads(err)["error"]  # structured error under --json


# ---------- helper probes (test_helper-style, kept here for cohesion) ----------

def test_probe_prefers_readonly_when_supported(monkeypatch):
    # Read-only probes win; the prompting functional probes must NOT be
    # consulted when the helper advertises the read-only ones.
    from diting import _helper

    def boom(b):
        raise AssertionError("functional (prompting) probe must not run")

    monkeypatch.setattr(_helper, "location_status", lambda b: "authorized")
    monkeypatch.setattr(_helper, "bluetooth_authorization_status", lambda b: "authorized")
    monkeypatch.setattr(_helper, "has_notification_permission", lambda b: True)
    monkeypatch.setattr(_helper, "has_permission", boom)
    monkeypatch.setattr(_helper, "has_bluetooth_permission", boom)
    caps = {"location_status": True, "bluetooth_auth": True, "notification_status": True}
    assert perm.probe("/x", caps=caps) == {
        "location": "authorized", "bluetooth": "authorized", "notifications": True,
    }


def test_probe_falls_back_when_readonly_absent(monkeypatch):
    from diting import _helper

    def boom(b):
        raise AssertionError("read-only probe must not run when unsupported")

    monkeypatch.setattr(_helper, "has_permission", lambda b: True)
    monkeypatch.setattr(_helper, "has_bluetooth_permission", lambda b: True)
    monkeypatch.setattr(_helper, "location_status", boom)
    monkeypatch.setattr(_helper, "bluetooth_authorization_status", boom)
    caps = {"location_status": False, "bluetooth_auth": False, "notification_status": False}
    assert perm.probe("/x", caps=caps) == {
        "location": "authorized", "bluetooth": "authorized", "notifications": None,
    }


def test_pending_is_distinct_from_denied():
    assert perm.is_authorized("authorized") is True
    assert perm.is_authorized("not_determined") is False
    assert perm.is_denied("not_determined") is False      # pending — wait, don't route
    assert perm.is_denied("denied") is True
    assert perm.is_denied("restricted") is True
    assert perm.is_ready({"location": "authorized", "bluetooth": "authorized"})
    assert not perm.is_ready({"location": "not_determined", "bluetooth": "authorized"})


def test_setup_json_maps_pending_to_false(monkeypatch, capsys, fake_helper):
    monkeypatch.setattr(perm, "detect_caps", lambda b: {
        "location_status": True, "bluetooth_auth": True, "notification_status": True,
    })
    monkeypatch.setattr(perm, "probe", lambda b, *, caps=None: {
        "location": "not_determined", "bluetooth": "authorized", "notifications": None,
    })
    with pytest.raises(SystemExit):
        cli._run_setup(["--json"])
    doc = _json.loads(capsys.readouterr().out)
    assert doc == {"location": False, "bluetooth": True,
                   "notifications": None, "ready": False}


def test_setup_suppresses_scene_banner(monkeypatch):
    monkeypatch.setattr(cli, "_run_setup", lambda rest: None)
    monkeypatch.setattr(
        cli, "_resolve_scene_at_startup",
        lambda c: ("home", "auto", "auto-detected scene: home (x)"),
    )
    emitted: list = []
    monkeypatch.setattr(cli, "_emit_scene_banner", lambda b: emitted.append(b))
    monkeypatch.setattr("sys.argv", ["diting", "setup"])
    cli._dispatch()
    assert emitted == []  # banner suppressed for setup


def test_readonly_probe_helpers(monkeypatch):
    from diting import _helper

    class P:
        def __init__(self, rc, out=b""):
            self.returncode = rc
            self.stdout = out
            self.stderr = b""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0))
    assert _helper.location_authorized("/x") is True
    assert _helper.bluetooth_authorized("/x") is True
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(4))
    assert _helper.location_authorized("/x") is False
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0, b"... location-status ... bluetooth-authorization ..."))
    assert _helper.has_location_status_subcommand("/x") is True
    assert _helper.has_bluetooth_authorization_subcommand("/x") is True
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0, b"scan ble-scan"))
    assert _helper.has_location_status_subcommand("/x") is False


def test_notification_probes(monkeypatch):
    from diting import _helper

    class P:
        def __init__(self, rc, out=b""):
            self.returncode = rc
            self.stdout = out
            self.stderr = b""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0))
    assert _helper.has_notification_permission("/x") is True
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(3))
    assert _helper.has_notification_permission("/x") is False
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0, b"... notification-status ..."))
    assert _helper.has_notification_status_subcommand("/x") is True
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0, b"scan ble-scan bluetooth-status"))
    assert _helper.has_notification_status_subcommand("/x") is False
