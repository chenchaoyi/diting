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
