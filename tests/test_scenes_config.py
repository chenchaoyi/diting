"""Tests for :mod:`diting.scenes_config` — scenes.yaml loader + lookup."""
from __future__ import annotations

import textwrap

import pytest

from diting import scenes_config


def _write(path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip())


def test_missing_file_returns_empty_registry(tmp_path) -> None:
    """No file → empty registry, no error, no warning. The default
    diting install has no scenes.yaml; it must not crash on startup."""
    p = tmp_path / "nope.yaml"
    reg = scenes_config.load_scenes_registry(p)
    assert reg.assignments == ()


def test_simple_ssid_match(tmp_path) -> None:
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        networks:
          - ssid: HomeNet
            scene: home
          - ssid: Meituan
            scene: office
    """)
    reg = scenes_config.load_scenes_registry(p)
    assert len(reg.assignments) == 2
    hit = reg.lookup(ssid="Meituan")
    assert hit is not None
    assert hit.scene == "office"
    assert hit.ssid == "Meituan"


def test_unknown_ssid_returns_none(tmp_path) -> None:
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        networks:
          - ssid: HomeNet
            scene: home
    """)
    reg = scenes_config.load_scenes_registry(p)
    assert reg.lookup(ssid="OtherNet") is None


def test_gateway_mac_match_case_insensitive(tmp_path) -> None:
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        networks:
          - gateway_mac: 14:51:7E:71:5A:1A
            scene: office
    """)
    reg = scenes_config.load_scenes_registry(p)
    hit = reg.lookup(gateway_mac="14:51:7e:71:5a:1a")
    assert hit is not None
    assert hit.scene == "office"


def test_gateway_mac_wins_over_ssid(tmp_path) -> None:
    """When the current connection's SSID matches one entry AND its
    gateway MAC matches another, the gateway_mac (more specific) wins.
    The use case is shared SSIDs (eduroam everywhere, multiple homes
    with the same name)."""
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        networks:
          - ssid: eduroam
            scene: home
          - gateway_mac: 14:51:7e:71:5a:1a
            scene: office
    """)
    reg = scenes_config.load_scenes_registry(p)
    hit = reg.lookup(ssid="eduroam", gateway_mac="14:51:7e:71:5a:1a")
    assert hit is not None
    assert hit.scene == "office"
    assert hit.gateway_mac == "14:51:7e:71:5a:1a"


def test_invalid_scene_name_in_entry_is_skipped(tmp_path, capsys) -> None:
    """A typo'd scene name in one entry MUST NOT break the file load.
    The bad entry is skipped with a stderr warning; the rest still
    loads."""
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        networks:
          - ssid: HomeNet
            scene: home
          - ssid: Office1
            scene: shop
          - ssid: Office2
            scene: office
    """)
    reg = scenes_config.load_scenes_registry(p)
    assert len(reg.assignments) == 2
    assert reg.lookup(ssid="Office1") is None
    assert reg.lookup(ssid="Office2") is not None
    err = capsys.readouterr().err
    assert "shop" in err


def test_entry_without_match_key_is_skipped(tmp_path, capsys) -> None:
    """An entry with neither ssid nor gateway_mac has no way to match
    a connection — skip it + warn so the user fixes their yaml."""
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        networks:
          - scene: office
          - ssid: Real
            scene: office
    """)
    reg = scenes_config.load_scenes_registry(p)
    assert len(reg.assignments) == 1
    err = capsys.readouterr().err
    assert "ssid" in err.lower() or "gateway_mac" in err.lower()


def test_malformed_top_level_is_tolerated(tmp_path, capsys) -> None:
    """A top-level list or scalar (not a mapping) is a user typo. Warn
    + return empty registry; never crash."""
    p = tmp_path / "scenes.yaml"
    _write(p, """\
        - Meituan
        - HomeNet
    """)
    reg = scenes_config.load_scenes_registry(p)
    assert reg.assignments == ()
    err = capsys.readouterr().err
    assert "mapping" in err.lower() or "ignoring" in err.lower()


def test_unparseable_yaml_is_tolerated(tmp_path, capsys) -> None:
    """A YAML syntax error (broken file in the middle of editing) must
    NOT crash diting. Warn + return empty registry."""
    p = tmp_path / "scenes.yaml"
    p.write_text("networks: [\n  - ssid: Meituan\n    scene: office\n")  # missing closing ]
    reg = scenes_config.load_scenes_registry(p)
    assert reg.assignments == ()
    err = capsys.readouterr().err
    assert "scenes.yaml" in err or "YAML" in err.upper() or "parseable" in err.lower()


def test_empty_file_is_empty_registry(tmp_path) -> None:
    """Empty file ≠ missing file; both yield an empty registry. No
    warning either — empty is valid (user might be using the file
    only for the comments)."""
    p = tmp_path / "scenes.yaml"
    p.write_text("")
    reg = scenes_config.load_scenes_registry(p)
    assert reg.assignments == ()


def test_lookup_by_ssid_returns_none_for_blank() -> None:
    reg = scenes_config.SceneRegistry(
        assignments=(
            scenes_config.SceneAssignment(scene="home", ssid="X"),
        ),
    )
    assert reg.lookup_by_ssid(None) is None
    assert reg.lookup_by_ssid("") is None


def test_env_var_overrides_default_path(monkeypatch, tmp_path) -> None:
    """`DITING_SCENES_FILE=/absolute/path` overrides the default
    `./scenes.yaml`. Matches the DITING_INVENTORY pattern for aps.yaml."""
    p = tmp_path / "custom.yaml"
    _write(p, """\
        networks:
          - ssid: Special
            scene: office
    """)
    monkeypatch.setenv("DITING_SCENES_FILE", str(p))
    reg = scenes_config.load_scenes_registry()  # no path arg → use env
    hit = reg.lookup(ssid="Special")
    assert hit is not None
    assert hit.scene == "office"
