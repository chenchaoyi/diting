"""Per-network scene assignment via ``scenes.yaml``.

Mirrors the ``aps.yaml`` pattern: optional user-curated file in cwd
(override with ``DITING_SCENES_FILE``), absent → empty registry,
malformed → stderr warning + empty registry. diting NEVER writes
back to this file; it's human-curated only.

Schema::

    networks:
      - ssid: HomeNet
        scene: home
      - ssid: Meituan
        scene: office
      - gateway_mac: 14:51:7e:71:5a:1a
        scene: office

Resolution semantics:

- Match by ``ssid`` (primary) or ``gateway_mac`` (fallback).
- When both could match the current connection, ``gateway_mac`` wins —
  it's more specific (think shared SSIDs like ``eduroam``).
- Invalid ``scene`` values in individual entries SHALL be skipped
  with a stderr warning; the rest of the file still loads.

Contract pinned in ``openspec/specs/scenes/spec.md``.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import scene as _scene_mod


@dataclass(frozen=True, slots=True)
class SceneAssignment:
    """One yaml entry: a network identifier plus the scene it gets."""
    scene: str
    ssid: str | None = None
    gateway_mac: str | None = None


@dataclass(frozen=True, slots=True)
class SceneRegistry:
    """In-memory view of the loaded ``scenes.yaml``. The lookup
    methods return a ``SceneAssignment`` (or None) so the caller can
    surface the match key in the banner."""
    assignments: tuple[SceneAssignment, ...] = field(default_factory=tuple)

    def lookup_by_ssid(self, ssid: str | None) -> SceneAssignment | None:
        if not ssid:
            return None
        for a in self.assignments:
            if a.ssid is not None and a.ssid == ssid:
                return a
        return None

    def lookup_by_gateway_mac(
        self, mac: str | None,
    ) -> SceneAssignment | None:
        if not mac:
            return None
        target = mac.lower()
        for a in self.assignments:
            if a.gateway_mac is not None and a.gateway_mac.lower() == target:
                return a
        return None

    def lookup(
        self,
        *,
        ssid: str | None = None,
        gateway_mac: str | None = None,
    ) -> SceneAssignment | None:
        """Match by gateway_mac first (more specific), then SSID."""
        hit = self.lookup_by_gateway_mac(gateway_mac)
        if hit is not None:
            return hit
        return self.lookup_by_ssid(ssid)


def default_scenes_path() -> Path:
    """``./scenes.yaml`` in cwd — mirrors :func:`network.default_config_path`.
    Resolved at lookup time (not import time)."""
    return Path("scenes.yaml")


def resolve_scenes_path() -> Path:
    override = os.environ.get("DITING_SCENES_FILE")
    return Path(override).expanduser() if override else default_scenes_path()


def load_scenes_registry(path: Path | None = None) -> SceneRegistry:
    """Load ``scenes.yaml`` into a :class:`SceneRegistry`.

    Permissive by design: missing file → empty registry, malformed
    file → stderr warning + empty registry, invalid individual entry
    → stderr warning + skip just that entry. NEVER raises.
    """
    p = path or resolve_scenes_path()
    if not p.exists():
        return SceneRegistry()
    try:
        with p.open() as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        print(
            f"warning: {p}: scenes.yaml is not parseable YAML ({exc}); "
            f"ignoring file",
            file=sys.stderr,
        )
        return SceneRegistry()
    if not isinstance(raw, dict):
        print(
            f"warning: {p}: top-level must be a mapping (`networks:` list); "
            f"ignoring file",
            file=sys.stderr,
        )
        return SceneRegistry()
    networks = raw.get("networks")
    if networks is None:
        return SceneRegistry()
    if not isinstance(networks, list):
        print(
            f"warning: {p}: `networks` must be a list; ignoring file",
            file=sys.stderr,
        )
        return SceneRegistry()

    valid_scenes = _scene_mod.valid_scenes()
    out: list[SceneAssignment] = []
    for idx, entry in enumerate(networks):
        if not isinstance(entry, dict):
            print(
                f"warning: {p}: networks[{idx}] is not a mapping; skipping",
                file=sys.stderr,
            )
            continue
        scene_name = entry.get("scene")
        if scene_name not in valid_scenes:
            print(
                f"warning: {p}: networks[{idx}] has invalid scene "
                f"{scene_name!r}; must be one of "
                f"{', '.join(valid_scenes)}; skipping entry",
                file=sys.stderr,
            )
            continue
        ssid = entry.get("ssid")
        gateway_mac = entry.get("gateway_mac")
        if ssid is None and gateway_mac is None:
            print(
                f"warning: {p}: networks[{idx}] has neither ssid nor "
                f"gateway_mac; skipping",
                file=sys.stderr,
            )
            continue
        out.append(SceneAssignment(
            scene=scene_name,
            ssid=ssid if isinstance(ssid, str) and ssid else None,
            gateway_mac=(
                gateway_mac if isinstance(gateway_mac, str) and gateway_mac
                else None
            ),
        ))
    return SceneRegistry(assignments=tuple(out))
