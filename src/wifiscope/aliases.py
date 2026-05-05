"""BSSID alias loader.

YAML format:

    40:fe:95:8a:3c:58: AX51-E_4-B2
    bc:22:47:ca:79:4a: AX60_2

The file lives at `$XDG_CONFIG_HOME/wifiscope/aliases.yaml` (defaults
to `~/.config/wifiscope/aliases.yaml`); override with the
`WIFISCOPE_ALIASES` environment variable. A missing file is fine —
`load_aliases()` returns an empty dict and the UI falls back to the
raw BSSID. Malformed YAML is *not* tolerated; we raise so a typo
during config editing is loud rather than silent.

BSSIDs are normalized to lowercase on load so lookup is
case-insensitive — H3C / Apple / etc. all spit MAC strings in
slightly different cases.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "wifiscope" / "aliases.yaml"


def resolve_config_path() -> Path:
    override = os.environ.get("WIFISCOPE_ALIASES")
    return Path(override).expanduser() if override else default_config_path()


def load_aliases(path: Path | None = None) -> dict[str, str]:
    p = path or resolve_config_path()
    if not p.exists():
        return {}
    with p.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{p}: top-level YAML must be a mapping, got {type(data).__name__}"
        )
    return {str(k).lower().strip(): str(v) for k, v in data.items()}


def format_bssid(bssid: str | None, aliases: dict[str, str]) -> str:
    """Render a BSSID with its alias if known, e.g. 'AX51-E_4-B2 (40:fe:...)'."""
    if bssid is None:
        return "n/a"
    alias = aliases.get(bssid.lower())
    return f"{alias} ({bssid})" if alias else bssid
