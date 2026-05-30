"""Per-channel relay auth — an HMAC bearer derived from the channel key.

The relay must authenticate requests per channel WITHOUT learning the
secretbox key (end-to-end encryption). The producer and consumer each
derive the same bearer token from the channel key::

    token = urlsafe_b64( HMAC-SHA256(key, RELAY_AUTH_CONTEXT) )

and present it as ``Authorization: Bearer <token>``. The token is a
one-way function of the key, so the relay seeing it cannot recover the
key. The relay binds a channel to ``sha256(token)`` on first contact
(trust-on-first-use) and rejects later mismatches — it stores only the
hash, never the bearer itself.

Derivation is stdlib-only (no libsodium), so it is shared by the desktop
producer here and mirrored by the diting-mobile consumer in Dart; the
``relay-auth.json`` fixture pins the expected value for cross-repo
conformance.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

RELAY_AUTH_CONTEXT = b"diting-companion/v1 relay-auth"


def derive_relay_token(key: bytes) -> str:
    """Derive the relay bearer token from the 32-byte channel key."""
    mac = hmac.new(key, RELAY_AUTH_CONTEXT, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")


def token_hash(token: str) -> str:
    """The hex sha256 the relay stores for trust-on-first-use binding.
    Mirrored by the Worker's ``tokenHash``."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()
