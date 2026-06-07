"""normalize_bssid — the canonical BSSID spelling every producer emits.

macOS formats some surfaces without octet zero-padding (the
SCDynamicStore ``CachedScanRecord`` renders ``0b`` as ``b``), which made
the same radio two identities downstream (duplicate Nearby rows,
phantom roams, split familiarity history) until normalization landed.
"""

from __future__ import annotations

from diting.models import normalize_bssid


def test_normalize_bssid_pads_octets():
    # The 2026-06-07 live symptom: SCDynamicStore spelling of the radio.
    assert normalize_bssid("40:fe:95:8a:3c:b") == "40:fe:95:8a:3c:0b"
    assert normalize_bssid("0:1:2:3:4:5") == "00:01:02:03:04:05"


def test_normalize_bssid_padded_passthrough():
    assert normalize_bssid("40:fe:95:8a:3c:0b") == "40:fe:95:8a:3c:0b"


def test_normalize_bssid_case_folds():
    assert normalize_bssid("40:FE:95:8A:3C:B") == "40:fe:95:8a:3c:0b"


def test_normalize_bssid_failsoft_junk():
    # Not six octets / not hex → lowercased passthrough, never a raise.
    assert normalize_bssid("not-a-mac") == "not-a-mac"
    assert normalize_bssid("AA:BB:CC") == "aa:bb:cc"
    assert normalize_bssid("gg:gg:gg:gg:gg:gg") == "gg:gg:gg:gg:gg:gg"
    assert normalize_bssid("aa:bb:cc:dd:ee:fff") == "aa:bb:cc:dd:ee:fff"
    assert normalize_bssid("") == ""


def test_normalize_bssid_none():
    assert normalize_bssid(None) is None
