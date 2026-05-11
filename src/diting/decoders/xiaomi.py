"""Xiaomi / Anhui Huami manufacturer-data decoder.

Xiaomi-family devices (Mi Band, Amazfit, redmi peripherals — all
manufactured under the Anhui Huami Information Technology Co., Ltd.
brand) advertise on Bluetooth company-id ``0x038F`` (911 dec). At the
time of writing Xiaomi has not published a public spec for this
manufacturer-data frame, and several reverse-engineered partial
descriptions disagree on the exact byte meanings.

To stay honest, this decoder takes a conservative stance:

* it RECOGNISES the frame (cid + first byte after the cid prefix,
  observed empirically to behave like a frame counter / sequence
  byte across captures of the same device);
* it surfaces the raw body bytes as a hex string so the detail
  modal can show what the device actually broadcast;
* it does NOT invent semantic field names like "battery %" or
  "step count" — those would be unverifiable claims, in violation
  of the project's "no semantic claims for unstable bits" rule.

The decoder's main practical value is "yes, this is the Xiaomi /
Huami frame, and here is the byte sequence you can compare across
captures by hand". Future revisions can add named fields as the
Xiaomi / Huami advertisement structure gets pinned down via more
real-world samples.
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

_XIAOMI_CID = 0x038F


@register
def decode(d: BLEDevice) -> dict[str, Any] | None:
    """Xiaomi / Anhui Huami manufacturer-data recogniser.

    Output keys (all ``xiaomi.*`` namespaced):

    * ``xiaomi.cid`` — the company-id (always ``0x038f`` here, but
      surfaced for parity with the other vendor decoders).
    * ``xiaomi.frame_seq`` — the first byte after the cid prefix
      (one byte). Observed to vary like a frame counter across
      captures of the same physical device; the user can use it to
      eyeball whether two close-RSSI Xiaomi rows are the same band
      cycling through ad slots.
    * ``xiaomi.body_hex`` — the remaining bytes (cid + frame_seq
      stripped), lowercase hex. Empty string when the advertisement
      is a header-only frame (the short ``8f03`` records that
      appear after RPA rotations).
    * ``xiaomi.body_len`` — int length of ``body_hex`` in bytes,
      makes scanning the detail modal easier.

    Abstains (returns ``None``) on:

    * Wrong cid.
    * Missing / invalid manufacturer_hex.
    * Truncated frame (under 2 hex bytes, i.e. the cid prefix itself
      didn't make it through the helper).
    """
    if d.vendor_id != _XIAOMI_CID:
        return None
    if not d.manufacturer_hex:
        return None
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    # cid (2 bytes LE) + optional 1 frame byte + 0..N body bytes
    if len(blob) < 2:
        return None
    out: dict[str, Any] = {"xiaomi.cid": f"0x{_XIAOMI_CID:04x}"}
    if len(blob) == 2:
        # Header-only frame — common after an RPA rotation.
        out["xiaomi.body_hex"] = ""
        out["xiaomi.body_len"] = 0
        return out
    frame_seq = blob[2]
    out["xiaomi.frame_seq"] = frame_seq
    body = blob[3:]
    out["xiaomi.body_hex"] = body.hex()
    out["xiaomi.body_len"] = len(body)
    return out
