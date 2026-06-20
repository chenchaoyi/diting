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
    monkeypatch.setattr(perm, "probe", lambda b: {
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
