"""Generic manufacturer-data recogniser for the long tail of vendors.

Most BLE adverts carry a SIG company-id plus a vendor-specific body. A
handful of vendors have dedicated decoders here (Apple, Microsoft,
Xiaomi/Huami, Ruuvi); everyone else — Polar, Garmin, Honor, and the many
chip / module makers (Telink, Silicon Labs/Bluegiga, …) — produced *no*
decoded fields at all, so a known-vendor advert showed up with empty
"decoded protocols" even though we can see exactly what it broadcast.

This decoder fills that gap WITHOUT inventing semantics (per the project's
"no semantic claims for unstable bits" rule, and unlike a name-based
classifier — see the no-name-based-classification guidance): it surfaces
the company-id, the resolved vendor, and the raw body bytes in a uniform
``mfg.*`` shape. It deliberately does NOT assign a ``device_type`` /
``device_class`` from the company-id — a chip-vendor id (Telink/Bluegiga)
says nothing about the product, so guessing would be wrong more than right.

Vendors that already have a dedicated decoder are skipped so we don't
double-emit alongside their richer protocol fields.
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

# Company-ids handled by a dedicated decoder in this package. Skipping
# them keeps the generic recogniser from emitting redundant `mfg.*` rows
# next to the protocol-specific fields (apple.* / ms.* / xiaomi.* / ruuvi.*).
_DEDICATED_CIDS = frozenset({0x004C, 0x0006, 0x038F, 0x0499})


@register
def decode(d: BLEDevice) -> dict[str, Any] | None:
    """Recognise any vendored manufacturer-data frame without a dedicated
    decoder, surfacing it as ``mfg.*`` fields.

    Output keys:

    * ``mfg.cid`` — company-id as ``0xXXXX``.
    * ``mfg.vendor`` — resolved vendor name, when known (omitted otherwise).
    * ``mfg.body_hex`` — bytes after the 2-byte company-id prefix, lowercase
      hex. Empty string for a header-only frame.
    * ``mfg.body_len`` — length of the body in bytes.

    Abstains (returns ``None``) on: no company-id, a company-id owned by a
    dedicated decoder, missing / invalid / too-short manufacturer_hex.
    """
    cid = d.vendor_id
    if cid is None or cid in _DEDICATED_CIDS:
        return None
    if not d.manufacturer_hex:
        return None
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    if len(blob) < 2:  # the 2-byte company-id prefix didn't survive
        return None
    body = blob[2:]
    out: dict[str, Any] = {
        "mfg.cid": f"0x{cid:04x}",
        "mfg.body_hex": body.hex(),
        "mfg.body_len": len(body),
    }
    if d.vendor:
        out["mfg.vendor"] = d.vendor
    return out
