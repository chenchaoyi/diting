"""Guard the PyInstaller frozen-build command (fix-frozen-companion-crypto).

CI does not run a full frozen build per-PR (only the release workflow on a
tag does), so a lazy-imported native dep can silently fall out of the bundle
and only crash a shipped binary — which is exactly how PyNaCl's
`_cffi_backend` went missing and crashed `k` (the companion screen) with
`ModuleNotFoundError: No module named '_cffi_backend'`. This asserts the
collection flags stay in the command.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_frozen.py"


def _cmd() -> list[str]:
    spec = importlib.util.spec_from_file_location("build_frozen", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod._pyinstaller_cmd()


def test_frozen_cmd_collects_pynacl_and_cffi_backend():
    """PyNaCl is lazy-imported (companion crypto), so it must be force-
    collected — including the `_cffi_backend` C extension cffi loads at
    runtime — or the frozen `k`/pairing path crashes."""
    cmd = _cmd()
    # `--collect-all nacl` / `--collect-all cffi` appear as adjacent pairs.
    assert ("--collect-all", "nacl") in list(zip(cmd, cmd[1:]))
    assert ("--collect-all", "cffi") in list(zip(cmd, cmd[1:]))
    assert ("--hidden-import", "_cffi_backend") in list(zip(cmd, cmd[1:]))


def test_frozen_cmd_keeps_core_collects():
    """A weak smoke that the rest of the lazy/data-file collection is intact
    (so this guard fails loudly if the command is gutted)."""
    pairs = set(zip(_cmd(), _cmd()[1:]))
    for pkg in ("pyobjc_core", "pyobjc_framework_CoreWLAN", "textual", "zeroconf"):
        assert ("--collect-all", pkg) in pairs, pkg
