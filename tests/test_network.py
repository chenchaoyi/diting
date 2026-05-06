"""Inventory resolution: the core of identifying which physical AP a
BSSID belongs to. The two real-world scenarios that drove the current
rules — H3C controllers handing out adjacent mgmt MACs out of one OUI
block, and the same vendor splitting "user" vs "internal" SSIDs across
sibling OUI blocks — both have regression cases here.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from wifiscope.network import (
    APEntry,
    NetworkInventory,
    band_label,
    cluster_label,
    default_config_path,
    format_bssid,
    load_inventory,
    resolve_config_path,
)


# --- fixtures the user actually ships, captured into a literal so a
# regression here always reproduces with the same data the production
# screenshots came from. -------------------------------------------------

H3C_HOME = NetworkInventory(
    aps=(
        APEntry(name="AX51-E_1-B1", mgmt_mac="40:fe:95:8a:3c:07"),
        APEntry(name="AX51-E_4-B2", mgmt_mac="40:fe:95:8a:3c:54"),
        APEntry(name="AX51-E_5-3F", mgmt_mac="40:fe:95:8a:3c:15"),
        APEntry(name="AX51-E_3-2F", mgmt_mac="40:fe:95:89:c7:df"),
        APEntry(name="AX60_2",       mgmt_mac="bc:22:47:ca:79:46"),
    ),
)


# --- prefix5 + last-byte proximity (primary rule) -----------------------

@pytest.mark.parametrize(
    "bssid, expected",
    [
        # AP 1 radios (mgmt 0x07): +1 = 2.4G, +4 = 5G
        ("40:fe:95:8a:3c:08", "AX51-E_1-B1"),
        ("40:fe:95:8a:3c:0b", "AX51-E_1-B1"),
        # AP 2 radios (mgmt 0x54)
        ("40:fe:95:8a:3c:55", "AX51-E_4-B2"),
        ("40:fe:95:8a:3c:58", "AX51-E_4-B2"),
        # AP 3 radios (mgmt 0x15)
        ("40:fe:95:8a:3c:16", "AX51-E_5-3F"),
        ("40:fe:95:8a:3c:19", "AX51-E_5-3F"),
        # AP 4 lives on a different chip (89:c7:* vs 8a:3c:*)
        ("40:fe:95:89:c7:e0", "AX51-E_3-2F"),
        ("40:fe:95:89:c7:e3", "AX51-E_3-2F"),
        # AP 5 different vendor OUI
        ("bc:22:47:ca:79:47", "AX60_2"),
        ("bc:22:47:ca:79:4a", "AX60_2"),
    ],
)
def test_resolve_primary_rule(bssid, expected):
    assert H3C_HOME.resolve(bssid) == expected


def test_resolve_three_aps_in_one_oui_do_not_collapse():
    """Regression: prefix5 alone matched any AP in the OUI; a -B2 BSSID
    used to mis-resolve to AX51-E_1-B1 because that was the first list
    entry. Last-byte proximity disambiguates."""
    assert H3C_HOME.resolve("40:fe:95:8a:3c:55") == "AX51-E_4-B2"
    assert H3C_HOME.resolve("40:fe:95:8a:3c:0b") == "AX51-E_1-B1"


def test_resolve_outside_window_returns_none():
    """A BSSID whose last byte is too far from any mgmt MAC is treated
    as a different AP entirely, even if the first five octets match."""
    # 0x40 is 0x39 above the closest mgmt (0x07) but we cap the window
    # at 8. Should not match B1 just because the prefix is the same.
    assert H3C_HOME.resolve("40:fe:95:8a:3c:40") is None


# --- mid4 fallback (cross-OUI vendor variant) ---------------------------

@pytest.mark.parametrize(
    "bssid, expected",
    [
        # H3C ships "internal" SSIDs on 44:* but the chip serial bytes
        # (positions 2..5) match the 40:* mgmt MAC.
        ("44:fe:95:89:c7:e0", "AX51-E_3-2F"),
        ("44:fe:95:89:c7:e3", "AX51-E_3-2F"),
        ("44:fe:95:8a:3c:08", "AX51-E_1-B1"),
        ("44:fe:95:8a:3c:55", "AX51-E_4-B2"),
        ("44:fe:95:8a:3c:16", "AX51-E_5-3F"),
    ],
)
def test_resolve_secondary_rule_cross_oui(bssid, expected):
    assert H3C_HOME.resolve(bssid) == expected


# --- non-matches --------------------------------------------------------

@pytest.mark.parametrize(
    "bssid",
    [
        "82:48:3b:80:99:0f",      # neighbour ('zhou') in user's office
        "c2:91:7c:40:5d:0f",      # another neighbour
        "f6:39:09:fa:78:8e",      # printer
        "72:42:d3:8f:8d:5c",      # locally-administered random
        None,                       # null bssid (e.g. fully redacted scan row)
    ],
)
def test_resolve_unrelated_returns_none(bssid):
    assert H3C_HOME.resolve(bssid) is None


# --- radio_overrides --------------------------------------------------

def test_radio_overrides_win_over_rule_match():
    inv = NetworkInventory(
        aps=(APEntry(name="generic", mgmt_mac="40:fe:95:8a:3c:07"),),
        radio_overrides={"40:fe:95:8a:3c:08": "manual-override"},
    )
    assert inv.resolve("40:fe:95:8a:3c:08") == "manual-override"


def test_radio_overrides_case_insensitive():
    inv = NetworkInventory(
        aps=(),
        radio_overrides={"aa:bb:cc:dd:ee:ff": "x"},
    )
    assert inv.resolve("AA:BB:CC:DD:EE:FF") == "x"


# --- is_same_ap -------------------------------------------------------

def test_is_same_ap_within_inventory():
    assert H3C_HOME.is_same_ap("40:fe:95:89:c7:e0", "40:fe:95:89:c7:e3")
    assert not H3C_HOME.is_same_ap("40:fe:95:89:c7:e3", "40:fe:95:8a:3c:58")


def test_is_same_ap_cross_oui_within_inventory():
    """Band switch on AP 4 across the 40: / 44: OUI blocks counts as
    one physical AP."""
    assert H3C_HOME.is_same_ap("40:fe:95:89:c7:e3", "44:fe:95:89:c7:e3")


def test_is_same_ap_neither_in_inventory_falls_back_to_prefix():
    """For BSSIDs we have no inventory entry for, group by prefix5 OR
    mid4 — both heuristics still apply."""
    inv = NetworkInventory()
    assert inv.is_same_ap("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02")
    assert inv.is_same_ap("40:bb:cc:dd:ee:01", "44:bb:cc:dd:ee:99")
    assert not inv.is_same_ap("aa:bb:cc:dd:ee:01", "11:22:33:dd:ee:01")


def test_is_same_ap_mismatch_when_one_resolves():
    """If one BSSID is ours but the other is not, they are not the
    same AP — even if the 5-octet prefix happens to coincide."""
    assert not H3C_HOME.is_same_ap(
        "40:fe:95:8a:3c:55",        # B2's 5G radio (resolves)
        "40:fe:95:8a:3c:99",        # outside window, does not resolve
    )


# --- band_label ------------------------------------------------------

@pytest.mark.parametrize(
    "ch, expected",
    [(1, "2.4G"), (6, "2.4G"), (14, "2.4G"),
     (36, "5G"), (157, "5G"), (177, "5G"),
     (None, None), (200, None), (15, None)],
)
def test_band_label(ch, expected):
    assert band_label(ch) == expected


# --- cluster_label ---------------------------------------------------

def test_cluster_label_groups_chip():
    """Octets 3..5 are the chip serial bits; same chip's many radios
    share them across OUI blocks."""
    common = {
        "40:fe:95:89:c7:e0", "40:fe:95:89:c7:e3", "40:fe:95:89:c7:e5",
        "44:fe:95:89:c7:e0", "44:fe:95:89:c7:e3",
    }
    labels = {cluster_label(b) for b in common}
    assert labels == {"?95:89:c7"}


def test_cluster_label_separates_unrelated():
    assert cluster_label("c2:91:7c:40:5d:0f") == "?7c:40:5d"
    assert cluster_label("f6:39:09:fa:78:8e") == "?09:fa:78"
    assert cluster_label("72:42:d3:8f:8d:5c") == "?d3:8f:8d"


def test_cluster_label_none_or_malformed():
    assert cluster_label(None) == "?"
    assert cluster_label("not-a-mac") == "?"


# --- format_bssid ----------------------------------------------------

def test_format_bssid_known_with_band():
    out = format_bssid("40:fe:95:89:c7:e3", 48, H3C_HOME)
    assert "AX51-E_3-2F" in out and "5G" in out and "40:fe:95:89:c7:e3" in out


def test_format_bssid_unknown_passthrough():
    out = format_bssid("ff:ff:ff:ff:ff:ff", 36, H3C_HOME)
    assert out == "ff:ff:ff:ff:ff:ff"


def test_format_bssid_none():
    assert format_bssid(None, 48, H3C_HOME) == "n/a"


# --- load_inventory --------------------------------------------------

def test_load_inventory_missing_file_returns_empty(tmp_path):
    inv = load_inventory(tmp_path / "nope.yaml")
    assert inv.aps == ()
    assert inv.radio_overrides == {}


def test_load_inventory_well_formed(tmp_path):
    p = tmp_path / "aps.yaml"
    p.write_text(textwrap.dedent(
        """
        aps:
          - name: 1F-bedroom
            mgmt_mac: 40:fe:95:8a:3c:07
          - name: 2F-living
            mgmt_mac: 40:fe:95:8a:3c:54

        radio_overrides:
          bc:22:47:ca:79:99: 3F-attic
        """
    ))
    inv = load_inventory(p)
    assert [a.name for a in inv.aps] == ["1F-bedroom", "2F-living"]
    assert inv.aps[0].mgmt_mac == "40:fe:95:8a:3c:07"
    assert inv.radio_overrides == {"bc:22:47:ca:79:99": "3F-attic"}


def test_load_inventory_missing_keys_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("aps:\n  - name: only-name\n")
    with pytest.raises(ValueError):
        load_inventory(p)


def test_load_inventory_top_level_must_be_mapping(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("[1, 2, 3]\n")
    with pytest.raises(ValueError):
        load_inventory(p)


# --- config path resolution -----------------------------------------


def test_default_config_path_is_cwd_relative():
    """The default lives next to the executed command, not in $HOME.
    Driven by user feedback that ``mkdir -p ~/.config/wifiscope`` and
    copying the example into a hidden directory was unnecessarily
    fiddly for a personal CLI tool that is most often run from inside
    its cloned repo. Returning a relative ``Path('aps.yaml')`` resolves
    against CWD at lookup time, so ``cd /repo && wifiscope`` finds the
    file next to the example template without ceremony.
    """
    assert default_config_path() == Path("aps.yaml")


def test_resolve_config_path_env_override_wins(monkeypatch):
    """``WIFISCOPE_INVENTORY`` always beats the default. ``~`` in the
    override is expanded so users can write ``~/somewhere/aps.yaml``.
    """
    monkeypatch.setenv("WIFISCOPE_INVENTORY", "~/custom/aps.yaml")
    resolved = resolve_config_path()
    assert resolved == Path("~/custom/aps.yaml").expanduser()


def test_resolve_config_path_no_env_falls_through_to_default(monkeypatch):
    """With the env var unset, resolution returns whatever
    :func:`default_config_path` produces — currently ``./aps.yaml``.
    Pinning this contract here so future refactors of the default
    cannot silently drift away from the env-override path.
    """
    monkeypatch.delenv("WIFISCOPE_INVENTORY", raising=False)
    assert resolve_config_path() == default_config_path()
