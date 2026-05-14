"""diting — macOS terminal listening post for Wi-Fi, BLE, link health.

`__version__` is sourced from `pyproject.toml` via
`importlib.metadata` so the CLI's `--version` flag, the TUI's title
bar, and the package's dist-info all agree without us hand-
maintaining a duplicate constant (which the v0.5.0 stale entry in
this file proved we will forget to bump).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("diting")
except PackageNotFoundError:
    __version__ = "0+unknown"
