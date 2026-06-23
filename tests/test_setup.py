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
    monkeypatch.setattr(perm, "probe", lambda b, *, caps=None, settle=None: {
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

    monkeypatch.setattr(_helper, "location_status", lambda b, *, settle=None: "authorized")
    monkeypatch.setattr(_helper, "bluetooth_authorization_status", lambda b: "authorized")
    monkeypatch.setattr(_helper, "notification_status", lambda b: "authorized")
    monkeypatch.setattr(_helper, "has_permission", boom)
    monkeypatch.setattr(_helper, "has_bluetooth_permission", boom)
    caps = {"location_status": True, "bluetooth_auth": True, "notification_status": True}
    assert perm.probe("/x", caps=caps) == {
        "location": "authorized", "bluetooth": "authorized", "notifications": "authorized",
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
    monkeypatch.setattr(perm, "probe", lambda b, *, caps=None, settle=None: {
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


# ---------- polish-setup-ux: prompt-launch settle + indented output ----------

def test_probe_threads_settle_to_location(monkeypatch):
    """`permission.probe(settle=…)` forwards the settle to location_status;
    the other probes are unaffected."""
    from diting import _helper

    seen = {}
    monkeypatch.setattr(_helper, "location_status",
                        lambda b, *, settle=None: seen.__setitem__("settle", settle) or "not_determined")
    monkeypatch.setattr(_helper, "bluetooth_authorization_status", lambda b: "authorized")
    monkeypatch.setattr(_helper, "has_notification_permission", lambda b: True)
    caps = {"location_status": True, "bluetooth_auth": True, "notification_status": True}
    out = perm.probe("/x", caps=caps, settle=1.2)
    assert seen["settle"] == 1.2
    assert out["location"] == "not_determined"


def test_location_status_settle_sets_env(monkeypatch):
    """A `settle` override sets DITING_LOC_SETTLE on the subprocess; the
    default (settle=None) passes no custom env."""
    from diting import _helper

    class P:
        returncode = 4
        stdout = b""
        stderr = b""

    captured = {}
    monkeypatch.setattr("subprocess.run",
                        lambda *a, **k: captured.update(k) or P())
    assert _helper.location_status("/x", settle=0.5) == "not_determined"
    assert float(captured["env"]["DITING_LOC_SETTLE"]) == 0.5

    captured.clear()
    _helper.location_status("/x")  # default: no settle override
    assert captured.get("env") is None


def test_setup_json_uses_default_settle(monkeypatch, capsys, fake_helper):
    """The --json path reads with the accurate default settle (settle=None),
    never the short prompt-launch pre-check value."""
    settles = []
    monkeypatch.setattr(perm, "detect_caps", lambda b: {
        "location_status": True, "bluetooth_auth": True, "notification_status": True,
    })

    def rec(b, *, caps=None, settle=None):
        settles.append(settle)
        return {"location": True, "bluetooth": True, "notifications": True}

    monkeypatch.setattr(perm, "probe", rec)
    with pytest.raises(SystemExit):
        cli._run_setup(["--json"])
    assert settles == [None]


def test_setup_indent_pads_human_output(monkeypatch, capsys):
    monkeypatch.setenv("DITING_SETUP_INDENT", "4")
    cli._sprint("hello\nworld")
    cli._sprint()  # blank line stays blank, no trailing spaces
    out = capsys.readouterr().out
    assert out == "    hello\n    world\n\n"


def test_setup_indent_absent_no_pad(monkeypatch, capsys):
    monkeypatch.delenv("DITING_SETUP_INDENT", raising=False)
    cli._sprint("hi")
    assert capsys.readouterr().out == "hi\n"
    # Unparsable value is treated as no indent, not a crash.
    monkeypatch.setenv("DITING_SETUP_INDENT", "lots")
    cli._sprint("hi")
    assert capsys.readouterr().out == "hi\n"


def test_setup_json_never_indented(monkeypatch, capsys, fake_helper):
    """--json output is machine-readable and must not be indented even when
    DITING_SETUP_INDENT is set."""
    monkeypatch.setenv("DITING_SETUP_INDENT", "6")
    _set_state(monkeypatch, location=True, bluetooth=True, notifications=False)
    with pytest.raises(SystemExit):
        cli._run_setup(["--json"])
    out = capsys.readouterr().out
    assert not out.startswith(" ")
    assert _json.loads(out)["ready"] is True


# ---------- installer-permissions-step: notifications visibility ----------

def test_notification_status_string_probe(monkeypatch):
    """`_helper.notification_status` maps the notification-status exit codes
    to a status string (mirrors location/bluetooth)."""
    from diting import _helper

    class P:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = b""
            self.stderr = b""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(0))
    assert _helper.notification_status("/x") == "authorized"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(3))
    assert _helper.notification_status("/x") == "denied"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(4))
    assert _helper.notification_status("/x") == "not_determined"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P(2))
    assert _helper.notification_status("/x") == "unknown"


def test_probe_notifications_is_status_string(monkeypatch):
    """`permission.probe` returns Notifications as a status string when the
    helper supports it; None when it does not."""
    from diting import _helper
    monkeypatch.setattr(_helper, "location_status", lambda b, *, settle=None: "authorized")
    monkeypatch.setattr(_helper, "bluetooth_authorization_status", lambda b: "authorized")
    monkeypatch.setattr(_helper, "notification_status", lambda b: "not_determined")
    caps_yes = {"location_status": True, "bluetooth_auth": True, "notification_status": True}
    assert perm.probe("/x", caps=caps_yes)["notifications"] == "not_determined"

    caps_no = {"location_status": True, "bluetooth_auth": True, "notification_status": False}
    assert perm.probe("/x", caps=caps_no)["notifications"] is None


def test_setup_json_notifications_status_maps_to_bool(monkeypatch, capsys, fake_helper):
    """A Notifications status string collapses to a bool in --json:
    authorized → true, pending/denied → false, None → null."""
    monkeypatch.setattr(perm, "detect_caps", lambda b: {
        "location_status": True, "bluetooth_auth": True, "notification_status": True})

    for status, expect in [("authorized", True), ("denied", False),
                           ("not_determined", False)]:
        monkeypatch.setattr(perm, "probe", lambda b, *, caps=None, settle=None, _s=status: {
            "location": "authorized", "bluetooth": "authorized", "notifications": _s})
        with pytest.raises(SystemExit):
            cli._run_setup(["--json"])
        doc = _json.loads(capsys.readouterr().out)
        assert doc["notifications"] is expect


def test_setup_waits_for_notifications_to_settle(monkeypatch, capsys, fake_helper):
    """Interactive: after the required grants land, setup keeps polling until
    the best-effort Notifications prompt settles, showing all three lines."""
    import sys as _sys
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(perm, "open_bundle", lambda b, *, lang: True)
    monkeypatch.setattr(perm, "detect_caps", lambda b: {
        "location_status": True, "bluetooth_auth": True, "notification_status": True})

    seq = [
        # pre-check: not ready
        {"location": "not_determined", "bluetooth": "not_determined",
         "notifications": "not_determined"},
        # loop 1: required ready, notifications still pending
        {"location": "authorized", "bluetooth": "authorized",
         "notifications": "not_determined"},
        # loop 2: notifications settles
        {"location": "authorized", "bluetooth": "authorized",
         "notifications": "authorized"},
    ]
    calls = {"n": 0}

    def fake_probe(b, *, caps=None, settle=None):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr(perm, "probe", fake_probe)
    cli._run_setup([])  # interactive success returns (no SystemExit)
    out = capsys.readouterr().out
    assert "Notifications: waiting" in out      # shown while pending
    assert "Notifications: granted" in out      # then settled
    assert "all required permissions granted" in out
