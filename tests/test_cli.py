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
