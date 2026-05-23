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
        bonjour_model=None,
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
    # Network printers publish `_ipp._tcp.local.`, which the mdns
    # module records as the category "Printer".
    h = _host(bonjour_services=("Printer",))
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
    h = _host(bonjour_services=("Sonos",))
    assert classify(h) == "speaker"


def test_homepod_airplay_audio_plus_homekit_signals_speaker_not_tv():
    """HomePods publish AirPlay + AirPlay audio + HomeKit. The
    HomeKit category is the discriminator vs Macs with AirPlay
    receiver enabled (which publish AirPlay audio but no HomeKit).
    Original regression from the 2026-05-23 tui-audit
    ('Blue-Pod' as tv); HomeKit requirement added 2026-05-23 PM
    after Macs were mis-routed to speaker."""
    h = _host(bonjour_services=("AirPlay", "AirPlay audio", "HomeKit"))
    assert classify(h) == "speaker"


def test_mac_with_airplay_receiver_enabled_signals_laptop_not_speaker():
    """A Mac with AirPlay receiver enabled publishes AirPlay +
    AirPlay audio + Apple Companion — the exact category set that
    iPad / iPhone publish PLUS the audio-receiver service. No
    HomeKit. Vendor=Apple. Must NOT classify as speaker —
    regression for the 2026-05-23 PM user-flagged case where an
    M2 MacBook Air rendered as `音箱` after the previous fix."""
    h = _host(
        vendor_raw="Apple, Inc.",
        bonjour_services=("AirPlay", "AirPlay audio", "Apple Companion"),
    )
    assert classify(h) == "laptop"


def test_homepod_full_apple_signature_signals_speaker_not_phone():
    """Real-data HomePod signature observed on the user's home
    network: AirPlay + AirPlay audio + Apple Companion + HomeKit.
    Speaker MUST win over phone — second regression from the
    2026-05-23 follow-up audit where my first fix used `_raop`
    as the needle and never matched the actual category string."""
    h = _host(bonjour_services=(
        "AirPlay", "AirPlay audio", "Apple Companion", "HomeKit",
    ))
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
    # `_smb._tcp.local.` → "File share" category.
    h = _host(bonjour_services=("File share",))
    assert classify(h) == "nas"


# ---------- phone ----------


def test_apple_companion_signals_phone():
    h = _host(bonjour_services=("Apple Companion",))
    assert classify(h) == "phone"


def test_ipad_airplay_plus_companion_signals_phone_not_tv():
    """iPads / iPhones with screen-mirroring active publish BOTH
    AirPlay AND Apple Companion. The phone rule must win —
    regression for the 2026-05-23 tui-audit where an iPad serial
    `L19L6JC6Q2` was classified as `tv`."""
    h = _host(bonjour_services=("AirPlay", "Apple Companion"))
    assert classify(h) == "phone"


def test_apple_tv_airplay_alone_still_signals_tv():
    """Apple TV publishes AirPlay without `AirPlay audio` or
    `Apple Companion` in its non-paired state. The AirPlay-only
    branch should still route to `tv`."""
    h = _host(bonjour_services=("AirPlay",))
    assert classify(h) == "tv"


# ---------- gaming ----------


def test_nintendo_vendor_signals_gaming():
    h = _host(vendor_raw="Nintendo Co., Ltd.")
    assert classify(h) == "gaming"


def test_sony_interactive_entertainment_signals_gaming_not_tv():
    """PlayStation consoles register under "Sony Interactive
    Entertainment Inc." in IEEE. The TV-vendor needle used to be
    just `"sony"` which also matched the PS vendor, mis-routing
    the user's PS5 Pro into `tv`. Regression for the 2026-05-23
    re-audit follow-up — needle narrowed to `"sony corporation"`
    so Bravia TVs still match but PlayStations fall through to
    the gaming rule."""
    h = _host(vendor_raw="Sony Interactive Entertainment Inc.")
    assert classify(h) == "gaming"


# ---------- Apple model-code (Bonjour TXT) ----------


def test_apple_model_mac_signals_laptop():
    """`Mac14,2` (MacBook Air M2 13" 2022) → laptop via the Apple
    model-code rule, regardless of Bonjour categories."""
    h = _host(
        vendor_raw="Apple, Inc.",
        bonjour_services=("AirPlay", "AirPlay audio", "Apple Companion"),
        bonjour_model="Mac14,2",
    )
    assert classify(h) == "laptop"


def test_apple_model_audioaccessory_signals_speaker():
    """`AudioAccessory6,1` (HomePod 2nd gen) → speaker even when
    HomeKit isn't visible yet in the bonjour_services snapshot
    (the HomePodSensor publishes HomeKit as a separate service-
    instance; cross-reference may race)."""
    h = _host(
        vendor_raw="Apple, Inc.",
        bonjour_services=("AirPlay", "AirPlay audio", "Apple Companion"),
        bonjour_model="AudioAccessory6,1",
    )
    assert classify(h) == "speaker"


def test_apple_model_iphone_signals_phone():
    h = _host(
        vendor_raw="Apple, Inc.",
        bonjour_services=("Apple Companion",),
        bonjour_model="iPhone16,1",
    )
    assert classify(h) == "phone"


def test_apple_model_appletv_signals_tv():
    """`AppleTV14,1` (Apple TV 4K 3rd gen) → tv via model code,
    not the AirPlay-as-tv fallback. Apple TVs also publish
    Apple Companion for pairing; the model code lifts them above
    the phone rule."""
    h = _host(
        vendor_raw="Apple, Inc.",
        bonjour_services=("AirPlay", "Apple Companion"),
        bonjour_model="AppleTV14,1",
    )
    assert classify(h) == "tv"


def test_apple_model_unknown_prefix_falls_through():
    """A model code with a prefix we don't recognise (future Apple
    SKU, or a typo) shouldn't short-circuit — the rules table still
    gets to fire."""
    h = _host(
        vendor_raw="Apple, Inc.",
        bonjour_services=("AirPlay", "Apple Companion"),
        bonjour_model="XyzNewThing1,1",
    )
    # Falls through Apple-model → tv-category (AirPlay no companion-speaker)
    # → phone (Apple Companion). The exact class doesn't matter for this
    # test — only that the function returns SOMETHING and doesn't crash.
    cls = classify(h)
    assert cls in {None, "tv", "phone"}


def test_apple_model_macbookpro_explicit_prefix_wins():
    """The MacBookPro prefix MUST match before the generic `Mac`
    prefix, otherwise `MacBookPro18,1` would resolve to laptop
    purely on the `Mac` prefix anyway (same class) — but the
    ordering matters for desktop variants like `Macmini`."""
    h = _host(bonjour_model="Macmini9,1")
    assert classify(h) == "desktop"


def test_sony_corporation_still_signals_tv():
    """Sony's TV / Bravia IEEE registrant — must still match the
    narrowed needle. Sanity that the fix didn't over-trim."""
    h = _host(vendor_raw="Sony Corporation")
    assert classify(h) == "tv"


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
