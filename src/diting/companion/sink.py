"""CompanionSink — the join point.

Given a wire payload dict (the exact dict the JSONL writer emits), decide
push-worthiness (PushPolicy), seal it under the channel key (crypto), and
enqueue it on the relay client. ``offer`` is cheap and non-blocking so it
is safe to call from the TUI / monitor event loop; a separate periodic
``flush`` (driven by the wiring layer) drains the queue to the relay.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .crypto import seal_event
from .protocol.apns import coarse_category
from .push_policy import PushPolicy
from .push_summary import push_summary
from .relay_client import RelayClient
from .state import PairingState

# Desktop-local fields that must NOT cross the companion wire. The mobile
# side runs strict `validate_event`, which rejects unknown keys; until a
# coordinated companion-protocol version carries them, strip here. The
# JSONL log keeps them — only the sealed copy is pruned.
_LOCAL_ONLY_FIELDS = frozenset({"familiarity"})


class CompanionSink:
    def __init__(
        self,
        state: PairingState,
        client: RelayClient,
        policy: PushPolicy,
        *,
        state_path: Path | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = state
        self._client = client
        self._policy = policy
        self._state_path = state_path
        self._monotonic = monotonic
        self._key = state.key_bytes()

    @property
    def client(self) -> RelayClient:
        return self._client

    def offer(self, payload: dict[str, Any]) -> bool:
        """Consider one wire payload for forwarding. Returns True if it was
        sealed and enqueued, False if the policy declined it."""
        if not self._policy.should_push(payload, self._monotonic()):
            return False
        if any(k in payload for k in _LOCAL_ONLY_FIELDS):
            payload = {
                k: v for k, v in payload.items() if k not in _LOCAL_ONLY_FIELDS
            }
        seq = self._state.next_seq(self._state_path)
        envelope = seal_event(
            self._key,
            channel=self._state.channel,
            seq=seq,
            ts=datetime.now().astimezone().isoformat(),
            payload=payload,
        )
        self._client.enqueue(
            envelope,
            category=coarse_category(payload.get("type", "")),
            summary=push_summary(payload),
        )
        return True

    def flush(self):
        return self._client.flush()
