"""Unit tests for scripts/tui_snapshot.py.

scripts/ is not a package, so we import the module by path.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_snapshot_module():
    name = "tui_snapshot_under_test"
    if name in sys.modules:
        return sys.modules[name]
    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        name, repo_root / "scripts" / "tui_snapshot.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec — @dataclass uses
    # sys.modules.get(cls.__module__) during class construction.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_audit_helper_pin_uses_installed_when_env_unset(
    monkeypatch, tmp_path,
):
    """Explore mode pins DITING_HELPER to the installed bundle when
    one exists and the user hasn't already set DITING_HELPER. That
    keeps the bundle's existing TCC grants in play and stops
    locationd from re-prompting on every scan tick during /tui-audit.
    """
    mod = _load_snapshot_module()

    fake_home = tmp_path / "home"
    installed = (
        fake_home
        / "Library"
        / "Application Support"
        / "diting"
        / "diting-tianer.app"
    )
    installed.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("DITING_HELPER", raising=False)

    mod._prefer_installed_helper_for_audit()

    assert os.environ["DITING_HELPER"] == str(installed)


def test_audit_helper_pin_skips_when_no_installed_bundle(
    monkeypatch, tmp_path,
):
    mod = _load_snapshot_module()

    fake_home = tmp_path / "empty_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("DITING_HELPER", raising=False)

    mod._prefer_installed_helper_for_audit()

    assert "DITING_HELPER" not in os.environ


def test_audit_helper_pin_respects_existing_override(
    monkeypatch, tmp_path,
):
    """An explicit DITING_HELPER (e.g. a contributor pointing at
    their local rebuild) wins over the auto-pin."""
    mod = _load_snapshot_module()

    fake_home = tmp_path / "home"
    installed = (
        fake_home
        / "Library"
        / "Application Support"
        / "diting"
        / "diting-tianer.app"
    )
    installed.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("DITING_HELPER", "/opt/contributor/rebuild.app")

    mod._prefer_installed_helper_for_audit()

    assert os.environ["DITING_HELPER"] == "/opt/contributor/rebuild.app"
