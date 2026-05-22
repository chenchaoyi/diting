"""CLI-level smoke tests.

These exercise `diting.cli.main` through `sys.argv` patching — close
to how the entry-point script invokes it, but without forking a real
process. Subcommand internals have their own tests; this file owns
the top-level flag dispatch.
"""
from __future__ import annotations

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
