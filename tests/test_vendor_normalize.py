"""Vendor-name normalization tests for `diting.lan._normalize_vendor`.

The function turns raw IEEE registry strings like
``"NEW H3C TECHNOLOGIES CO., LTD"`` into short, readable display
forms like ``"New H3C"``. These tests cover the suffix-stripping,
prefix-stripping, acronym-preservation, and truncation paths.
"""
from __future__ import annotations

from diting.lan import _normalize_vendor, _VENDOR_DISPLAY_WIDTH


def test_returns_none_for_none() -> None:
    assert _normalize_vendor(None) is None


def test_returns_none_for_empty() -> None:
    assert _normalize_vendor("") is None
    assert _normalize_vendor("   ") is None


def test_strips_co_ltd_suffix() -> None:
    assert _normalize_vendor("TP-LINK CO., LTD") == "TP-Link"
    assert _normalize_vendor("BILIAN CO.,LTD") == "Bilian"


def test_strips_corporation_suffix() -> None:
    assert _normalize_vendor("XEROX CORPORATION") == "Xerox"


def test_strips_inc_suffix() -> None:
    assert _normalize_vendor("Apple Inc.") == "Apple"
    assert _normalize_vendor("Apple, Inc.") == "Apple"


def test_strips_technologies_suffix() -> None:
    assert _normalize_vendor("ASUSTEK COMPUTER INC.") == "Asustek Computer"
    assert (
        _normalize_vendor("NEW H3C TECHNOLOGIES CO., LTD") == "New H3C"
    )


def test_strips_electronics_suffix() -> None:
    # SHENZHEN is a leading prefix, ELECTRONIC is a trailing suffix —
    # both get stripped, leaving the brand.
    assert _normalize_vendor("SHENZHEN BILIAN ELECTRONIC CO.,LTD") == "Bilian"


def test_strips_shenzhen_prefix() -> None:
    assert _normalize_vendor("SHENZHEN VENDOR") == "Vendor"


def test_strips_hangzhou_prefix() -> None:
    assert _normalize_vendor("HANGZHOU H3C") == "H3C"


def test_strips_multiple_geographic_prefixes() -> None:
    # Unlikely but defensive — the loop should keep stripping.
    assert _normalize_vendor("SHENZHEN HANGZHOU FOO") == "Foo"


def test_titlecases_default() -> None:
    assert _normalize_vendor("REGULAR VENDOR") == "Regular Vendor"


def test_preserves_h3c_acronym() -> None:
    assert _normalize_vendor("H3C") == "H3C"
    # In multi-word too:
    assert _normalize_vendor("NEW H3C") == "New H3C"


def test_preserves_asus_acronym() -> None:
    assert _normalize_vendor("ASUS") == "ASUS"


def test_preserves_hp_acronym() -> None:
    assert _normalize_vendor("HP") == "HP"


def test_preserves_tp_link_brand() -> None:
    # IEEE registers TP-LINK; Python's .title() would emit "Tp-Link".
    # The override fixes the casing.
    assert "TP-Link" in _normalize_vendor("TP-LINK TECHNOLOGIES")


def test_preserves_ibm_acronym() -> None:
    assert _normalize_vendor("IBM CORP") == "IBM"


def test_truncates_to_column_width() -> None:
    # 30 char vendor → truncated to 16 cells (15 chars + ellipsis).
    raw = "Aaaaaaaaaaaaaaaaa Bbbbbbbbbbbbbb"
    out = _normalize_vendor(raw)
    assert out is not None
    assert len(out) <= _VENDOR_DISPLAY_WIDTH


def test_idempotent_under_repeated_calls() -> None:
    once = _normalize_vendor("NEW H3C TECHNOLOGIES CO., LTD")
    twice = _normalize_vendor(once or "")
    assert once == twice


def test_empty_after_stripping_returns_none() -> None:
    # All-noise input collapses to empty; function must return None
    # rather than raise.
    assert _normalize_vendor("CO., LTD") is None
    assert _normalize_vendor("CORPORATION INC") is None


def test_handles_unicode_input() -> None:
    # IEEE strings are ASCII, but defensively the function must not
    # raise on UTF-8.
    out = _normalize_vendor("BAR CORP")
    assert out == "Bar"
