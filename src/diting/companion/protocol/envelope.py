"""Relay envelope — the unit a producer POSTs and a consumer pulls.

The envelope is pure transport structure; the event plaintext is sealed
into ``ct`` by the sender (secretbox, added in a later task group) and
the relay only ever sees these fields. Keys are kept short because every
event rides one envelope:

    v    int     protocol major (see version.py)
    ch   str     channel id (opaque pairing handle)
    seq  int     monotonic per-channel sequence (cursor); >= 1
    ts   str     producer wall-clock, ISO-8601 with offset
    n    str     base64 secretbox nonce
    ct   str     base64 secretbox ciphertext (sealed event object)

The relay assigns / honours ``seq`` ordering; the consumer pulls items
strictly after a cursor and uses ``seq`` to detect gaps. This module
does no crypto and never inspects ``ct`` — it validates shape only.
"""

from __future__ import annotations

from typing import Any

from .errors import ProtocolError
from .version import is_supported_version

ENVELOPE_FIELDS = ("v", "ch", "seq", "ts", "n", "ct")


def build_envelope(
    *,
    version: int,
    channel: str,
    seq: int,
    ts: str,
    nonce_b64: str,
    ciphertext_b64: str,
) -> dict[str, Any]:
    """Assemble a wire envelope dict. Does not encrypt — ``ciphertext_b64``
    is already-sealed bytes, base64-encoded, supplied by the caller."""
    return {
        "v": version,
        "ch": channel,
        "seq": seq,
        "ts": ts,
        "n": nonce_b64,
        "ct": ciphertext_b64,
    }


def validate_envelope(obj: Any) -> dict[str, Any]:
    """Return ``obj`` if it is a structurally valid envelope, else raise
    :class:`ProtocolError`.

    Validates shape and the supported-version gate only. A genuinely
    newer-major envelope raises (the consumer abstains); a malformed one
    raises too. Authenticity of ``ct`` is a crypto concern handled when
    the envelope is opened, not here.
    """
    if not isinstance(obj, dict):
        raise ProtocolError(f"envelope must be an object, got {type(obj).__name__}")
    missing = [k for k in ENVELOPE_FIELDS if k not in obj]
    if missing:
        raise ProtocolError(f"envelope missing fields: {', '.join(missing)}")
    if not is_supported_version(obj["v"]):
        raise ProtocolError(f"unsupported protocol version: {obj['v']!r}")
    if not isinstance(obj["ch"], str) or not obj["ch"]:
        raise ProtocolError("envelope 'ch' must be a non-empty string")
    seq = obj["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ProtocolError("envelope 'seq' must be an integer >= 1")
    for k in ("ts", "n", "ct"):
        if not isinstance(obj[k], str) or not obj[k]:
            raise ProtocolError(f"envelope '{k}' must be a non-empty string")
    return obj
