"""Device-class classifier tests (`diting.lan_classify.classify`)."""
from __future__ import annotations

from datetime import datetime, timezone

from diting.lan import LANHost
from diting.lan_classify import classify


def _host(**overrides) -> LANHost:
    """Build a LANHost with sensible defaults; override only what each
    test cares about. Defaults: universal MAC, no probe enrichment,
    no Bonjour services, not self / not gateway."""
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    defaults: dict = dict(
        mac="08:11:22:33:44:55",
        ip="192.168.1.42",
        vendor=None,
        hostname=None,
        bonjour_name=None,
        bonjour_services=(),
        first_seen=now,
        last_seen=now,
        is_gateway=False,
        is_self=False,
        is_randomised_mac=False,
        last_rtt_ms=None,
        last_reachable_at=None,
        vendor_raw=None,
        nbns_name=None,
        upnp_server=None,
        upnp_friendly_name=None,
        upnp_model=None,
        ttl=None,
        ttl_class=None,
        device_class=None,
    )
    defaults.update(overrides)
    return LANHost(**defaults)


# ---------- gateway wins ----------


def test_gateway_wins_router_regardless_of_vendor():
    # Even if the vendor would otherwise route to "tv", a gateway
    # flag forces the class to router.
    h = _host(is_gateway=True, vendor_raw="HiSense Co., Ltd.")
    assert classify(h) == "router"


# ---------- printer ----------


def test_airprint_bonjour_signals_printer():
    h = _host(bonjour_services=("AirPrint", "IPP"))
    assert classify(h) == "printer"


def test_printer_vendor_signals_printer():
    h = _host(vendor_raw="Brother Industries, Ltd.")
    assert classify(h) == "printer"
    h2 = _host(vendor_raw="EPSON")
    assert classify(h2) == "printer"


# ---------- tv ----------


def test_upnp_smarttv_header_signals_tv():
    h = _host(upnp_server="Linux/3.10 UPnP/1.0 SmartTV/2024.01")
    assert classify(h) == "tv"


def test_hisense_vendor_signals_tv():
    h = _host(vendor_raw="Hisense Visual Technology Co.")
    assert classify(h) == "tv"


def test_airplay_bonjour_signals_tv():
    # AirPlay alone on a non-Apple-vendor device is most commonly a TV
    # (e.g. an Apple TV box or a TV with AirPlay 2 support).
    h = _host(bonjour_services=("AirPlay", "GoogleCast"))
    assert classify(h) == "tv"


# ---------- camera ----------


def test_hikvision_vendor_signals_camera():
    h = _host(vendor_raw="Hikvision Digital Technology Co.,Ltd")
    assert classify(h) == "camera"


def test_dahua_vendor_signals_camera():
    h = _host(vendor_raw="Dahua Technology Co., Ltd")
    assert classify(h) == "camera"


def test_imou_vendor_signals_camera():
    h = _host(vendor_raw="IMOU Technology")
    assert classify(h) == "camera"


def test_upnp_camera_server_header_signals_camera():
    h = _host(upnp_server="Hikvision-Webs/1.0")
    assert classify(h) == "camera"


# ---------- smart-home ----------


def test_tuya_vendor_signals_smart_home():
    h = _host(vendor_raw="Tuya Smart Inc.")
    assert classify(h) == "smart-home"


def test_xiaomi_vendor_signals_smart_home():
    h = _host(vendor_raw="Xiaomi Communications Co Ltd")
    assert classify(h) == "smart-home"


def test_aqara_vendor_signals_smart_home():
    h = _host(vendor_raw="Aqara Smart Home")
    assert classify(h) == "smart-home"


# ---------- speaker ----------


def test_sonos_bonjour_signals_speaker():
    h = _host(bonjour_services=("_spotify-connect",))
    assert classify(h) == "speaker"


def test_bose_vendor_signals_speaker():
    h = _host(vendor_raw="Bose Corporation")
    assert classify(h) == "speaker"


# ---------- nas ----------


def test_synology_vendor_signals_nas():
    h = _host(vendor_raw="Synology Inc.")
    assert classify(h) == "nas"


def test_qnap_vendor_signals_nas():
    h = _host(vendor_raw="QNAP Systems")
    assert classify(h) == "nas"


def test_smb_bonjour_signals_nas():
    h = _host(bonjour_services=("smb", "_adisk"))
    assert classify(h) == "nas"


# ---------- phone ----------


def test_apple_companion_signals_phone():
    h = _host(bonjour_services=("_companion-link",))
    assert classify(h) == "phone"


# ---------- gaming ----------


def test_nintendo_vendor_signals_gaming():
    h = _host(vendor_raw="Nintendo Co., Ltd.")
    assert classify(h) == "gaming"


# ---------- router ----------


def test_tp_link_vendor_signals_router():
    h = _host(vendor_raw="Tp-Link Technologies Co.,Ltd.")
    assert classify(h) == "router"


def test_h3c_vendor_signals_router():
    h = _host(vendor_raw="New H3C Technologies Co., Ltd")
    assert classify(h) == "router"


def test_ubiquiti_vendor_signals_router():
    h = _host(vendor_raw="Ubiquiti Networks Inc.")
    assert classify(h) == "router"


# ---------- desktop TTL fallback ----------


def test_windows_ttl_signals_desktop():
    h = _host(ttl=128, ttl_class="windows")
    assert classify(h) == "desktop"


# ---------- None / pure-function safety ----------


def test_no_signals_returns_none():
    h = _host()
    assert classify(h) is None


def test_random_mac_with_no_other_signals_returns_none():
    h = _host(is_randomised_mac=True)
    assert classify(h) is None


def test_classifier_never_raises_on_minimal_host():
    """All-None fields must not raise from any predicate."""
    h = _host()
    # Should be a plain return, not an exception.
    classify(h)


def test_classifier_with_predicate_raising_skips_and_continues(monkeypatch):
    """A rogue predicate that raises must not break the function —
    subsequent rules still get a chance to match."""
    # We patch the RULES tuple temporarily with one raising predicate
    # followed by a stable one that should match.
    from diting import lan_classify as mod
    original = mod._RULES
    try:
        def _boom(_h):
            raise RuntimeError("rule kaboom")

        def _is_apple(h):
            return (h.vendor_raw or "").lower().startswith("apple")

        mod._RULES = (
            (_boom, "should-never-fire"),
            (_is_apple, "phone"),
        )
        h = _host(vendor_raw="Apple, Inc.")
        assert classify(h) == "phone"
    finally:
        mod._RULES = original


# ---------- output domain ----------


_VALID_CLASSES = {
    "phone", "laptop", "desktop", "tv", "camera", "smart-home",
    "printer", "nas", "gaming", "speaker", "router",
}


def test_every_rule_result_is_in_the_documented_vocabulary():
    """Sanity that nobody adds a misspelled / off-spec class string
    to the rules table without it showing up in this test."""
    from diting.lan_classify import _RULES
    for _pred, klass in _RULES:
        assert klass in _VALID_CLASSES, f"unknown class string: {klass!r}"
