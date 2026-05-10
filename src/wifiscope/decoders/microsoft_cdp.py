"""Microsoft CDP / Swift Pair byte-level decoder.

Microsoft's Cross Device Platform (CDP) multiplexes several subtypes
inside the manufacturer-data field for company ID 0x0006. The helper
already labels the first subtype byte (``type``) as either
"MS device beacon" (0x01) or "Swift Pair" (0x03). This module
extracts the rest of the payload bytes:

  * 0x01 device beacon — discovery broadcast every Windows 10/11
    machine and Surface Hub emits. Carries a 4-byte session salt
    plus a truncated device-hash that lets two Windows machines
    notice each other without yet pairing. We surface the bytes
    mechanically; no Microsoft-private flag interpretations.

  * 0x03 / 0x05 / 0x06 / 0x08 Swift Pair — the "Connect to Surface
    Pen?" / "Connect to Razer Mouse?" pop-up beacon. Carries a
    sub-scenario byte plus the **UTF-8 model name** users see in
    the Windows pairing prompt. This is the win: turning a generic
    "Microsoft" row into "Microsoft · Surface Pen 2".

References: Microsoft Connected Devices Platform (CDP) protocol +
the public Swift Pair HID guidance docs. Sub-scenario semantics
shift slightly between Microsoft documentation pages so we don't
claim a strict scenario→meaning mapping; the byte hex is shown.

Output keys: ``ms_cdp.*`` for 0x01, ``swift_pair.*`` for 0x03+.
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

_MICROSOFT_CID = 0x0006

_SUBTYPE_DEVICE_BEACON = 0x01
# Swift Pair sub-scenarios. Different Microsoft pages list slightly
# different values; we only use the set to route into the Swift Pair
# decoder vs the generic device-beacon decoder.
_SUBTYPE_SWIFT_PAIR_RANGE = {0x03, 0x05, 0x06, 0x08}


def _ms_payload(d: BLEDevice) -> bytes | None:
    """Return the bytes after the 2-byte cid prefix, or None.

    Unlike Apple Continuity, Microsoft CDP does not chain multiple
    subtypes inside one advertisement, so a flat cid-then-payload
    view is enough.
    """
    if d.vendor_id != _MICROSOFT_CID:
        return None
    if not d.manufacturer_hex:
        return None
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    if len(blob) < 3:
        return None
    return blob[2:]


@register
def decode_device_beacon(d: BLEDevice) -> dict[str, Any] | None:
    """Microsoft CDP device-discovery beacon (subtype 0x01).

    Layout (post-subtype byte) — names follow Microsoft's CDP SDK
    source; the precise bit packing inside each header byte
    differs across CDP versions and the public docs do not pin a
    canonical mapping, so we surface the bytes mechanically:

      [0]    device_type        — device-kind + flag bits packed
                                  together (Xbox / Surface Hub /
                                  Phone / Windows Desktop / IoT)
      [1]    version            — protocol-version / flavour byte;
                                  ``0x20`` is what every Windows
                                  10/11 machine in the live capture
                                  emits, independent of edition
      [2]    flags              — secondary flag byte (shared
                                  experiences capability hints)
      [3..6] salt               — 4-byte random per-session salt
      [7..]  device_hash        — truncated SHA of (cdp-id + salt);
                                  lets one Windows machine
                                  recognise another without
                                  exchanging credentials yet
    """
    payload = _ms_payload(d)
    if payload is None or not payload:
        return None
    if payload[0] != _SUBTYPE_DEVICE_BEACON:
        return None
    out: dict[str, Any] = {"ms_cdp.subtype": "device beacon"}
    if len(payload) >= 2:
        out["ms_cdp.device_type"] = f"0x{payload[1]:02x}"
    if len(payload) >= 3:
        out["ms_cdp.version"] = f"0x{payload[2]:02x}"
    if len(payload) >= 4:
        out["ms_cdp.flags"] = f"0x{payload[3]:02x}"
    if len(payload) >= 8:
        out["ms_cdp.salt"] = payload[4:8].hex()
    if len(payload) > 8:
        out["ms_cdp.device_hash"] = payload[8:].hex()
    return out


@register
def decode_swift_pair(d: BLEDevice) -> dict[str, Any] | None:
    """Microsoft Swift Pair beacon (subtype 0x03 / 0x05 / 0x06 / 0x08).

    Layout (post-subtype byte):

      [0]    sub_scenario       — pairing flavour: LE-only,
                                  LE+BR/EDR, with / without
                                  confirmation prompt, etc.
      [1]    reserved_rssi      — 0x80
      [2..]  model_name         — UTF-8 string (Microsoft's docs
                                  call it the "device name"; this
                                  is exactly what the Windows
                                  "Connect to X?" prompt displays)

    The model name is decoded as UTF-8; on a decode failure we
    fall back to hex so a malformed beacon still produces something
    inspectable rather than a None.
    """
    payload = _ms_payload(d)
    if payload is None or not payload:
        return None
    subtype = payload[0]
    if subtype not in _SUBTYPE_SWIFT_PAIR_RANGE:
        return None
    out: dict[str, Any] = {
        "swift_pair.subtype_hex": f"0x{subtype:02x}",
    }
    if len(payload) >= 2:
        out["swift_pair.sub_scenario"] = f"0x{payload[1]:02x}"
    if len(payload) >= 3:
        out["swift_pair.reserved_rssi"] = f"0x{payload[2]:02x}"
    if len(payload) > 3:
        name_bytes = payload[3:]
        # Many devices null-terminate the name; trim trailing NULs
        # so the modal doesn't print "Surface Pen\x00\x00".
        name_bytes = name_bytes.rstrip(b"\x00")
        try:
            out["swift_pair.model"] = name_bytes.decode("utf-8")
        except UnicodeDecodeError:
            out["swift_pair.model_hex"] = name_bytes.hex()
    return out
