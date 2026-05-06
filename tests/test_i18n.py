"""Coverage for the static-at-launch i18n module: language detection,
catalog lookup with fallback, format-string substitution, and the
CJK-aware cell-width padding helper."""

from __future__ import annotations

import pytest

from wifiscope import i18n


@pytest.fixture(autouse=True)
def _restore_lang():
    """Each test runs with a clean language state and leaves the
    process-wide default intact for the next test, since wifiscope
    sets the language exactly once at startup."""
    saved = i18n.get_lang()
    try:
        yield
    finally:
        i18n.set_lang(saved)


# ---------- detect_default_lang ----------


def test_detect_explicit_wifiscope_lang_wins_over_locale():
    env = {"WIFISCOPE_LANG": "en", "LANG": "zh_CN.UTF-8"}
    assert i18n.detect_default_lang(env) == i18n.EN


def test_detect_zh_from_lang_env():
    env = {"LANG": "zh_CN.UTF-8"}
    assert i18n.detect_default_lang(env) == i18n.ZH


def test_detect_zh_from_lc_all_overrides_lang():
    env = {"LC_ALL": "zh_CN.UTF-8", "LANG": "en_US.UTF-8"}
    assert i18n.detect_default_lang(env) == i18n.ZH


def test_detect_falls_back_to_english():
    assert i18n.detect_default_lang({}) == i18n.EN
    assert i18n.detect_default_lang({"LANG": "fr_FR.UTF-8"}) == i18n.EN


def test_detect_ignores_invalid_wifiscope_lang_value():
    """A typo in the env should not silently route to a language we
    cannot serve — fall through to locale detection instead."""
    env = {"WIFISCOPE_LANG": "ja", "LANG": "zh_CN.UTF-8"}
    assert i18n.detect_default_lang(env) == i18n.ZH


# ---------- resolve_lang ----------


def test_resolve_cli_override_wins_over_env():
    env = {"WIFISCOPE_LANG": "zh"}
    assert i18n.resolve_lang(i18n.EN, env) == i18n.EN


def test_resolve_no_override_uses_env():
    env = {"WIFISCOPE_LANG": "zh"}
    assert i18n.resolve_lang(None, env) == i18n.ZH


def test_resolve_rejects_unknown_cli_value():
    with pytest.raises(ValueError):
        i18n.resolve_lang("ja", {})


# ---------- t() ----------


def test_t_returns_english_when_lang_is_english():
    i18n.set_lang(i18n.EN)
    assert i18n.t("Connection") == "Connection"


def test_t_falls_back_to_english_when_zh_key_missing(monkeypatch):
    """A new English string should not blank the UI just because the
    Chinese catalog has not been updated yet."""
    monkeypatch.setattr(i18n, "_ZH", {})
    i18n.set_lang(i18n.ZH)
    assert i18n.t("brand-new string with no translation") == (
        "brand-new string with no translation"
    )


def test_t_substitutes_placeholders(monkeypatch):
    monkeypatch.setattr(i18n, "_ZH", {"hello {name}": "你好 {name}"})
    i18n.set_lang(i18n.ZH)
    assert i18n.t("hello {name}", name="ccy") == "你好 ccy"


def test_t_substitutes_in_english_too(monkeypatch):
    """Format-string semantics must work even when the language is
    English and no lookup happens, since call sites should not branch
    on the active language."""
    i18n.set_lang(i18n.EN)
    assert i18n.t("ch{n}", n=48) == "ch48"


# ---------- pad_cells ----------


def test_pad_cells_pads_ascii_to_target_width():
    assert i18n.pad_cells("ab", 6) == "ab    "


def test_pad_cells_treats_cjk_as_two_cells_each():
    """'连接' is 4 cells, so reaching 10 requires 6 spaces — using
    str.ljust here would over-pad and break column alignment."""
    assert i18n.pad_cells("连接", 10) == "连接      "


def test_pad_cells_returns_unchanged_if_already_wide():
    assert i18n.pad_cells("toolong", 4) == "toolong"


def test_pad_cells_handles_mixed_ascii_and_cjk():
    # 'SSID 信号' = 4 + 1 + 4 = 9 cells
    assert i18n.pad_cells("SSID 信号", 12) == "SSID 信号   "


# ---------- set_lang validation ----------


def test_set_lang_rejects_unknown_value():
    with pytest.raises(ValueError):
        i18n.set_lang("ja")
