"""Runtime glue: build a sink from saved pairing, drive periodic flush,
and render the status chip.

Activation is opt-in by pairing: if no pairing-state file exists (or
``DITING_COMPANION=0``), :func:`build_sink` returns ``None`` and callers
stay completely inert — nothing is imported from the crypto stack and no
egress happens. So the hot TUI / monitor path pays nothing until the user
runs ``diting companion pair``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..i18n import t

if TYPE_CHECKING:  # avoid importing the crypto stack at module load
    from .sink import CompanionSink

FLUSH_INTERVAL_S = 3.0
# Consecutive fully-failed flushes before the chip names the outage —
# ~9 s at the flush interval, so a transient blip never flashes it.
UNREACHABLE_AFTER_FAILURES = 3
# Envelopes sent per flush. Bounds the per-call blocking time on a slow link
# so a large backlog drains incrementally across periodic cycles instead of
# one all-or-nothing burst that blocks the flush thread for minutes.
DEFAULT_FLUSH_BATCH = 50


def _state_path_if_paired(state_path: Path | None) -> Path | None:
    """Resolve the pairing-state path and return it only if the file
    exists — a cheap check that avoids importing the crypto stack (and
    pynacl) on the common unpaired path."""
    if os.environ.get("DITING_COMPANION") == "0":
        return None
    if state_path is not None:
        path = state_path
    else:
        override = os.environ.get("DITING_COMPANION_STATE")
        path = Path(override).expanduser() if override else Path("diting-companion.json")
    return path if path.exists() else None


def build_sink(state_path: Path | None = None) -> "CompanionSink | None":
    """Build a CompanionSink from saved pairing, or None if not paired."""
    path = _state_path_if_paired(state_path)
    if path is None:
        return None
    # Heavy imports happen only when actually paired.
    from .push_policy import PushPolicy
    from .relay_client import RelayClient
    from .sink import CompanionSink
    from .state import load_state

    st = load_state(path)
    if st is None:
        return None
    client = RelayClient(st.relay_url, st.channel, st.relay_token())
    return CompanionSink(st, client, PushPolicy(), state_path=path)


async def flush_loop(sink: "CompanionSink", *, interval: float = FLUSH_INTERVAL_S) -> None:
    """Periodically drain the relay queue off the event loop. On cancel,
    make a best-effort final drain so a clean shutdown isn't lossy."""
    try:
        while True:
            await asyncio.sleep(interval)
            if sink.client.pending:
                await asyncio.to_thread(sink.flush, DEFAULT_FLUSH_BATCH)
    except asyncio.CancelledError:
        if sink.client.pending:
            try:
                # Best-effort, bounded: a clean quit never hangs the shutdown
                # draining a deep backlog over a slow link.
                await asyncio.to_thread(sink.flush, DEFAULT_FLUSH_BATCH)
            except Exception:
                pass
        raise


def subtitle_chip(sink: "CompanionSink") -> str:
    """Short companion status for the TUI header subtitle."""
    c = sink.client
    if c.pending and c.dropped:
        chip = t("companion: {n} queued, {d} dropped", n=c.pending, d=c.dropped)
    elif c.pending:
        chip = t("companion: {n} queued", n=c.pending)
    elif c.dropped:
        return t("companion: {d} dropped", d=c.dropped)
    else:
        return t("companion: on")
    # A queued backlog reads very differently depending on whether delivery
    # is merely behind or failing outright — name a sustained outage.
    if c.consecutive_failures >= UNREACHABLE_AFTER_FAILURES:
        chip += t(" · relay unreachable")
    return chip
