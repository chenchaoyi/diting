"""Pairing payload — the contents of the QR the desktop renders.

This is the only channel by which the secretbox key reaches the phone;
it never touches the relay or any server. The payload is encoded as a
compact custom-scheme URI so it is QR-friendly and human-inspectable:

    diting-pair://v1/<channel>?k=<urlsafe_b64_key>&relay=<https_url>[&fp=<fingerprint>]

Fields:
    version      protocol major (path: ``v1``)
    channel      channel id (path segment)
    key_b64      urlsafe-base64 of the 32-byte secretbox key
    relay_url    relay base URL (https expected)
    fingerprint  optional relay TLS pin

``decode_pairing`` raises :class:`ProtocolError` on anything malformed —
the consumer refuses the scan and stores nothing.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from .errors import ProtocolError
from .version import PROTOCOL_VERSION, is_supported_version

SCHEME = "diting-pair"
KEY_BYTES = 32  # libsodium secretbox key length


@dataclass(frozen=True, slots=True)
class PairingPayload:
    version: int
    channel: str
    key_b64: str
    relay_url: str
    fingerprint: str | None = None

    def key_bytes(self) -> bytes:
        """Decode the urlsafe-base64 key to raw bytes. Raises
        :class:`ProtocolError` if it is not 32 valid bytes."""
        return _decode_key(self.key_b64)


def encode_key(raw: bytes) -> str:
    """Urlsafe-base64 (no padding) encode a raw secretbox key."""
    if len(raw) != KEY_BYTES:
        raise ProtocolError(f"key must be {KEY_BYTES} bytes, got {len(raw)}")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_key(key_b64: str) -> bytes:
    try:
        pad = "=" * (-len(key_b64) % 4)
        raw = base64.urlsafe_b64decode(key_b64 + pad)
    except (ValueError, TypeError) as exc:
        raise ProtocolError(f"pairing key is not valid base64: {exc}") from exc
    if len(raw) != KEY_BYTES:
        raise ProtocolError(
            f"pairing key decodes to {len(raw)} bytes, expected {KEY_BYTES}"
        )
    return raw


def encode_pairing(payload: PairingPayload) -> str:
    """Encode a pairing payload to its QR URI string."""
    _decode_key(payload.key_b64)  # fail fast on a bad key
    if not payload.channel:
        raise ProtocolError("pairing channel must be non-empty")
    if "/" in payload.channel:
        raise ProtocolError("pairing channel must not contain '/'")
    scheme = urlsplit(payload.relay_url).scheme
    if scheme not in ("http", "https"):
        raise ProtocolError(f"relay_url must be http(s), got {scheme!r}")
    query: list[tuple[str, str]] = [
        ("k", payload.key_b64),
        ("relay", payload.relay_url),
    ]
    if payload.fingerprint:
        query.append(("fp", payload.fingerprint))
    return (
        f"{SCHEME}://v{payload.version}/{quote(payload.channel, safe='')}"
        f"?{urlencode(query)}"
    )


def decode_pairing(uri: str) -> PairingPayload:
    """Decode a pairing QR URI. Raises :class:`ProtocolError` on any
    structural problem so the consumer can refuse the scan cleanly."""
    if not isinstance(uri, str):
        raise ProtocolError("pairing payload must be a string")
    parts = urlsplit(uri)
    if parts.scheme != SCHEME:
        raise ProtocolError(f"pairing scheme must be {SCHEME!r}, got {parts.scheme!r}")
    host = parts.netloc  # the 'v1' major sits in the authority slot
    if not (host.startswith("v") and host[1:].isdigit()):
        raise ProtocolError(f"pairing version segment malformed: {host!r}")
    version = int(host[1:])
    if not is_supported_version(version):
        raise ProtocolError(f"unsupported pairing version: {version}")
    channel = parts.path.lstrip("/")
    if not channel:
        raise ProtocolError("pairing channel missing")
    q = parse_qs(parts.query, keep_blank_values=False)
    key_list = q.get("k")
    relay_list = q.get("relay")
    if not key_list:
        raise ProtocolError("pairing payload missing key 'k'")
    if not relay_list:
        raise ProtocolError("pairing payload missing 'relay'")
    key_b64 = key_list[0]
    relay_url = relay_list[0]
    _decode_key(key_b64)  # validate
    if urlsplit(relay_url).scheme not in ("http", "https"):
        raise ProtocolError("pairing relay_url must be http(s)")
    fp_list = q.get("fp")
    fingerprint = fp_list[0] if fp_list else None
    return PairingPayload(
        version=version,
        channel=channel,
        key_b64=key_b64,
        relay_url=relay_url,
        fingerprint=fingerprint,
    )


def default_version() -> int:
    return PROTOCOL_VERSION
