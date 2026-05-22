"""Scene awareness — diting's notion of "where the user is right now".

Four named environments that each carry a set of default knobs and a
plain-language baseline expectation that downstream tools (the
analyzer, the LLM bundle) use to interpret per-event data correctly.
Contract pinned in ``openspec/specs/scenes/spec.md``.

Module-level state, mirrors :mod:`diting.i18n`'s ``_lang`` pattern: the
active scene is set once at process startup by the CLI and read
everywhere via :func:`get_scene`. Tests use :func:`set_scene` to force
a specific scene for deterministic behaviour.

The four scenes (lowercase ASCII names):

- ``home`` (default) — sparse RF, stable network, you know everyone.
- ``office`` — dense enterprise WiFi, continuous BLE churn.
- ``public`` — cafe / train / plane / public WiFi, almost everything
  is passers-by.
- ``audit`` — actively investigating, record everything.
"""
from __future__ import annotations

import os
import sys
from typing import Any

HOME = "home"
OFFICE = "office"
PUBLIC = "public"
AUDIT = "audit"

_VALID: tuple[str, ...] = (HOME, OFFICE, PUBLIC, AUDIT)
_DEFAULT = HOME

# Source-of-resolution constants — what told us which scene to use.
SOURCE_CLI = "cli"
SOURCE_ENV = "env"
SOURCE_YAML = "yaml"      # scenes.yaml matched the current network
SOURCE_AUTO = "auto"      # heuristic classified from active connection signals
SOURCE_DEFAULT = "default"

# Heuristic threshold — BSSID count above this classifies as office.
# Empirically: corp floors easily see 60+ on 5 GHz alone; typical
# apartments see 10-20 from neighbouring residences. 30 is the
# crossover. Tuning is a future concern; today it's a constant so the
# behaviour is reproducible.
_OFFICE_BSSID_THRESHOLD = 30

_scene: str = _DEFAULT


def get_scene() -> str:
    """Return the active scene name."""
    return _scene


def set_scene(scene: str) -> None:
    """Force the active scene. Callers are typically the CLI on
    startup; tests use this to flip scenes without going through env
    var / arg parsing.
    """
    global _scene
    if scene not in _VALID:
        raise ValueError(
            f"unsupported scene: {scene!r}; "
            f"must be one of {', '.join(_VALID)}"
        )
    _scene = scene


def valid_scenes() -> tuple[str, ...]:
    """Tuple of the four canonical scene names. Stable across the
    `scenes` capability."""
    return _VALID


def resolve_scene(
    cli_value: str | None,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Pick the active scene from CLI > env > default.

    Returns ``(scene, source)`` where ``source`` is one of
    :data:`SOURCE_CLI`, :data:`SOURCE_ENV`, :data:`SOURCE_DEFAULT`.

    - ``cli_value`` is the value parsed from ``--scene`` (or ``None``
      if the flag was absent). An invalid CLI value raises
      :class:`ValueError` — the CLI layer turns that into a
      clean ``sys.exit``.
    - ``env`` defaults to :data:`os.environ`; a blank
      ``DITING_SCENE`` is treated as absent so a parent shell can
      clear it with ``DITING_SCENE= diting``.
    - An invalid env-var value triggers a stderr warning and falls
      back to the default rather than exiting — a broken shell rc
      should not break startup.
    """
    if cli_value is not None:
        if cli_value not in _VALID:
            raise ValueError(
                f"unsupported scene: {cli_value!r}; "
                f"must be one of {', '.join(_VALID)}"
            )
        return cli_value, SOURCE_CLI
    if env is None:
        env = dict(os.environ)
    raw = (env.get("DITING_SCENE") or "").strip()
    if not raw:
        return _DEFAULT, SOURCE_DEFAULT
    if raw not in _VALID:
        print(
            f"warning: DITING_SCENE={raw!r} is not a valid scene; "
            f"using {_DEFAULT!r} default",
            file=sys.stderr,
        )
        return _DEFAULT, SOURCE_DEFAULT
    return raw, SOURCE_ENV


def scene_defaults(scene: str) -> dict[str, Any]:
    """Return the per-scene knob map.

    Keys defined in Phase 1:

    - ``ble_presence_gate_s`` (float) — BLE anonymous-advert presence
      gate, seconds.
    - ``llm_prior`` (str) — short plain-language baseline expectation,
      injected into ``--for-llm`` prompts so the LLM interprets the
      data under the right priors.

    Future phases may add more keys (``roam_notify_threshold``,
    ``bonjour_categories_visible``, ``lan_inventory_default``,
    ``event_throttle``). Callers SHALL read defensively with
    ``.get(name, default)`` so adding a key isn't a breaking change.

    Raises :class:`ValueError` on unknown scene names.
    """
    if scene not in _VALID:
        raise ValueError(
            f"unsupported scene: {scene!r}; "
            f"must be one of {', '.join(_VALID)}"
        )
    return _DEFAULTS[scene]


# ---------- per-scene knob values ----------
#
# `home` matches v1.5.0's pre-scene default exactly so a user who
# upgrades and does not pass --scene sees identical behaviour. `office`
# triples it to absorb more Continuity RPA churn. `public` is the
# noisiest environment and gets the most aggressive gate. `audit`
# turns the gate off entirely — equivalent to --ble-presence-gate 0.

_DEFAULTS: dict[str, dict[str, Any]] = {
    HOME: {
        "ble_presence_gate_s": 5.0,
        "llm_prior": (
            "small known network — novelty matters. Sparse RF, "
            "stable AP, ~10-15 BLE devices typical. Look for new "
            "identifiers and unexpected roams."
        ),
    },
    OFFICE: {
        "ble_presence_gate_s": 15.0,
        "llm_prior": (
            "dense enterprise environment — baseline churn expected. "
            "50+ BLE devices, 100+ BSSIDs typical. Continuous Apple "
            "Continuity RPA rotation; roams every 5-15 min from AP "
            "density. Look for departures from this baseline, not "
            "the baseline itself."
        ),
    },
    PUBLIC: {
        "ble_presence_gate_s": 30.0,
        "llm_prior": (
            "hostile shared WiFi — cardinality is noise. Cafe / "
            "train / plane / public hotspot. Almost every identifier "
            "is a passer-by. LAN-side hosts are untrusted strangers. "
            "Treat per-identifier ranks as noise; aggregate counts "
            "and timing are still meaningful."
        ),
    },
    AUDIT: {
        "ble_presence_gate_s": 0.0,
        "llm_prior": (
            "raw capture — no filtering applied. User is actively "
            "investigating (security research / device debug / "
            "forensics). Every event in the log is intentional. "
            "Treat ephemeral identifiers and short-lived signals "
            "as potentially meaningful."
        ),
    },
}


def classify_environment(
    security: str | None,
    visible_bssid_count: int,
    ssid: str | None = None,
) -> tuple[str, str]:
    """Heuristic scene classifier — no side effects, pure function.

    Returns ``(scene, reason)``. The reason is a short human-readable
    string the CLI banner surfaces so the user can see why diting
    picked the scene it did.

    Rules in priority order (first match wins):

    1. ``security`` contains "Enterprise" (case-insensitive — matches
       WPA2 Enterprise / WPA3 Enterprise / WPA-Enterprise) → ``office``.
       Enterprise auth is the strongest single signal that the user is
       on a corp / institutional network.
    2. ``visible_bssid_count >= 30`` → ``office``. Catches dense urban
       offices, malls, conference centres without enterprise auth.
    3. otherwise → ``home``. The conservative fallback.

    Note: ``public`` is intentionally NOT auto-classified. Open WiFi
    exists in homes (neighbour's), offices (guest network), and public
    spaces; without active probing diting cannot distinguish them.
    Public scene stays opt-in via ``--scene public``.
    """
    if security and "enterprise" in security.lower():
        return OFFICE, f"{security} auth"
    if visible_bssid_count >= _OFFICE_BSSID_THRESHOLD:
        return OFFICE, f"{visible_bssid_count} BSSIDs visible"
    return HOME, "no enterprise auth, sparse BSSID surface"
