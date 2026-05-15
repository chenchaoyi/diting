"""Per-key decoders for Bonjour service-instance TXT records.

The Bonjour detail modal renders TXT data in two layers:

  Decoded — well-known keys (``model`` / ``osxvers`` / ``srcvers`` /
            ``features`` / ``ft`` / ``rpFl``) surface as named
            human-readable fields above the raw table.
  Raw     — everything else still shows up as a 2-column table so
            the user can read unknown fields verbatim.

Decoders follow the BLE decoder convention:

* register via :func:`register` (a tiny decorator that builds the
  registry at import time);
* take the raw TXT value (a ``str`` because :class:`BonjourDevice`
  already drops non-UTF-8 fields);
* return ``(label, value)`` on success, ``None`` to abstain.

A decoder MUST NOT raise — malformed values are common in the
wild and an exception in one decoder must not poison the rest of
the modal. The harness in :func:`decode_txt` wraps each invocation
in a try-except as belt-and-braces, but decoders should treat that
as a safety net not an authoritative contract.
"""
from __future__ import annotations

from typing import Callable

DecoderResult = tuple[str, str] | None
Decoder = Callable[[str], DecoderResult]

_REGISTRY: dict[str, Decoder] = {}


def register(key: str) -> Callable[[Decoder], Decoder]:
    """Decorator that registers a decoder for a TXT key name.

    Multiple decoders per key are not supported — the last
    registration wins. Stick to one decoder per well-known key.
    """
    def _wrap(fn: Decoder) -> Decoder:
        _REGISTRY[key] = fn
        return fn
    return _wrap


def decoded_keys() -> set[str]:
    """The set of TXT keys with registered decoders.

    Exposed so the modal can render the raw TXT table while
    skipping keys whose decoded form is already shown.
    """
    return set(_REGISTRY)


def decode_txt(txt: dict[str, str]) -> list[tuple[str, str]]:
    """Decode every recognised TXT key in ``txt``.

    Returns a list of ``(label, decoded_value)`` tuples preserving
    the registry's registration order so the rendered modal is
    deterministic across runs. Keys absent from the registry are
    skipped (the modal renders them in the raw table instead).
    """
    out: list[tuple[str, str]] = []
    for key, decoder in _REGISTRY.items():
        raw = txt.get(key)
        if raw is None:
            continue
        try:
            result = decoder(raw)
        except Exception:
            # Decoder safety net. Decoders SHOULD abstain on bad
            # input rather than raise; this is the last line of
            # defence so a broken decoder can never break the
            # modal render.
            continue
        if result is None:
            continue
        out.append(result)
    return out


# ---------------------------------------------------------------------
# Initial decoder set
# ---------------------------------------------------------------------
#
# Starter kit. The full long tail of TXT keys (AirPlay's `features`
# bitmask, RAOP's `ft`, Companion-link `rpFl`, etc.) lives behind a
# registry rather than a giant if/elif so new decoders can land one
# at a time without touching the modal renderer.

# Hand-picked subset of Apple's well-known model identifiers. Not
# exhaustive — the table grows when a user reports a missing entry.
# Unrecognised identifiers fall through to displaying the raw
# string (no abstain, since the model code itself is meaningful).
_APPLE_MODELS: dict[str, str] = {
    # MacBook Pro
    "MacBookPro17,1":  "MacBook Pro 13-inch (M1, 2020)",
    "MacBookPro18,1":  "MacBook Pro 16-inch (M1 Pro, 2021)",
    "MacBookPro18,2":  "MacBook Pro 16-inch (M1 Max, 2021)",
    "MacBookPro18,3":  "MacBook Pro 14-inch (M1 Pro, 2021)",
    "MacBookPro18,4":  "MacBook Pro 14-inch (M1 Max, 2021)",
    "Mac14,5":         "MacBook Pro 14-inch (M2 Max, 2023)",
    "Mac14,6":         "MacBook Pro 16-inch (M2 Max, 2023)",
    "Mac14,9":         "MacBook Pro 14-inch (M2 Pro, 2023)",
    "Mac14,10":        "MacBook Pro 16-inch (M2 Pro, 2023)",
    "Mac15,3":         "MacBook Pro 14-inch (M3, 2023)",
    "Mac15,6":         "MacBook Pro 14-inch (M3 Pro, 2023)",
    "Mac15,7":         "MacBook Pro 16-inch (M3 Pro, 2023)",
    "Mac15,8":         "MacBook Pro 14-inch (M3 Max, 2023)",
    "Mac15,9":         "MacBook Pro 16-inch (M3 Max, 2023)",
    "Mac15,10":        "MacBook Pro 14-inch (M3 Max, 2023)",
    "Mac15,11":        "MacBook Pro 16-inch (M3 Max, 2023)",
    "Mac16,1":         "MacBook Pro 14-inch (M4, 2024)",
    "Mac16,5":         "MacBook Pro 14-inch (M4 Pro, 2024)",
    "Mac16,6":         "MacBook Pro 16-inch (M4 Pro, 2024)",
    "Mac16,7":         "MacBook Pro 16-inch (M4 Max, 2024)",
    "Mac16,8":         "MacBook Pro 14-inch (M4 Max, 2024)",
    # MacBook Air
    "MacBookAir10,1":  "MacBook Air (M1, 2020)",
    "Mac14,2":         "MacBook Air 13-inch (M2, 2022)",
    "Mac14,15":        "MacBook Air 15-inch (M2, 2023)",
    "Mac15,12":        "MacBook Air 13-inch (M3, 2024)",
    "Mac15,13":        "MacBook Air 15-inch (M3, 2024)",
    # Mac mini / Mac Studio
    "Macmini9,1":      "Mac mini (M1, 2020)",
    "Mac14,3":         "Mac mini (M2, 2023)",
    "Mac14,12":        "Mac mini (M2 Pro, 2023)",
    "Mac16,10":        "Mac mini (M4, 2024)",
    "Mac16,11":        "Mac mini (M4 Pro, 2024)",
    "Mac14,8":         "Mac Studio (M1 Max / Ultra, 2022)",
    "Mac14,13":        "Mac Studio (M2 Max, 2023)",
    "Mac14,14":        "Mac Studio (M2 Ultra, 2023)",
    # iPhone
    "iPhone15,2":      "iPhone 14 Pro",
    "iPhone15,3":      "iPhone 14 Pro Max",
    "iPhone16,1":      "iPhone 15 Pro",
    "iPhone16,2":      "iPhone 15 Pro Max",
    "iPhone17,1":      "iPhone 16 Pro",
    "iPhone17,2":      "iPhone 16 Pro Max",
    # HomePod / AppleTV
    "AudioAccessory1,1":   "HomePod (1st generation)",
    "AudioAccessory5,1":   "HomePod mini",
    "AudioAccessory6,1":   "HomePod (2nd generation)",
    "AppleTV5,3":          "Apple TV HD",
    "AppleTV6,2":          "Apple TV 4K (1st generation)",
    "AppleTV11,1":         "Apple TV 4K (2nd generation)",
    "AppleTV14,1":         "Apple TV 4K (3rd generation)",
}


@register("model")
def _decode_model(raw: str) -> DecoderResult:
    """Apple's hardware model identifier (``MacBookPro18,1``).

    Maps a curated subset to friendly product names. Unknown
    identifiers still surface — they're useful as-is for matching
    Apple's identifier-to-product tables externally.
    """
    raw = raw.strip()
    if not raw:
        return None
    friendly = _APPLE_MODELS.get(raw)
    if friendly:
        return ("model", f"{friendly} ({raw})")
    return ("model", raw)


@register("osxvers")
def _decode_osxvers(raw: str) -> DecoderResult:
    """macOS major version. AirPlay advertises this as an integer
    (e.g. ``"14"`` for Sonoma, ``"15"`` for Sequoia, ``"26"`` for
    the 2026 release). We pass it through with the macOS-version
    name when known; otherwise display raw.
    """
    raw = raw.strip()
    if not raw.isdigit():
        return None
    _MAJOR_NAMES = {
        "11": "Big Sur",
        "12": "Monterey",
        "13": "Ventura",
        "14": "Sonoma",
        "15": "Sequoia",
        "26": "Tahoe",
    }
    name = _MAJOR_NAMES.get(raw)
    if name:
        return ("macOS", f"{name} ({raw})")
    return ("macOS", raw)


@register("srcvers")
def _decode_srcvers(raw: str) -> DecoderResult:
    """Source-firmware version string. Render verbatim — these are
    Apple-internal build identifiers, no canonical decoding."""
    raw = raw.strip()
    if not raw:
        return None
    return ("firmware", raw)


@register("deviceid")
def _decode_deviceid(raw: str) -> DecoderResult:
    """The ``deviceid`` TXT field on AirPlay / RAOP services is a
    MAC address used by the resolver's OUI step. Render it as a
    proper MAC so the user reading the modal can correlate with
    BLE / Wi-Fi vendor data."""
    raw = raw.strip()
    # MACs are 17 chars in canonical colon-separated form
    # (``xx:xx:xx:xx:xx:xx``); accept that shape and pass through.
    parts = raw.split(":")
    if len(parts) != 6 or any(len(p) != 2 for p in parts):
        return None
    return ("device MAC", raw.lower())
