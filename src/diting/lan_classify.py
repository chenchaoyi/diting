"""Device-class inference for `LANHost`.

Pure read-side classifier — consumes the vendor / probe / TTL
fields already populated on a `LANHost` and returns one of the
documented class strings (``phone | laptop | desktop | tv | camera
| smart-home | printer | nas | gaming | speaker | router``) or
``None`` when no rule fires.

Class output is **presentational**. Wrong class never affects
events, the analyzer aggregation, the JSONL stream, or the LLM
bundle. Worst case: the LAN row shows a misleading one-word label.

Rules table walked top-down, first match wins. Rules use only the
fields available on `LANHost`; the classifier never does I/O.
Inputs are tolerant: missing fields just skip the rule that
needed them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from .lan import LANHost


# ---------- helpers ----------


def _lower(value: str | None) -> str:
    """Coerce a possibly-None value to a lowercase string for matching."""
    return (value or "").lower()


def _has_any(haystack: str, needles: tuple[str, ...]) -> bool:
    """True iff any needle appears in the lowercase haystack."""
    return any(n in haystack for n in needles)


def _bonjour_has(host: "LANHost", needles: tuple[str, ...]) -> bool:
    """True iff any needle matches in the Bonjour service categories."""
    cats = " ".join(host.bonjour_services or ()).lower()
    return _has_any(cats, needles)


# ---------- per-class predicates ----------
# Ordered most-specific → most-general within each class. Predicates
# are total functions (LANHost → bool) so the rules table stays a
# flat list of (predicate, class) pairs.

_CAMERA_VENDOR_NEEDLES: tuple[str, ...] = (
    "hikvision",
    "dahua",
    "axis communications",
    "tapo",
    "imou",
    "reolink",
    "ezviz",
    "amcrest",
    "uniview",
)

_SMART_HOME_VENDOR_NEEDLES: tuple[str, ...] = (
    "tuya",
    "xiaomi",
    "aqara",
    "mijia",
    "lumi",
    "shenzhen bilian",
    "espressif",
    "imilab",
)

_ROUTER_VENDOR_NEEDLES: tuple[str, ...] = (
    "tp-link",
    "tplink",
    "asus",
    "asustek",
    "netgear",
    "linksys",
    "ubiquiti",
    "mikrotik",
    "new h3c",
    "h3c technologies",
    "huawei technologies",
    "ruijie",
    "openwrt",
    "fortinet",
)

_NAS_VENDOR_NEEDLES: tuple[str, ...] = (
    "synology",
    "qnap",
    "western digital",
    "wd technologies",
    "drobo",
    "asustor",
    "terramaster",
)

_PRINTER_VENDOR_NEEDLES: tuple[str, ...] = (
    "brother industries",
    "canon",
    "epson",
    "kyocera",
    "ricoh",
    "lexmark",
    "fuji xerox",
)

_TV_VENDOR_NEEDLES: tuple[str, ...] = (
    "hisense",
    "lge",
    "lg electronics",
    "samsung electronics",
    "sony",
    "tcl",
    "skyworth",
    "konka",
    "changhong",
    "vizio",
    "roku",
    "amazon technologies",
)

_GAMING_VENDOR_NEEDLES: tuple[str, ...] = (
    "nintendo",
    "sony interactive entertainment",
    "microsoft corporation",  # xbox; also-trips on PCs — gated below by other rules
)

_SPEAKER_VENDOR_NEEDLES: tuple[str, ...] = (
    "sonos",
    "bose",
    "harman",
    "jbl",
    "anker",
    "ultimate ears",
    "marshall",
    "denon",
    "bang & olufsen",
)


# ---------- rules table ----------

Rule = tuple[Callable[["LANHost"], bool], str]


_RULES: tuple[Rule, ...] = (
    # Gateway is always router, regardless of vendor.
    (lambda h: h.is_gateway, "router"),

    # Printers via Bonjour AirPrint / IPP / LPD — strongest signal,
    # works even when vendor is unknown.
    (
        lambda h: _bonjour_has(
            h, ("airprint", "ipp", "ipps", "lpd", "pdl-datastream"),
        ),
        "printer",
    ),
    (
        lambda h: _has_any(_lower(h.vendor_raw), _PRINTER_VENDOR_NEEDLES),
        "printer",
    ),

    # Cameras — strong vendor signal + sometimes UPnP server header
    # carrying "Hikvision-Webs".
    (
        lambda h: _has_any(_lower(h.vendor_raw), _CAMERA_VENDOR_NEEDLES),
        "camera",
    ),
    (
        lambda h: _has_any(
            _lower(h.upnp_server),
            ("hikvision", "dahua", "axis", "ip-cam", "ipcam", "netcam"),
        ),
        "camera",
    ),

    # NAS — Bonjour shares (SMB / AFP) or vendor.
    (
        lambda h: _bonjour_has(
            h, ("smb", "afpovertcp", "nfs", "_adisk", "time machine"),
        ),
        "nas",
    ),
    (
        lambda h: _has_any(_lower(h.vendor_raw), _NAS_VENDOR_NEEDLES),
        "nas",
    ),

    # Speakers (HomePod / Sonos) — `_raop` is the AirPlay receiver
    # service published by audio-only Apple devices; HomePods AND
    # iPads / iPhones can publish AirPlay, but only audio-output
    # devices publish `_raop._tcp`. Order matters: this rule MUST
    # come before the AirPlay-as-tv rule so HomePods don't get
    # mis-classified.
    (
        lambda h: _bonjour_has(h, ("_raop", "_spotify-connect", "sonos")),
        "speaker",
    ),
    (
        lambda h: _has_any(_lower(h.vendor_raw), _SPEAKER_VENDOR_NEEDLES),
        "speaker",
    ),

    # TVs — UPnP server header is the most reliable signal because
    # smart TVs almost always run a UPnP MediaRenderer.
    (
        lambda h: _has_any(
            _lower(h.upnp_server),
            ("smarttv", "smart-tv", "hisense", "samsung-tv", "lge-tv",
             "androidtv", "android-tv", "android tv", "webos", "tizen",
             "appletv", "apple-tv"),
        ),
        "tv",
    ),
    # Cast / Android-TV protocols are TV-specific (no phone / speaker
    # publishes them).
    (
        lambda h: _bonjour_has(h, ("googlecast", "_androidtvremote2")),
        "tv",
    ),
    # AirPlay alone is ambiguous — iPad, iPhone, HomePod, AND Apple TV
    # all publish it. Treat as tv ONLY when no phone / speaker
    # companion signal is present (the speaker rule above already
    # claimed `_raop`-bearing hosts; this leaves Apple TV — which
    # publishes AirPlay without `_raop` — and third-party AirPlay-
    # capable TVs).
    (
        lambda h: _bonjour_has(h, ("airplay",))
        and not _bonjour_has(
            h, ("_companion-link", "apple companion", "_apple-mobdev2"),
        ),
        "tv",
    ),
    (
        lambda h: _has_any(_lower(h.vendor_raw), _TV_VENDOR_NEEDLES),
        "tv",
    ),

    # Phones — Apple Continuity / Companion Bonjour. Falls through
    # the TV rules above only when AirPlay is paired with
    # `_companion-link`, i.e. an iPad / iPhone / Mac.
    (
        lambda h: _bonjour_has(
            h, ("_companion-link", "apple companion", "_apple-mobdev2"),
        ),
        "phone",
    ),

    # Gaming consoles — Bonjour Nintendo / vendor.
    (
        lambda h: _has_any(_lower(h.vendor_raw), _GAMING_VENDOR_NEEDLES),
        "gaming",
    ),

    # Routers / APs — vendor.
    (
        lambda h: _has_any(_lower(h.vendor_raw), _ROUTER_VENDOR_NEEDLES),
        "router",
    ),

    # Smart-home — broad bucket for IoT bridges, plugs, sensors.
    (
        lambda h: _has_any(
            _lower(h.vendor_raw), _SMART_HOME_VENDOR_NEEDLES,
        ),
        "smart-home",
    ),

    # Self is always the user's Mac — laptop or desktop, but the
    # row already shows "this Mac" so we don't need to disambiguate
    # the class. Defer to TTL-based fallback below.

    # TTL fallbacks — least confident, deliberately last. Windows
    # is the only OS family with a distinct initial TTL among
    # common consumer devices.
    (lambda h: h.ttl_class == "windows", "desktop"),
)


# ---------- public API ----------


def classify(host: "LANHost") -> str | None:
    """Return the device class for ``host`` or None when no rule fires.

    Total function — no exceptions on any combination of input
    fields. Caller-side rule (the merge step in ``lan.py``) decides
    what to do with a None result; the row's class column simply
    renders empty when class is None.
    """
    try:
        for predicate, klass in _RULES:
            try:
                if predicate(host):
                    return klass
            except Exception:
                # Defensive: a rule predicate that raises must not
                # break classification of subsequent rules or the
                # overall function contract.
                continue
        return None
    except Exception:  # pragma: no cover — safety net
        return None
