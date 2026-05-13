"""Build a frozen, standalone ``diting`` binary via PyInstaller.

Produces ``dist/diting/diting`` containing the Python interpreter
plus every runtime dep (Textual, pyobjc bridges, zeroconf, PyYAML)
so end users don't need Python on their machine. The output of this
script is the ``bin/diting`` half of the release tarball; the
Swift helper bundle is packaged alongside by
``scripts/package_release.sh``.

Run via:

    uv run --group release python scripts/build_frozen.py

Output:
    dist/diting/                   # PyInstaller --onedir layout
    └── diting                     # entry-point binary
    ├── _internal/
    │   └── ...                    # Python stdlib + deps + ObjC frameworks
    └── ...

The ``--onedir`` layout (vs ``--onefile``) trades a slightly bigger
directory tree for a much faster first-run (no extraction to
/tmp), which matters because every Textual repaint goes through
the frozen ``site-packages``.

PyInstaller is intentionally not a runtime dependency — it lives
in the ``release`` dependency-group in pyproject.toml, brought in
only when this script (or CI) runs.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"


def _check_pyinstaller_available() -> None:
    """Hard-fail with a useful message if PyInstaller isn't installed.

    Catches the common "I forgot to install the release group" case
    so the user sees a clear pointer instead of an opaque
    ModuleNotFoundError mid-build.
    """
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "PyInstaller is not installed.\n"
            "Install the release dependency group with:\n"
            "    uv sync --group release\n"
        )
        sys.exit(1)


def _clean_previous_build() -> None:
    """Wipe stale dist/ + build/ so the next run produces a clean
    artefact. PyInstaller updates in place but stray files from a
    previous build (e.g. a renamed entry point) hang around and
    bloat the tarball."""
    for d in (DIST_DIR, BUILD_DIR):
        if d.is_dir():
            shutil.rmtree(d)


def main() -> None:
    _check_pyinstaller_available()
    _clean_previous_build()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        # Single binary name `diting` (no .app, no version suffix).
        "--name", "diting",
        # No console window stays attached on macOS — Textual takes
        # over the terminal it was launched from. (`--windowed` would
        # break that.)
        "--console",
        # pyobjc lazy-loads ObjC framework bridges via per-framework
        # distributions; PyInstaller's static analysis misses them.
        # --collect-all walks each package's resource / metadata
        # tree so the bridge .so + the bundled `.bridgesupport`
        # files travel with us.
        "--collect-all", "pyobjc_core",
        "--collect-all", "pyobjc_framework_Cocoa",
        "--collect-all", "pyobjc_framework_CoreWLAN",
        "--collect-all", "pyobjc_framework_SystemConfiguration",
        # Textual ships TCSS theme files + the Rich console as data
        # files; --collect-all is the safest way to keep both.
        "--collect-all", "textual",
        "--collect-all", "rich",
        # zeroconf uses ifaddr's bundled wheels; collect-all keeps
        # them.
        "--collect-all", "zeroconf",
        "--collect-all", "ifaddr",
        # Ship the bundled OUI / service-type / Bonjour-category
        # data files. They live under src/diting/data/ and are read
        # via importlib.resources at runtime.
        "--add-data", f"{REPO_ROOT / 'src' / 'diting' / 'data'}:diting/data",
        # Strip debug symbols from binaries. Knocks ~6 MB off a
        # release build at no runtime cost.
        "--strip",
        # The entry script — the CLI dispatcher that pyproject.toml's
        # [project.scripts] maps `diting` to.
        str(REPO_ROOT / "src" / "diting" / "cli.py"),
    ]

    # Invoke PyInstaller; let its output stream straight to our
    # stdout/stderr so build progress shows up live in CI logs.
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)

    binary = DIST_DIR / "diting" / "diting"
    if not binary.is_file():
        sys.stderr.write(
            f"Build finished but {binary} is missing.\n"
            "Check PyInstaller output above for hidden errors.\n"
        )
        sys.exit(2)

    print(f"\nbuilt: {binary}")
    print(f"size: {binary.stat().st_size / (1024 * 1024):.1f} MB (entry binary only)")
    print(
        "Bundle this directory (dist/diting/) as `bin/` inside the "
        "release tarball; see scripts/package_release.sh."
    )


if __name__ == "__main__":
    main()
