"""Multi-tier IEEE OUI lookup tests.

Verifies the (MA-L / MA-M / MA-S) longest-prefix-wins behaviour of
`diting.ble.lookup_oui_vendor` and the graceful-degradation contract
of `diting.ble.load_ouis_layered`.

Synthetic dicts only — these tests do not touch the bundled JSON
files, so they pass regardless of whether the MA-M / MA-S tiers
have been populated via `scripts/refresh_ouis.py` yet.
"""
from __future__ import annotations

import json
from pathlib import Path

from diting.ble import load_ouis_layered, lookup_oui_vendor


def test_lookup_prefers_ma_s_over_ma_m_and_ma_l() -> None:
    ma_l = {"aa:bb:cc": "MA-L vendor"}
    ma_m = {"aa:bb:cc:1": "MA-M vendor"}
    ma_s = {"aa:bb:cc:11:2": "MA-S vendor"}
    # MAC: aa:bb:cc:11:22:33 → 36-bit prefix `aa:bb:cc:11:2`
    assert (
        lookup_oui_vendor(
            "aa:bb:cc:11:22:33", ma_l=ma_l, ma_m=ma_m, ma_s=ma_s,
        )
        == "MA-S vendor"
    )


def test_lookup_falls_back_to_ma_m_when_ma_s_missing() -> None:
    ma_l = {"aa:bb:cc": "MA-L vendor"}
    ma_m = {"aa:bb:cc:1": "MA-M vendor"}
    ma_s: dict[str, str] = {}
    assert (
        lookup_oui_vendor(
            "aa:bb:cc:11:22:33", ma_l=ma_l, ma_m=ma_m, ma_s=ma_s,
        )
        == "MA-M vendor"
    )


def test_lookup_falls_back_to_ma_l_when_higher_tiers_missing() -> None:
    ma_l = {"aa:bb:cc": "MA-L vendor"}
    assert (
        lookup_oui_vendor(
            "aa:bb:cc:11:22:33", ma_l=ma_l, ma_m={}, ma_s={},
        )
        == "MA-L vendor"
    )


def test_lookup_returns_none_when_no_tier_matches() -> None:
    assert (
        lookup_oui_vendor(
            "aa:bb:cc:11:22:33", ma_l={}, ma_m={}, ma_s={},
        )
        is None
    )


def test_lookup_returns_none_for_empty_identifier() -> None:
    assert lookup_oui_vendor(None, ma_l={"aa:bb:cc": "x"}) is None
    assert lookup_oui_vendor("", ma_l={"aa:bb:cc": "x"}) is None


def test_lookup_tolerates_dash_and_colon_and_no_separator() -> None:
    ma_l = {"38:09:fb": "Apple, Inc."}
    assert (
        lookup_oui_vendor("38-09-fb-0b-be-60", ma_l=ma_l) == "Apple, Inc."
    )
    assert (
        lookup_oui_vendor("38:09:fb:0b:be:60", ma_l=ma_l) == "Apple, Inc."
    )
    assert lookup_oui_vendor("3809fb0bbe60", ma_l=ma_l) == "Apple, Inc."


def test_legacy_signature_still_works() -> None:
    """The pre-multitier `lookup_oui_vendor(mac, ouis)` call form
    must keep returning the same answers — tests in test_ble.py
    rely on it, and so do `mdns.py` + `ble.py` internals."""
    ouis = {"38:09:fb": "Apple, Inc."}
    assert lookup_oui_vendor("38:09:fb:0b:be:60", ouis) == "Apple, Inc."
    assert lookup_oui_vendor("11:22:33:44:55:66", ouis) is None


def test_load_ouis_layered_returns_three_dicts() -> None:
    ma_l, ma_m, ma_s = load_ouis_layered()
    assert isinstance(ma_l, dict)
    assert isinstance(ma_m, dict)
    assert isinstance(ma_s, dict)
    # MA-L is bundled with real data; MA-M / MA-S are stubs by default.
    # Whichever way the bundled files look right now, every value must
    # be a string and every key must be lowercase.
    for d in (ma_l, ma_m, ma_s):
        for k, v in d.items():
            assert k == k.lower()
            assert isinstance(v, str)


def test_load_ouis_layered_tolerates_missing_files(tmp_path: Path) -> None:
    """Pointing the loader at a path that doesn't exist yields an
    empty dict for that tier; the call as a whole does not raise."""
    ma_l, ma_m, ma_s = load_ouis_layered(
        ma_l_path=tmp_path / "missing-ma-l.json",
        ma_m_path=tmp_path / "missing-ma-m.json",
        ma_s_path=tmp_path / "missing-ma-s.json",
    )
    assert ma_l == {}
    assert ma_m == {}
    assert ma_s == {}


def test_load_ouis_layered_tolerates_unreadable_file(tmp_path: Path) -> None:
    """Malformed JSON in any tier is swallowed — that tier becomes
    empty; the other tiers still load normally."""
    broken = tmp_path / "broken.json"
    broken.write_text("not json at all {{{")
    ok_ma_l = tmp_path / "ma_l.json"
    ok_ma_l.write_text(
        json.dumps({"_meta": "x", "aa:bb:cc": "Real"})
    )
    ma_l, ma_m, ma_s = load_ouis_layered(
        ma_l_path=ok_ma_l, ma_m_path=broken, ma_s_path=broken,
    )
    assert ma_l == {"aa:bb:cc": "Real"}
    assert ma_m == {}
    assert ma_s == {}


def test_load_ouis_layered_real_files_match_bundled_keys() -> None:
    """The default-path load (no kwargs) succeeds and the resulting
    MA-L dict contains at least one well-known entry (Apple). MA-M /
    MA-S may be stubs and therefore empty; that's fine."""
    ma_l, _ma_m, _ma_s = load_ouis_layered()
    # Apple's 38:09:fb is a stable historical assignment that won't
    # disappear from MA-L.
    assert ma_l.get("38:09:fb") is not None
