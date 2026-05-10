"""Eddystone decoder.

Eddystone advertises in service-data scoped to the FEAA UUID. The
first byte of the payload is a frame-type discriminator:

    0x00 — UID  (16-byte beacon ID: 10-byte namespace + 6-byte instance)
    0x10 — URL  (1-byte URL scheme + compressed URL bytes)
    0x20 — TLM  (battery voltage / temperature / ad count / time since boot)
    0x30 — EID  (encrypted, opaque to passive observers — not decoded)

References:
    https://github.com/google/eddystone (canonical spec, archived but
    stable). The framework here covers UID / URL / TLM unencrypted;
    EID is intentionally not decoded since it's a per-beacon-key
    symmetric ciphertext.

Output keys are protocol-namespaced under ``eddystone.``:

    eddystone.frame           "UID" | "URL" | "TLM" | "EID"
    eddystone.tx_power_at_0m  int (UID + URL frames; ranging RSSI at 0 m)
    eddystone.namespace       hex string (UID)
    eddystone.instance        hex string (UID)
    eddystone.url             expanded URL string (URL)
    eddystone.battery_mv      int (TLM, milli-volts; 0 = not supported)
    eddystone.temperature_c   float (TLM, signed 8.8 fixed-point in °C)
    eddystone.ad_count        int (TLM, advertisements since boot)
    eddystone.uptime_s        int (TLM, seconds since boot)
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

_FEAA = "FEAA"
_FRAME_UID = 0x00
_FRAME_URL = 0x10
_FRAME_TLM = 0x20
_FRAME_EID = 0x30

# URL frame scheme prefix table (1 byte → string).
_URL_SCHEMES = {
    0x00: "http://www.",
    0x01: "https://www.",
    0x02: "http://",
    0x03: "https://",
}

# URL-frame "encoded character" expansions (for byte values >= 0).
# Bytes 0x00..0x0d expand to common TLDs / URL fragments; 0x0e..0x20
# and 0x7f..0xff are reserved. Anything else passes through as ASCII.
_URL_EXPANSIONS = {
    0x00: ".com/", 0x01: ".org/", 0x02: ".edu/", 0x03: ".net/",
    0x04: ".info/", 0x05: ".biz/", 0x06: ".gov/",
    0x07: ".com", 0x08: ".org", 0x09: ".edu", 0x0a: ".net",
    0x0b: ".info", 0x0c: ".biz", 0x0d: ".gov",
}


def _normalize_uuid_key(key: str) -> str:
    """Eddystone keys can arrive 16-bit short (``FEAA``) or 128-bit
    canonical (``0000FEAA-...``). Collapse to the 4-char short form
    used by SIG conventions.
    """
    s = key.upper().replace("-", "")
    if len(s) == 32 and s.endswith("00805F9B34FB") and s.startswith("0000"):
        return s[4:8]
    return s


def _expand_url(payload: bytes) -> str | None:
    """Decode an Eddystone-URL payload (already past the frame-type
    byte and tx-power byte). Returns the expanded URL string or
    None if the scheme byte is invalid.
    """
    if not payload:
        return None
    scheme = _URL_SCHEMES.get(payload[0])
    if scheme is None:
        return None
    out = [scheme]
    for b in payload[1:]:
        ex = _URL_EXPANSIONS.get(b)
        if ex is not None:
            out.append(ex)
        elif 0x21 <= b <= 0x7E:
            # printable ASCII passes through
            out.append(chr(b))
        else:
            # reserved / non-printable — surface as escape sequence
            # rather than dropping silently
            out.append(f"\\x{b:02x}")
    return "".join(out)


def _signed8(b: int) -> int:
    return b - 256 if b >= 128 else b


@register
def decode(d: BLEDevice) -> dict[str, Any] | None:
    if not d.service_data:
        return None
    payload_hex: str | None = None
    for uuid, hex_blob in d.service_data:
        if _normalize_uuid_key(uuid) == _FEAA:
            payload_hex = hex_blob
            break
    if payload_hex is None:
        return None
    try:
        blob = bytes.fromhex(payload_hex)
    except ValueError:
        return None
    if not blob:
        return None
    frame = blob[0]

    if frame == _FRAME_UID and len(blob) >= 18:
        # frame(1) + tx_power(1) + namespace(10) + instance(6) [+ rfu(2)]
        return {
            "eddystone.frame": "UID",
            "eddystone.tx_power_at_0m": _signed8(blob[1]),
            "eddystone.namespace": blob[2:12].hex(),
            "eddystone.instance": blob[12:18].hex(),
        }

    if frame == _FRAME_URL and len(blob) >= 3:
        # frame(1) + tx_power(1) + scheme(1) + encoded url
        url = _expand_url(blob[2:])
        if url is None:
            return None
        return {
            "eddystone.frame": "URL",
            "eddystone.tx_power_at_0m": _signed8(blob[1]),
            "eddystone.url": url,
        }

    if frame == _FRAME_TLM and len(blob) >= 14:
        # frame(1) + version(1) + battery_mv_be(2) + temp_8.8_be(2)
        # + adv_count_be(4) + sec_count_be(4); only version 0x00
        # documented.
        battery_mv = (blob[2] << 8) | blob[3]
        # Signed 8.8 fixed-point. The integer part is signed.
        temp_int = blob[4]
        if temp_int >= 128:
            temp_int -= 256
        temp_frac = blob[5] / 256.0
        temperature_c = temp_int + temp_frac
        ad_count = (blob[6] << 24) | (blob[7] << 16) | (blob[8] << 8) | blob[9]
        sec_count = (blob[10] << 24) | (blob[11] << 16) | (blob[12] << 8) | blob[13]
        # Eddystone-TLM stores time in 0.1 s units.
        uptime_s = sec_count // 10
        return {
            "eddystone.frame": "TLM",
            "eddystone.battery_mv": battery_mv,
            "eddystone.temperature_c": round(temperature_c, 2),
            "eddystone.ad_count": ad_count,
            "eddystone.uptime_s": uptime_s,
        }

    if frame == _FRAME_EID:
        return {"eddystone.frame": "EID"}

    return None
