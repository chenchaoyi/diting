"""Tests for :mod:`diting.scene` — scene resolution and defaults."""
from __future__ import annotations

import pytest

from diting import scene


def test_valid_scenes_returns_exactly_four_canonical_names() -> None:
    assert scene.valid_scenes() == ("home", "office", "public", "audit")


def test_default_scene_is_home() -> None:
    """`home` is the default — preserves the v1.5.0 baseline so a user
    who upgrades without passing --scene sees no behaviour change."""
    resolved, source = scene.resolve_scene(cli_value=None, env={})
    assert resolved == "home"
    assert source == "default"


def test_resolve_cli_wins_over_env() -> None:
    """CLI flag is the highest-priority scene source."""
    resolved, source = scene.resolve_scene(
        cli_value="audit",
        env={"DITING_SCENE": "office"},
    )
    assert resolved == "audit"
    assert source == "cli"


def test_resolve_env_fills_in_when_no_cli() -> None:
    resolved, source = scene.resolve_scene(
        cli_value=None,
        env={"DITING_SCENE": "office"},
    )
    assert resolved == "office"
    assert source == "env"


def test_resolve_blank_env_falls_to_default() -> None:
    """`DITING_SCENE= diting` should be treated as 'cleared', not as
    'set to empty string'. Match the existing DITING_LOG / lang
    blank-env semantics."""
    resolved, source = scene.resolve_scene(
        cli_value=None,
        env={"DITING_SCENE": ""},
    )
    assert resolved == "home"
    assert source == "default"


def test_resolve_invalid_env_warns_and_defaults(capsys) -> None:
    """A broken shell rc shouldn't break diting's startup. Warn on
    stderr, fall back to default."""
    resolved, source = scene.resolve_scene(
        cli_value=None,
        env={"DITING_SCENE": "shop"},
    )
    assert resolved == "home"
    assert source == "default"
    err = capsys.readouterr().err
    assert "DITING_SCENE" in err
    assert "shop" in err


def test_resolve_invalid_cli_raises_value_error() -> None:
    """Invalid CLI value MUST raise — the CLI layer turns this into a
    clean sys.exit with a clear error. Bad CLI input is an error in a
    way a bad shell rc isn't."""
    with pytest.raises(ValueError) as excinfo:
        scene.resolve_scene(cli_value="shop", env={})
    assert "shop" in str(excinfo.value)
    # The error names the valid scenes so the user can correct.
    for name in scene.valid_scenes():
        assert name in str(excinfo.value)


def test_set_scene_invalid_raises() -> None:
    with pytest.raises(ValueError):
        scene.set_scene("shop")


def test_set_scene_get_scene_roundtrip() -> None:
    original = scene.get_scene()
    try:
        scene.set_scene("office")
        assert scene.get_scene() == "office"
        scene.set_scene("home")
        assert scene.get_scene() == "home"
    finally:
        scene.set_scene(original)


def test_scene_defaults_home_presence_gate_is_5s() -> None:
    """home matches v1.5.0's pre-scene default. NO behavioural break
    for upgrading users who don't pass --scene."""
    assert scene.scene_defaults("home")["ble_presence_gate_s"] == 5.0


def test_scene_defaults_office_presence_gate_is_15s() -> None:
    assert scene.scene_defaults("office")["ble_presence_gate_s"] == 15.0


def test_scene_defaults_public_presence_gate_is_30s() -> None:
    assert scene.scene_defaults("public")["ble_presence_gate_s"] == 30.0


def test_scene_defaults_audit_presence_gate_is_zero() -> None:
    """audit explicitly disables the gate — equivalent to passing
    --ble-presence-gate 0."""
    assert scene.scene_defaults("audit")["ble_presence_gate_s"] == 0.0


def test_scene_defaults_includes_llm_prior_for_every_scene() -> None:
    """Each scene's llm_prior is the load-bearing context the LLM
    bundle injects. Empty or missing is a regression."""
    for name in scene.valid_scenes():
        prior = scene.scene_defaults(name).get("llm_prior")
        assert isinstance(prior, str) and len(prior) > 20, (
            f"scene {name!r} has missing or trivially-short llm_prior"
        )


def test_scene_defaults_unknown_scene_raises() -> None:
    with pytest.raises(ValueError):
        scene.scene_defaults("shop")


def test_callers_can_read_knobs_defensively() -> None:
    """The dict.get() pattern lets future scene knobs land without
    breaking older callers. Critical for the P3 follow-up that will
    add roam_notify_threshold / bonjour_categories / lan_inventory."""
    assert scene.scene_defaults("home").get(
        "future_knob", "fallback"
    ) == "fallback"
