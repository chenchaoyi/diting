"""iBeacon decoder.

Layout (Apple Proximity Beacon spec, manufacturer-data after the
2-byte company ID 0x004C):

    type        1 B = 0x02
    length      1 B = 0x15  (= 21, fixed)
    UUID        16 B (big-endian)
    major       2 B big-endian
    minor       2 B big-endian
    tx_power    1 B signed (RSSI expected at 1 m)

So the full manufacturer-data blob is 25 bytes: 2-byte cid + 23-byte
beacon record. The helper hex-encodes the lot, including the cid
prefix.

Output keys:

    ibeacon.uuid       canonical UUID-with-dashes string
    ibeacon.major      int 0..65535
    ibeacon.minor      int 0..65535
    ibeacon.tx_power   int (signed dBm at 1 m)
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

_APPLE_CID = 0x004C
_IBEACON_TYPE = 0x02
_IBEACON_LEN = 0x15  # 21 bytes after the (type, length) prefix


def _format_uuid(b: bytes) -> str:
    """Format 16 raw bytes as a canonical lowercase UUID string."""
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


@register
def decode(d: BLEDevice) -> dict[str, Any] | None:
    if d.vendor_id != _APPLE_CID:
        return None
    if not d.manufacturer_hex:
        return None
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    # Need cid (2) + type (1) + length (1) + iBeacon body (21) = 25 bytes.
    if len(blob) < 25:
        return None
    if blob[2] != _IBEACON_TYPE or blob[3] != _IBEACON_LEN:
        return None

    uuid_bytes = blob[4:20]
    major = (blob[20] << 8) | blob[21]
    minor = (blob[22] << 8) | blob[23]
    # tx_power is signed int8.
    tx_raw = blob[24]
    tx_power = tx_raw - 256 if tx_raw >= 128 else tx_raw
    return {
        "ibeacon.uuid": _format_uuid(uuid_bytes),
        "ibeacon.major": major,
        "ibeacon.minor": minor,
        "ibeacon.tx_power": tx_power,
    }
