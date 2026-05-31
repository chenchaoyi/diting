"""Desktop pairing state — the generated channel id + secretbox key.

Stored in a git-ignored JSON file (``./diting-companion.json`` by
default, ``DITING_COMPANION_STATE`` to override — mirroring how
``aps.yaml`` resolves cwd-relative with ``DITING_INVENTORY``). It holds a
secret (the channel key), so it carries the same privacy treatment as
``aps.yaml``: never committed, a public ``diting-companion.example.json``
ships instead.

The monotonic envelope sequence persists here too (``last_seq``) so the
cursor keeps advancing across restarts and never reuses a number.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nacl.utils import random as nacl_random

from .protocol import auth, pairing
from .protocol.version import PROTOCOL_VERSION

KEY_BYTES = 32


def default_state_path() -> Path:
    override = os.environ.get("DITING_COMPANION_STATE")
    return Path(override).expanduser() if override else Path("diting-companion.json")


@dataclass(slots=True)
class PairingState:
    version: int
    channel: str
    key_b64: str
    relay_url: str
    fingerprint: str | None = None
    created: str | None = None
    last_seq: int = 0

    # ---------- construction ----------

    @classmethod
    def generate(cls, relay_url: str, *, fingerprint: str | None = None) -> "PairingState":
        return cls(
            version=PROTOCOL_VERSION,
            channel=secrets.token_urlsafe(18),
            key_b64=pairing.encode_key(nacl_random(KEY_BYTES)),
            relay_url=relay_url,
            fingerprint=fingerprint,
            created=datetime.now().astimezone().isoformat(),
            last_seq=0,
        )

    # ---------- derived ----------

    def key_bytes(self) -> bytes:
        return self.to_payload().key_bytes()

    def to_payload(self) -> pairing.PairingPayload:
        return pairing.PairingPayload(
            version=self.version,
            channel=self.channel,
            key_b64=self.key_b64,
            relay_url=self.relay_url,
            fingerprint=self.fingerprint,
        )

    def qr_uri(self) -> str:
        return pairing.encode_pairing(self.to_payload())

    def relay_token(self) -> str:
        return auth.derive_relay_token(self.key_bytes())

    # ---------- persistence ----------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "channel": self.channel,
            "key_b64": self.key_b64,
            "relay_url": self.relay_url,
            "fingerprint": self.fingerprint,
            "created": self.created,
            "last_seq": self.last_seq,
        }

    def save(self, path: Path | None = None) -> Path:
        path = path or default_state_path()
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        try:  # best-effort: a secret file should not be world-readable
            path.chmod(0o600)
        except OSError:
            pass
        return path

    def next_seq(self, path: Path | None = None) -> int:
        """Advance + persist the monotonic sequence, returning the new value."""
        self.last_seq += 1
        self.save(path)
        return self.last_seq


def load_state(path: Path | None = None) -> PairingState | None:
    """Load pairing state, or None if not paired. Malformed state raises."""
    path = path or default_state_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PairingState(
        version=data["version"],
        channel=data["channel"],
        key_b64=data["key_b64"],
        relay_url=data["relay_url"],
        fingerprint=data.get("fingerprint"),
        created=data.get("created"),
        last_seq=int(data.get("last_seq", 0)),
    )


def clear_state(path: Path | None = None) -> bool:
    """Remove the pairing-state file. Returns True if one existed."""
    path = path or default_state_path()
    if path.exists():
        path.unlink()
        return True
    return False


def render_qr(data: str) -> str:
    """Render ``data`` as a compact half-block QR for the terminal."""
    import io

    import segno

    buf = io.StringIO()
    segno.make(data, error="m").terminal(buf, compact=True)
    return buf.getvalue()
