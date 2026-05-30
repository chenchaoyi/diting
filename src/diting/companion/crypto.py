"""Seal an event into a companion-protocol envelope, and open one.

libsodium secretbox (XSalsa20-Poly1305) under the 32-byte channel key.
The sealed plaintext is exactly the event's JSONL object (same bytes the
``EventLogger`` would write), so the wire payload and the on-disk report
share one shape. ``open_envelope`` is the inverse, used by tests here and
mirrored by the mobile consumer in Dart; it fails closed (raises
``ProtocolError``) on a tampered ciphertext, a wrong key, or a payload
that does not conform to the event schema.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox
from nacl.utils import random as nacl_random

from .protocol.envelope import build_envelope, validate_envelope
from .protocol.errors import ProtocolError
from .protocol.events_schema import validate_event
from .protocol.version import PROTOCOL_VERSION

KEY_BYTES = SecretBox.KEY_SIZE  # 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except (ValueError, TypeError) as exc:
        raise ProtocolError(f"envelope field is not valid base64: {exc}") from exc


def seal_event(key: bytes, *, channel: str, seq: int, ts: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Seal one event ``payload`` dict into a wire envelope.

    ``ts`` is the producer wall-clock for the envelope (distinct from the
    event's own ``ts`` inside the sealed payload). The plaintext is the
    compact JSON of ``payload`` with ``ensure_ascii=False`` — byte-for-byte
    what the JSONL writer emits.
    """
    if len(key) != KEY_BYTES:
        raise ProtocolError(f"channel key must be {KEY_BYTES} bytes, got {len(key)}")
    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    enc = SecretBox(key).encrypt(plaintext, nacl_random(SecretBox.NONCE_SIZE))
    return build_envelope(
        version=PROTOCOL_VERSION,
        channel=channel,
        seq=seq,
        ts=ts,
        nonce_b64=_b64(enc.nonce),
        ciphertext_b64=_b64(enc.ciphertext),
    )


def open_envelope(key: bytes, env: dict[str, Any]) -> dict[str, Any]:
    """Open + validate a wire envelope, returning the event payload.

    Raises :class:`ProtocolError` on a malformed envelope, a failed
    authentication (tamper / wrong key), non-JSON plaintext, or a payload
    that does not conform to the event schema — never surfacing
    fabricated data.
    """
    validate_envelope(env)
    nonce = _unb64(env["n"])
    ciphertext = _unb64(env["ct"])
    try:
        plaintext = SecretBox(key).decrypt(ciphertext, nonce)
    except CryptoError as exc:
        raise ProtocolError("envelope failed authentication (tamper or wrong key)") from exc
    try:
        obj = json.loads(plaintext)
    except ValueError as exc:
        raise ProtocolError(f"decrypted payload is not JSON: {exc}") from exc
    return validate_event(obj)
