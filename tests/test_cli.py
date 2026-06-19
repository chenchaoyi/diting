"""CLI-level smoke tests.

These exercise `diting.cli.main` through `sys.argv` patching — close
to how the entry-point script invokes it, but without forking a real
process. Subcommand internals have their own tests; this file owns
the top-level flag dispatch.
"""
from __future__ import annotations

import asyncio as _asyncio
import json as _json
from importlib.metadata import version as _pkg_version

import pytest

from diting import cli


def test_version_flag_prints_running_version(monkeypatch, capsys) -> None:
    """`diting --version` prints `diting <X.Y.Z>` matching the
    installed package version, and exits without launching the TUI
    or any helper. This is the version users / bug reporters read."""
    monkeypatch.setattr("sys.argv", ["diting", "--version"])
    cli.main()
    out = capsys.readouterr().out.strip()
    expected = f"diting {_pkg_version('diting')}"
    assert out == expected, (
        f"--version should print {expected!r}, got {out!r}"
    )


def test_version_flag_short_dash_v(monkeypatch, capsys) -> None:
    """`diting -V` is an alias for `--version`."""
    monkeypatch.setattr("sys.argv", ["diting", "-V"])
    cli.main()
    out = capsys.readouterr().out.strip()
    assert out.startswith("diting ")
    # Version part should be PEP 440-ish — at minimum non-empty.
    assert len(out.split()[1]) > 0


def test_version_short_circuits_before_locale(monkeypatch, capsys) -> None:
    """`--version` MUST run before locale resolution / TUI launch.
    Passing both `--version` and `--lang zh` should still produce the
    English version line without launching the TUI."""
    # Sentinel: if main() reached the TUI path, this would raise
    # before we got there (resolve_helper_binary etc.). The version
    # short-circuit avoids that entire codepath.
    monkeypatch.setattr("sys.argv", ["diting", "--lang", "zh", "--version"])
    cli.main()
    out = capsys.readouterr().out.strip()
    assert out.startswith("diting ")


# ------------------------------------------------------------------
# --ble-presence-gate flag + DITING_BLE_PRESENCE_GATE env var
# ------------------------------------------------------------------


def test_extract_ble_presence_gate_arg_parses_seconds_form() -> None:
    args = ["--ble-presence-gate", "30s"]
    assert cli._extract_ble_presence_gate_arg(args) == 30.0
    assert args == []


def test_extract_ble_presence_gate_arg_parses_equals_form() -> None:
    args = ["--ble-presence-gate=2m"]
    assert cli._extract_ble_presence_gate_arg(args) == 120.0
    assert args == []


def test_extract_ble_presence_gate_arg_accepts_zero_shortcut() -> None:
    """`--ble-presence-gate 0` (no unit) is the obvious way to spell
    'disable the gate'; accept it without forcing the user to type
    `0s`."""
    args = ["--ble-presence-gate", "0"]
    assert cli._extract_ble_presence_gate_arg(args) == 0.0


def test_extract_ble_presence_gate_arg_absent_returns_none() -> None:
    """Caller distinguishes 'not passed' from '0s' so it can fall
    back to env var. None is the absence sentinel."""
    args = ["--lang", "en"]
    assert cli._extract_ble_presence_gate_arg(args) is None
    assert args == ["--lang", "en"]


def test_extract_ble_presence_gate_arg_invalid_unit_exits(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr("sys.argv", ["diting"])  # for any locale-resolve side effect
    with pytest.raises(SystemExit):
        cli._extract_ble_presence_gate_arg(["--ble-presence-gate", "abc"])


def test_resolve_ble_presence_gate_cli_wins(monkeypatch) -> None:
    """CLI value takes precedence over env var (matches the
    DITING_LANG / DITING_LOG resolution pattern)."""
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "60s")
    assert cli._resolve_ble_presence_gate(15.0) == 15.0


def test_resolve_ble_presence_gate_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "30s")
    assert cli._resolve_ble_presence_gate(None) == 30.0


def test_resolve_ble_presence_gate_default_5s(monkeypatch) -> None:
    monkeypatch.delenv("DITING_BLE_PRESENCE_GATE", raising=False)
    assert cli._resolve_ble_presence_gate(None) == 5.0


def test_resolve_ble_presence_gate_blank_env_is_default(monkeypatch) -> None:
    """A blank env var means 'parent shell explicitly unset me' — fall
    back to the default, not refuse to launch."""
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "")
    assert cli._resolve_ble_presence_gate(None) == 5.0


def test_resolve_ble_presence_gate_invalid_env_warns_and_defaults(
    monkeypatch, capsys,
) -> None:
    """Invalid env var → stderr warning, return 5.0 default (don't
    crash startup over a broken shell rc)."""
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "garbage")
    assert cli._resolve_ble_presence_gate(None) == 5.0
    err = capsys.readouterr().err
    assert "DITING_BLE_PRESENCE_GATE" in err


# ------------------------------------------------------------------
# --scene flag + scene-aware _resolve_ble_presence_gate
# ------------------------------------------------------------------


def test_extract_scene_arg_parses_value() -> None:
    args = ["--scene", "office"]
    assert cli._extract_scene_arg(args) == "office"
    assert args == []


def test_extract_scene_arg_parses_equals_form() -> None:
    args = ["--scene=audit"]
    assert cli._extract_scene_arg(args) == "audit"
    assert args == []


def test_extract_scene_arg_absent_returns_none() -> None:
    args = ["--lang", "en"]
    assert cli._extract_scene_arg(args) is None
    assert args == ["--lang", "en"]


def test_extract_scene_arg_invalid_value_exits(capsys) -> None:
    """Bad CLI input is a clear error, not a fallback. The user
    typed something wrong; tell them, exit non-zero."""
    with pytest.raises(SystemExit):
        cli._extract_scene_arg(["--scene", "shop"])
    err = capsys.readouterr().err
    assert "shop" in err
    # The error must list the valid scene names so the user can fix it.
    for name in ("home", "office", "public", "audit"):
        assert name in err


def test_extract_scene_arg_missing_value_exits() -> None:
    with pytest.raises(SystemExit):
        cli._extract_scene_arg(["--scene"])


def test_resolve_ble_presence_gate_uses_scene_default_when_no_cli_no_env(
    monkeypatch,
) -> None:
    """When neither CLI flag nor env var is set, the scene-derived
    default wins. This is what `diting --scene office` triggers:
    no `--ble-presence-gate`, no env var, gate becomes 15.0."""
    monkeypatch.delenv("DITING_BLE_PRESENCE_GATE", raising=False)
    assert cli._resolve_ble_presence_gate(
        None, scene_default=15.0,
    ) == 15.0


def test_resolve_ble_presence_gate_cli_overrides_scene_default(
    monkeypatch,
) -> None:
    """`--scene office --ble-presence-gate 5s` → gate is 5s, NOT
    the office-scene default 15s. Explicit flag is narrower-scoped
    and always wins."""
    monkeypatch.delenv("DITING_BLE_PRESENCE_GATE", raising=False)
    assert cli._resolve_ble_presence_gate(
        5.0, scene_default=15.0,
    ) == 5.0


def test_resolve_ble_presence_gate_env_wins_over_scene_default(
    monkeypatch,
) -> None:
    """Env var sits between CLI flag and scene default in precedence.
    `DITING_BLE_PRESENCE_GATE=60s --scene office` → gate is 60s."""
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "60s")
    assert cli._resolve_ble_presence_gate(
        None, scene_default=15.0,
    ) == 60.0


def test_resolve_ble_presence_gate_blank_env_falls_to_scene_default(
    monkeypatch,
) -> None:
    """`DITING_BLE_PRESENCE_GATE= --scene public` → gate is 30s
    (the public scene default), not the hard 5s fallback."""
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "")
    assert cli._resolve_ble_presence_gate(
        None, scene_default=30.0,
    ) == 30.0


def test_resolve_ble_presence_gate_invalid_env_falls_to_scene_default(
    monkeypatch, capsys,
) -> None:
    """Invalid env var still falls to scene default (not the hard
    5s baseline). Warn on stderr but don't crash startup."""
    monkeypatch.setenv("DITING_BLE_PRESENCE_GATE", "garbage")
    assert cli._resolve_ble_presence_gate(
        None, scene_default=30.0,
    ) == 30.0
    err = capsys.readouterr().err
    assert "DITING_BLE_PRESENCE_GATE" in err
    # Warning message names the scene default it fell back to.
    assert "30" in err


# ------------------------------------------------------------------
# Startup scene resolution: CLI > env > yaml > heuristic > default
# ------------------------------------------------------------------


def test_resolve_scene_at_startup_cli_short_circuits_yaml_and_heuristic(
    monkeypatch, tmp_path,
) -> None:
    """When the user passes --scene, the yaml lookup + heuristic do
    NOT run. We assert this by pointing DITING_SCENES_FILE at a yaml
    that would match (and would otherwise win) and confirming CLI
    still wins."""
    yaml_path = tmp_path / "scenes.yaml"
    yaml_path.write_text("networks:\n  - ssid: X\n    scene: office\n")
    monkeypatch.setenv("DITING_SCENES_FILE", str(yaml_path))
    monkeypatch.delenv("DITING_SCENE", raising=False)
    scene_, source, banner = cli._resolve_scene_at_startup("audit")
    assert scene_ == "audit"
    assert source == "cli"
    assert banner is None  # explicit user choice → no banner


def test_resolve_scene_at_startup_env_short_circuits_yaml_and_heuristic(
    monkeypatch, tmp_path,
) -> None:
    yaml_path = tmp_path / "scenes.yaml"
    yaml_path.write_text("networks:\n  - ssid: X\n    scene: office\n")
    monkeypatch.setenv("DITING_SCENES_FILE", str(yaml_path))
    monkeypatch.setenv("DITING_SCENE", "public")
    scene_, source, banner = cli._resolve_scene_at_startup(None)
    assert scene_ == "public"
    assert source == "env"
    assert banner is None


def test_resolve_scene_at_startup_yaml_hit(monkeypatch, tmp_path) -> None:
    """No CLI, no env. scenes.yaml matches the current SSID. The
    yaml tier should resolve; banner names the matched key."""
    yaml_path = tmp_path / "scenes.yaml"
    yaml_path.write_text("networks:\n  - ssid: TestNet\n    scene: office\n")
    monkeypatch.setenv("DITING_SCENES_FILE", str(yaml_path))
    monkeypatch.delenv("DITING_SCENE", raising=False)
    # Patch the WiFi backend so we don't try to hit real CoreWLAN.
    class _FakeConn:
        ssid = "TestNet"
        security = "WPA2 Personal"
        router_ip = None
    class _FakeBackend:
        def get_connection(self):
            return _FakeConn()
        def get_scan_results(self):
            return []
    monkeypatch.setattr(
        "diting.macos_backend.MacOSWiFiBackend",
        lambda *a, **kw: _FakeBackend(),
    )
    scene_, source, banner = cli._resolve_scene_at_startup(None)
    assert scene_ == "office"
    assert source == "yaml"
    assert banner is not None
    assert "TestNet" in banner or "scenes.yaml" in banner


def test_resolve_scene_at_startup_heuristic_when_no_yaml(
    monkeypatch, tmp_path,
) -> None:
    """No yaml hit, but the connection is WPA2 Enterprise — the
    heuristic should fire and return office."""
    yaml_path = tmp_path / "empty.yaml"
    yaml_path.write_text("")
    monkeypatch.setenv("DITING_SCENES_FILE", str(yaml_path))
    monkeypatch.delenv("DITING_SCENE", raising=False)
    class _FakeConn:
        ssid = "MysteryNet"
        security = "WPA2 Enterprise"
        router_ip = None
    class _FakeBackend:
        def get_connection(self):
            return _FakeConn()
        def get_scan_results(self):
            return []
    monkeypatch.setattr(
        "diting.macos_backend.MacOSWiFiBackend",
        lambda *a, **kw: _FakeBackend(),
    )
    scene_, source, banner = cli._resolve_scene_at_startup(None)
    assert scene_ == "office"
    assert source == "auto"
    assert "WPA2 Enterprise" in banner


def test_resolve_scene_at_startup_no_connection_falls_to_default(
    monkeypatch,
) -> None:
    """No active Wi-Fi — heuristic and yaml are both skipped, falls
    to home / default with no banner."""
    monkeypatch.delenv("DITING_SCENE", raising=False)
    monkeypatch.delenv("DITING_SCENES_FILE", raising=False)
    class _FakeBackend:
        def get_connection(self):
            return None
    monkeypatch.setattr(
        "diting.macos_backend.MacOSWiFiBackend",
        lambda *a, **kw: _FakeBackend(),
    )
    scene_, source, banner = cli._resolve_scene_at_startup(None)
    assert scene_ == "home"
    assert source == "default"
    assert banner is None


def test_emit_scene_banner_respects_quiet_env(monkeypatch, capsys) -> None:
    """DITING_SCENE_QUIET=1 silences the banner for scripts that want
    clean startup output."""
    monkeypatch.setenv("DITING_SCENE_QUIET", "1")
    cli._emit_scene_banner("auto-detected scene: office (test)")
    err = capsys.readouterr().err
    assert err == ""


def test_emit_scene_banner_writes_to_stderr_not_stdout(
    monkeypatch, capsys,
) -> None:
    """Banner MUST go to stderr — `diting monitor > log.jsonl` shells
    must not see banner text interleaved with JSONL."""
    monkeypatch.delenv("DITING_SCENE_QUIET", raising=False)
    cli._emit_scene_banner("pinned scene: office (matched X in scenes.yaml)")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pinned scene" in captured.err


def test_emit_scene_banner_none_input_is_no_op(monkeypatch, capsys) -> None:
    """When source is cli / env / default, _resolve_scene_at_startup
    returns None for banner_text. The emitter must accept None silently
    so callers can pass it unconditionally."""
    monkeypatch.delenv("DITING_SCENE_QUIET", raising=False)
    cli._emit_scene_banner(None)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------- Startup splash wire-up (v1.8.0) ----------

def test_ensure_helper_ready_drives_splash_for_two_tcc_probes(
    monkeypatch, tmp_path,
) -> None:
    """_ensure_helper_ready hands the three steps (helper / Location /
    Bluetooth) to splash.run_with_splash; results are consumed back
    into the existing location_ok / bluetooth_ok variables."""
    from diting import _helper, splash

    fake_binary = str(tmp_path / "diting-tianer")
    # `find_helper` would normally probe the filesystem; force it
    # to return our fake path so `_ensure_helper_ready` advances
    # past the locate phase without ever calling `try_build`.
    monkeypatch.setattr(_helper, "find_helper", lambda: fake_binary)
    monkeypatch.setattr(_helper, "has_ble_scan_subcommand", lambda b: True)
    monkeypatch.setattr(_helper, "has_permission", lambda b: True)
    monkeypatch.setattr(_helper, "has_bluetooth_permission", lambda b: True)

    captured: dict[str, object] = {}

    def fake_run_with_splash(steps, *, console=None):
        captured["steps"] = list(steps)
        return [bool(fn()) for _label, fn in steps]

    monkeypatch.setattr(splash, "run_with_splash", fake_run_with_splash)

    result = cli._ensure_helper_ready()

    assert result == fake_binary
    assert len(captured["steps"]) == 3
    labels = [label for label, _fn in captured["steps"]]
    # Labels are i18n-resolved (EN at this point) — assert by EN key
    # since the test runner is in EN locale by default.
    assert labels[0] == "helper located"
    assert labels[1] == "checking Location Services"
    assert labels[2] == "checking Bluetooth"


def test_ensure_helper_ready_consumes_splash_results_into_grant_flow(
    monkeypatch, tmp_path, capsys,
) -> None:
    """When the splash reports Bluetooth as False, _ensure_helper_ready
    SHALL fall into the existing missing-permission prompt path
    (the `Permissions required:` instructional prose) after splash
    teardown — unchanged by the splash refactor."""
    from diting import _helper, splash

    fake_binary = str(tmp_path / "Helper.app" / "Contents" / "MacOS" / "diting-tianer")
    (tmp_path / "Helper.app" / "Contents" / "MacOS").mkdir(parents=True)
    monkeypatch.setattr(_helper, "find_helper", lambda: fake_binary)
    monkeypatch.setattr(_helper, "has_ble_scan_subcommand", lambda b: True)
    monkeypatch.setattr(_helper, "has_permission", lambda b: True)
    monkeypatch.setattr(_helper, "has_bluetooth_permission", lambda b: False)

    def fake_run_with_splash(steps, *, console=None):
        return [bool(fn()) for _label, fn in steps]

    monkeypatch.setattr(splash, "run_with_splash", fake_run_with_splash)
    # Stop the post-splash flow before `open` would actually fire.
    import subprocess as _subprocess
    monkeypatch.setattr(
        _subprocess, "Popen",
        lambda *args, **kwargs: None,
    )
    # Cut the grant-polling loop short by stubbing `time.sleep` to
    # immediately overshoot the timeout.
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)

    cli._ensure_helper_ready()
    captured = capsys.readouterr()
    assert "Permissions required:" in captured.out
    assert "Bluetooth (BLE devices view)" in captured.out


def test_no_companion_flag_sets_env_and_strips(monkeypatch) -> None:
    """`--no-companion` is popped from argv and pins DITING_COMPANION=0 so
    the sink is never built — a per-run self-test mute, pairing untouched."""
    monkeypatch.delenv("DITING_COMPANION", raising=False)
    args = ["--no-companion", "--notify"]
    assert cli._extract_no_companion_arg(args) is True
    assert args == ["--notify"]  # flag stripped, others preserved
    assert __import__("os").environ["DITING_COMPANION"] == "0"


def test_no_companion_flag_absent_leaves_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("DITING_COMPANION", raising=False)
    args = ["--notify"]
    assert cli._extract_no_companion_arg(args) is False
    assert args == ["--notify"]
    assert "DITING_COMPANION" not in __import__("os").environ


def test_no_companion_env_makes_build_sink_inert(monkeypatch, tmp_path) -> None:
    """With the gate set, build_sink returns None even when paired on disk."""
    from diting.companion import runtime
    from diting.companion.state import PairingState

    path = tmp_path / "companion.json"
    PairingState.generate("https://r.example").save(path)
    monkeypatch.setenv("DITING_COMPANION", "0")
    assert runtime.build_sink(path) is None


# ------------------------------------------------------------------
# agent-friendly CLI (agent-friendly-cli)
# ------------------------------------------------------------------

import json as _json


def test_main_guard_turns_exception_into_clean_message(monkeypatch, capsys):
    """An uncaught exception in a runner becomes one `diting: …` line on
    stderr + exit 1 — never a traceback."""
    def boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(cli, "_dispatch", boom)
    monkeypatch.setattr("sys.argv", ["diting", "once"])
    monkeypatch.delenv("DITING_DEBUG", raising=False)
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert err.strip() == "diting: kaboom"
    assert "Traceback" not in err


def test_main_guard_debug_reraises(monkeypatch):
    def boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(cli, "_dispatch", boom)
    monkeypatch.setattr("sys.argv", ["diting", "once"])
    monkeypatch.setenv("DITING_DEBUG", "1")
    with pytest.raises(RuntimeError, match="kaboom"):
        cli.main()


def test_main_guard_passes_systemexit_code_through(monkeypatch):
    def usage_exit():
        raise SystemExit(2)
    monkeypatch.setattr(cli, "_dispatch", usage_exit)
    monkeypatch.setattr("sys.argv", ["diting", "analyze", "--bogus"])
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 2


def test_main_guard_emits_json_error_under_json(monkeypatch, capsys):
    def boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(cli, "_dispatch", boom)
    monkeypatch.setattr("sys.argv", ["diting", "analyze", "--json", "x.jsonl"])
    monkeypatch.delenv("DITING_DEBUG", raising=False)
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 1
    obj = _json.loads(capsys.readouterr().err.strip())
    assert obj == {"error": "kaboom", "code": 1}


def test_for_llm_is_boolean_does_not_eat_input(tmp_path, monkeypatch, capsys):
    """The reported crash: `--for-llm <log>` must treat the log as input,
    not as the out-path. With no -o it writes one file to cwd."""
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: False)
    log = tmp_path / "diting-x.jsonl"
    log.write_text(
        '{"type":"session_meta","ts":"2026-05-07T22:00:00+00:00","scene":"home"}\n'
        '{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:01+00:00"}\n'
    )
    monkeypatch.chdir(tmp_path)
    cli._run_analyze(["--for-llm", str(log)])  # the crashing arg order
    files = list(tmp_path.glob("diting-analysis-for-llm-*.md"))
    assert len(files) == 1 and files[0].read_text().strip()


def test_for_llm_out_path_is_a_non_md_file_is_usage_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: False)
    log = tmp_path / "diting-x.jsonl"
    log.write_text('{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:00+00:00"}\n')
    afile = tmp_path / "not-a-dir"  # exists, not a directory, no .md suffix
    afile.write_text("x")
    with pytest.raises(SystemExit) as ei:
        cli._run_analyze([str(log), "--for-llm", "-o", str(afile)])
    assert ei.value.code == 2


def test_analyze_json_is_pure_parseable_document(tmp_path, capsys):
    log = tmp_path / "diting-x.jsonl"
    log.write_text(
        '{"type":"session_meta","ts":"2026-05-07T22:00:00+00:00","scene":"office"}\n'
        '{"type":"ble_device_seen","ts":"2026-05-07T22:00:01+00:00","vendor":"Acme","name":"d"}\n'
    )
    cli._run_analyze([str(log), "--json"])
    out = capsys.readouterr().out
    doc = _json.loads(out)  # the whole stdout is one JSON document
    assert doc["total_events"] == 2
    assert "temporal" in doc and "insights" in doc


def test_analyze_json_keys_stay_english_under_zh(tmp_path, capsys):
    from diting import i18n
    log = tmp_path / "diting-x.jsonl"
    log.write_text('{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:00+00:00"}\n')
    saved = i18n.get_lang()
    try:
        i18n.set_lang("zh")
        cli._run_analyze([str(log), "--json"])
        doc = _json.loads(capsys.readouterr().out)
        assert "total_events" in doc and "counts_by_type" in doc
    finally:
        i18n.set_lang(saved)


# ---------- agent-cli-foundation: verb redesign + aliases ----------

def _fake_connection():
    from diting.models import Connection
    from datetime import datetime, timezone
    return Connection(
        ssid="X", bssid="aa:bb:cc:dd:ee:ff", rssi_dbm=-50, noise_dbm=-94,
        tx_rate_mbps=300.0, channel=36, channel_width_mhz=80,
        channel_band="5 GHz", phy_mode="ax", security="WPA2",
        mcs_index=7, nss=2, timestamp=datetime.now(timezone.utc),
    )


class _FakeBackend:
    name = "fake"

    def __init__(self, conn):
        self._conn = conn

    def get_connection(self):
        return self._conn

    def permission_state(self):
        return "granted"


def test_canonical_verbs_dispatch():
    # The canonical verb set is the contract; aliases resolve onto it.
    assert cli._CANONICAL_VERBS == [
        "status", "scan", "stream", "calibrate",
        "analyze", "companion", "capabilities",
    ]
    for v in cli._CANONICAL_VERBS:
        assert cli._resolve_alias(v) == v  # canonical passes through


def test_deprecated_alias_forwards_to_canonical():
    assert cli._resolve_alias("once") == "status"
    assert cli._resolve_alias("watch") == "stream"
    assert cli._resolve_alias("monitor") == "stream"
    assert cli._resolve_alias("analyse") == "analyze"  # silent spelling alias


def test_alias_notice_on_stderr_only(monkeypatch, capsys):
    # `once --help` forwards to `status` (help short-circuits the backend).
    monkeypatch.setattr("sys.argv", ["diting", "once", "--help"])
    cli.main()
    cap = capsys.readouterr()
    assert cap.out.startswith("usage: diting status")
    assert "deprecated" not in cap.out  # never pollutes stdout
    assert "diting: 'once' is deprecated; use 'status'" in cap.err


def test_status_json_snapshot(monkeypatch, capsys):
    monkeypatch.setattr(cli, "MacOSWiFiBackend", lambda: _FakeBackend(_fake_connection()))
    with pytest.raises(SystemExit) as ei:
        cli._run_status(["--json"])
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert set(doc) == {"backend", "permission_state", "associated", "connection"}
    assert doc["associated"] is True and doc["connection"]["ssid"] == "X"


def test_status_not_associated_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(cli, "MacOSWiFiBackend", lambda: _FakeBackend(None))
    with pytest.raises(SystemExit) as ei:
        cli._run_status(["--json"])
    assert ei.value.code == 1
    doc = _json.loads(capsys.readouterr().out)
    assert doc["associated"] is False and doc["connection"] is None


# ---------- agent-cli-foundation: capabilities manifest ----------

def test_capabilities_manifest_shape():
    m = cli._capabilities_manifest()
    assert m["schema_version"] == cli.CAPABILITIES_SCHEMA_VERSION
    assert m["exit_code_convention"]["2"] == "usage error"
    for c in m["commands"]:
        assert {"name", "summary", "output", "exit_codes", "flags"} <= set(c)
        for f in c["flags"]:
            assert {"name", "type", "default", "repeatable"} == set(f)


def test_capabilities_covers_every_canonical_verb():
    m = cli._capabilities_manifest()
    assert {c["name"] for c in m["commands"]} == set(cli._CANONICAL_VERBS)


def test_capabilities_lists_deprecated_aliases():
    m = cli._capabilities_manifest()
    assert m["deprecated_aliases"] == {
        "once": "status", "watch": "stream", "monitor": "stream",
    }


def test_capabilities_json_is_pure_parseable_document(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["diting", "capabilities", "--json"])
    cli._run_capabilities(["--json"])
    doc = _json.loads(capsys.readouterr().out)
    assert [c["name"] for c in doc["commands"]] == cli._CANONICAL_VERBS


# ---------- agent-cli-foundation: scan one-shot ----------

def test_scan_default_runs_both(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_scan_wifi", lambda: [{"ssid": "AP"}])

    async def fake_ble(dur):
        return [{"identifier": "x"}]
    monkeypatch.setattr(cli, "_scan_ble", fake_ble)
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--json"]))
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc["wifi"] == [{"ssid": "AP"}] and doc["ble"] == [{"identifier": "x"}]


def test_scan_wifi_only_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_scan_wifi", lambda: [{"ssid": "AP"}])

    async def fake_ble(dur):  # must NOT be called
        raise AssertionError("ble should not run with --wifi only")
    monkeypatch.setattr(cli, "_scan_ble", fake_ble)
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--wifi", "--json"]))
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert set(doc) == {"wifi"}


def test_scan_sensor_error_is_structured(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_scan_wifi", lambda: [{"ssid": "AP"}])

    async def fake_ble(dur):
        raise RuntimeError("BLE unavailable (permission: denied)")
    monkeypatch.setattr(cli, "_scan_ble", fake_ble)
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--json"]))
    # wifi succeeded → exit 0 despite the ble error
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc["wifi"] == [{"ssid": "AP"}]
    assert doc["ble"]["error"] == "BLE unavailable (permission: denied)"
    assert doc["ble"]["code"] == 1


# ---------- agent-cli-foundation: duration grammar + help ----------

# ---------- headless-capture-engine: scan --lan/--mdns + stream --sensors ----------

def test_scan_lan_json_keying(monkeypatch, capsys):
    async def fake_lan(dur):
        return [{"ip": "10.0.0.5", "hostname": "nas"}]
    monkeypatch.setattr(cli, "_scan_lan", fake_lan)
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--lan", "--json"]))
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert set(doc) == {"lan"} and doc["lan"][0]["ip"] == "10.0.0.5"


def test_scan_mdns_json_keying(monkeypatch, capsys):
    async def fake_mdns(dur):
        return [{"name": "LivingRoom", "service_type": "_airplay._tcp"}]
    monkeypatch.setattr(cli, "_scan_mdns", fake_mdns)
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--mdns", "--json"]))
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert set(doc) == {"mdns"} and doc["mdns"][0]["name"] == "LivingRoom"


def test_scan_lan_error_is_structured(monkeypatch, capsys):
    async def fake_lan(dur):
        raise RuntimeError("not associated; cannot enumerate the LAN")
    monkeypatch.setattr(cli, "_scan_lan", fake_lan)
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--lan", "--json"]))
    assert ei.value.code == 1  # only sensor failed → no data
    doc = _json.loads(capsys.readouterr().out)
    assert doc["lan"]["error"].startswith("not associated")
    assert doc["lan"]["code"] == 1


def test_stream_sensors_default():
    assert cli._parse_sensors(None) == {"wifi", "latency", "rf"}


def test_stream_sensors_all_parses():
    from diting.capture import ALL_SENSORS
    assert cli._parse_sensors("all") == set(ALL_SENSORS)
    assert cli._parse_sensors("wifi,ble,lan") == {"wifi", "ble", "lan"}


def test_stream_sensors_unknown_token_exits_2(capsys):
    with pytest.raises(SystemExit) as ei:
        cli._parse_sensors("wifi,sonar")
    assert ei.value.code == 2
    assert "sonar" in capsys.readouterr().err


def test_capabilities_lists_sensors_flag():
    m = cli._capabilities_manifest()
    stream = next(c for c in m["commands"] if c["name"] == "stream")
    scan = next(c for c in m["commands"] if c["name"] == "scan")
    assert "--sensors" in {f["name"] for f in stream["flags"]}
    assert {"--lan", "--mdns"} <= {f["name"] for f in scan["flags"]}


def test_duration_grammar_suffix_forms():
    assert cli._parse_duration_seconds("30") == 30.0
    assert cli._parse_duration_seconds("45s") == 45.0
    assert cli._parse_duration_seconds("5m") == 300.0
    assert cli._parse_duration_seconds("2h") == 7200.0


def test_duration_bad_value_exits_2(monkeypatch):
    monkeypatch.setattr(cli, "_scan_wifi", lambda: [])
    with pytest.raises(SystemExit) as ei:
        _asyncio.run(cli._run_scan(["--duration", "soon", "--json"]))
    assert ei.value.code == 2


def test_subcommand_help_prints_and_exits_zero(monkeypatch, capsys):
    # Every subcommand's help carries Examples + Exit codes; the
    # json-object commands also advertise --json (stream is json-lines).
    json_cmds = {"status", "scan", "analyze", "capabilities"}
    for cmd in ("status", "scan", "stream", "analyze", "capabilities"):
        monkeypatch.setattr("sys.argv", ["diting", cmd, "--help"])
        cli.main()
        out = capsys.readouterr().out
        assert "Examples:" in out and "Exit codes:" in out
        if cmd in json_cmds:
            assert "--json" in out


def test_top_level_help_states_exit_codes_and_points_at_capabilities():
    usage = cli._usage()
    assert "Exit codes:" in usage
    assert "capabilities" in usage


def test_connection_to_dict_round_trips():
    from diting.models import Connection, connection_to_dict
    from datetime import datetime, timezone
    c = Connection(
        ssid="X", bssid="aa:bb:cc:dd:ee:ff", rssi_dbm=-50, noise_dbm=-94,
        tx_rate_mbps=300.0, channel=36, channel_width_mhz=80,
        channel_band="5 GHz", phy_mode="ax", security="WPA2",
        mcs_index=7, nss=2,
        timestamp=datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc),
    )
    d = connection_to_dict(c)
    assert d["ssid"] == "X"
    assert d["timestamp"] == "2026-06-09T12:00:00+00:00"
    assert _json.dumps(d)  # fully JSON-serializable


def test_for_llm_guidance_is_provider_neutral_and_names_deepseek(
    tmp_path, monkeypatch, capsys,
):
    """simplify-llm-bundle: the post-write guidance frames targets as 'any
    AI chat', confirms the clipboard copy, and lists DeepSeek among the
    examples (not just Claude / ChatGPT)."""
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: True)
    log = tmp_path / "diting-x.jsonl"
    log.write_text('{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:00+00:00"}\n')
    monkeypatch.chdir(tmp_path)
    cli._run_analyze([str(log), "--for-llm"])
    out = capsys.readouterr().out
    assert "any AI chat" in out
    assert "copied to clipboard" in out
    assert "deepseek.com" in out
    assert "gemini" in out.lower() and "kimi" in out.lower()


def test_for_llm_raw_references_original_no_rewrite(tmp_path, monkeypatch, capsys):
    """for-llm-raw: --raw references the existing log (no rewrite) and the
    guidance lists it to attach; the prompt mentions the raw log."""
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: False)
    log = tmp_path / "diting-x.jsonl"
    log.write_text(
        '{"type":"session_meta","ts":"2026-05-07T22:00:00+00:00","scene":"home"}\n'
        '{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:01+00:00","bssid":"aa:bb:cc:dd:ee:01","ssid":"Net"}\n'
    )
    monkeypatch.chdir(tmp_path)
    cli._run_analyze([str(log), "--for-llm", "--raw"])
    out = capsys.readouterr().out
    # only the briefing was written — no copy of the log
    briefings = list(tmp_path.glob("diting-analysis-for-llm-*.md"))
    assert len(briefings) == 1
    assert not list(tmp_path.glob("diting-raw-anonymized-*.jsonl"))
    assert "diting-x.jsonl" in out               # original referenced
    assert "attach the raw event log" in out
    assert "raw JSONL event log is attached" in briefings[0].read_text()


def test_raw_implies_for_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: False)
    log = tmp_path / "diting-x.jsonl"
    log.write_text('{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:00+00:00"}\n')
    monkeypatch.chdir(tmp_path)
    cli._run_analyze([str(log), "--raw"])  # no explicit --for-llm
    assert len(list(tmp_path.glob("diting-analysis-for-llm-*.md"))) == 1


def test_raw_anonymize_writes_scrubbed_log_with_matching_handles(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: False)
    log = tmp_path / "diting-x.jsonl"
    log.write_text(
        '{"type":"link_state","state":"associated","ts":"2026-05-07T22:00:00+00:00","bssid":"aa:bb:cc:dd:ee:01","ssid":"HomeNet"}\n'
        '{"type":"ble_device_seen","ts":"2026-05-07T22:00:01+00:00","identifier":"uuid-1","name":"Joe iPhone","vendor":"Apple, Inc."}\n'
        '{"type":"latency_spike","ts":"2026-05-07T22:00:02+00:00","target_ip":"1.1.1.1","rtt_ms":300}\n'
    )
    monkeypatch.chdir(tmp_path)
    cli._run_analyze([str(log), "--for-llm", "--raw", "--anonymize"])
    scrubbed = list(tmp_path.glob("diting-raw-anonymized-*.jsonl"))
    assert len(scrubbed) == 1
    import json as _json
    blob = scrubbed[0].read_text()
    rows = [_json.loads(line) for line in blob.splitlines()]
    # real identifiers gone, handles in; public IP + vendor verbatim
    assert "aa:bb:cc:dd:ee:01" not in blob and "HomeNet" not in blob
    assert "Joe iPhone" not in blob              # device name scrubbed
    assert "AP_1" in blob and "SSID_1" in blob and "NAME_1" in blob
    assert any(r.get("target_ip") == "1.1.1.1" for r in rows)  # public IP kept
    assert "Apple, Inc." in blob                 # vendor preserved


def test_scrub_event_maps_identifiers_keeps_public_ip():
    from diting.analyze import Anonymizer, scrub_event
    anon = Anonymizer()
    ev = {
        "type": "lan_host_dhcp_rotation", "mac": "de:ad:be:ef:00:01",
        "new_ip": "192.168.1.5", "target_ip": "8.8.8.8",
        "hostname": "nas.local", "name": "Bob Mac", "vendor": "Acme",
    }
    out = scrub_event(ev, anon)
    assert out["mac"].startswith("MAC_")
    assert out["new_ip"].startswith("IP_")       # RFC1918 → handle
    assert out["target_ip"] == "8.8.8.8"          # public IP verbatim
    assert out["hostname"].startswith("HOST_")
    assert out["name"].startswith("NAME_")
    assert out["vendor"] == "Acme"                # not identifying
    assert ev["mac"] == "de:ad:be:ef:00:01"       # input not mutated
