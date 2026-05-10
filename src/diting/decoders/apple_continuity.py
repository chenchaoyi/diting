"""Apple Continuity subtype byte-level decoder.

Apple's Continuity protocol multiplexes several subtypes inside the
manufacturer-data field for company ID 0x004C. The helper already
labels the first subtype byte (``type``) and, for type 0x10
specifically, extracts the device-class nibble. This module unpacks
the rest of the payload bytes for the subtypes we care about most:

  * 0x10 Nearby Info — every iPhone / iPad / Mac / Apple TV /
    HomePod broadcasts this; carries the status byte, OS-and-class
    byte, and a short AppleID hash.
  * 0x12 Find My target — short form (2-byte payload: status +
    hint byte). The long form (25-byte public key broadcast) is
    out of scope here; we'd never decode the rotating EC key.
  * 0x0C Handoff — clipboard-present flag, sequence counter, GCM
    auth tag, and 10-byte encrypted activity ID.

**Important caveat**: bit-level semantics inside the status / flag
bytes shift between iOS major versions (the various
reverse-engineering writeups disagree even within one iOS release).
This decoder surfaces the raw bytes with mechanical labels rather
than claiming Apple-internal flag interpretations. The user can
inspect, compare across rows, and form their own pattern theories
without us baking a wrong claim into the UI.

Output keys are ``nearby_info.*``, ``find_my.*``, ``handoff.*``.
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

_APPLE_CID = 0x004C
_TYPE_HANDOFF = 0x0C
_TYPE_NEARBY_INFO = 0x10
_TYPE_FIND_MY = 0x12


def _continuity_payload(d: BLEDevice, expected_type: int) -> bytes | None:
    """Return the payload bytes of the FIRST Continuity subframe whose
    type matches ``expected_type``, or None if not present.

    Apple's Continuity layers subtypes back-to-back inside one
    manufacturer-data field (Nearby Info often follows Handoff in the
    same packet). Walk the (type, length, payload) records starting
    after the 2-byte company-ID prefix; stop when we find the type or
    fall off the end.
    """
    if d.vendor_id != _APPLE_CID:
        return None
    if not d.manufacturer_hex:
        return None
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    # Skip the 2-byte cid prefix.
    i = 2
    while i + 1 < len(blob):
        subtype = blob[i]
        length = blob[i + 1]
        start = i + 2
        end = start + length
        if end > len(blob):
            break
        if subtype == expected_type:
            return blob[start:end]
        i = end
    return None


@register
def decode_nearby_info(d: BLEDevice) -> dict[str, Any] | None:
    """Apple Continuity Nearby Info (0x10) byte detail.

    Layout (post-length byte):

      payload[0]   status_flags   — high nibble action_code-ish,
                                    low nibble flag bits; exact
                                    semantics shift per iOS release
      payload[1]   class_os_byte  — low nibble = device class
                                    (iPhone / iPad / Mac / ...),
                                    high nibble = OS-version hint
      payload[2..] AppleID hash   — partial SHA hint of the AppleID
                                    enabling cross-device coalescing
                                    on Apple's side; no public
                                    semantic, useful as a stable
                                    per-account identifier
    """
    payload = _continuity_payload(d, _TYPE_NEARBY_INFO)
    if payload is None or len(payload) < 2:
        return None
    status = payload[0]
    class_os = payload[1]
    out: dict[str, Any] = {
        "nearby_info.status_hex": f"0x{status:02x}",
        "nearby_info.action_code_hi": (status >> 4) & 0x0F,
        "nearby_info.flags_lo": status & 0x0F,
        "nearby_info.class_byte_hex": f"0x{class_os:02x}",
        "nearby_info.os_hint_hi": (class_os >> 4) & 0x0F,
        "nearby_info.device_class_lo": class_os & 0x0F,
    }
    if len(payload) > 2:
        out["nearby_info.appleid_hash"] = payload[2:].hex()
    return out


@register
def decode_find_my(d: BLEDevice) -> dict[str, Any] | None:
    """Apple Find My (0x12) short-form target broadcast.

    Layout (post-length byte) for the 2-byte short form most
    devices use:

      payload[0]   status_flags  — community references suggest
                                    bits include "registered to
                                    AppleID" and "lost mode", but
                                    documented mappings disagree
                                    across sources, so we surface
                                    the byte hex without claiming
                                    semantics
      payload[1]   hint_byte     — appears to rotate 0x00–0x03 in
                                    the wild; may be a battery /
                                    rotation-state counter

    The 25-byte long form (AirTag public-key rotation packet) is not
    decoded here — it's an opaque rotating EC public key fragment,
    nothing publicly meaningful to extract.
    """
    payload = _continuity_payload(d, _TYPE_FIND_MY)
    if payload is None or len(payload) < 2:
        return None
    out: dict[str, Any] = {
        "find_my.status_hex": f"0x{payload[0]:02x}",
        "find_my.hint_hex": f"0x{payload[1]:02x}",
    }
    if len(payload) >= 25:
        # Long form — surface the key fragment hex but do not pretend
        # to decode it. Trim to keep modal lines readable.
        out["find_my.key_fragment"] = payload[2:25].hex()
    return out


@register
def decode_handoff(d: BLEDevice) -> dict[str, Any] | None:
    """Apple Continuity Handoff (0x0C) frame detail.

    Layout (post-length byte, length is typically 0x0e = 14 bytes):

      payload[0]   flags             — bit 0 indicates clipboard
                                       contents are present
      payload[1]   seq               — sequence counter increments
                                       per change; lets us tell
                                       "same activity, repeated
                                       advertisement" apart from
                                       "user just shared something"
      payload[2..3]   auth_tag       — GCM tag (truncated)
      payload[4..]    activity_id    — encrypted with the user's
                                       per-Continuity key; opaque
                                       to passive observers
    """
    payload = _continuity_payload(d, _TYPE_HANDOFF)
    if payload is None or len(payload) < 4:
        return None
    flags = payload[0]
    seq = payload[1]
    auth_tag = payload[2:4]
    activity = payload[4:]
    return {
        "handoff.clipboard_present": bool(flags & 0x01),
        "handoff.flags_hex": f"0x{flags:02x}",
        "handoff.seq": seq,
        "handoff.auth_tag": auth_tag.hex(),
        "handoff.activity_id": activity.hex(),
    }
