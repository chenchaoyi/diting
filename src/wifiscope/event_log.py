"""JSONL event logger shared by `wifiscope monitor` and the TUI.

Single point of truth for the wire format so both modes produce
byte-identical streams. Schema is locale-stable English (event
type names, state strings, field names) — log analysis scripts
should not break when the user toggles WIFISCOPE_LANG. User-
supplied strings (SSID, AP location names from aps.yaml) flow
through unchanged via ``ensure_ascii=False`` so a Chinese SSID
like ``咖啡馆`` survives readable in the log instead of becoming
``\\u54d6\\u5561\\u9986``.

Durability. File-mode loggers open in append mode with line
buffering AND explicit flush after every write, so each event
hits the kernel page cache before the producer side moves on.
A SIGKILL or hard crash after the flush call does not lose
data — the kernel still writes the cached bytes to disk. Only
a kernel panic or power loss between flush and the next disk
sync window can drop already-emitted events. ``atexit``
registration is the belt-and-suspenders for exit paths that
skip the normal close (Textual exception path, sys.exit on a
worker thread): every file-mode logger registers itself so the
file is closed cleanly even when the host App's on_unmount
does not run.

The logger is forgiving about transient I/O errors — a disk-full
or NFS hiccup must not crash the long-running TUI / monitor. We
log to stderr once per failure class and keep the in-memory
event stream flowing.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import weakref
from datetime import datetime, timezone
from typing import IO, Any

from .events import (
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
    RFStirEvent,
    RoamEvent,
)
from .models import Connection


def _iso(now: datetime) -> str:
    """Compact ISO-8601 with explicit UTC.

    Naive datetimes (no tzinfo) follow Python's convention of
    "local clock time" — that's what ``datetime.now()`` returns
    and what most TUI producers hand us. We must NOT label local
    time as ``+00:00`` UTC: that would silently shift every event
    by the local offset and break any cross-timezone log analysis
    or AI consumer.

    ``datetime.astimezone()`` with no argument is the documented
    way to convert a naive datetime to its local-aware equivalent
    (Python ≥ 3.6); chaining ``.astimezone(timezone.utc)`` then
    yields the canonical UTC form. Aware inputs are normalised
    the same way so all output is stable +00:00.
    """
    if now.tzinfo is None:
        # Promote naive → local-aware → UTC. This single line is
        # what was missing in the previous implementation, which
        # used .replace(tzinfo=utc) and silently labelled local
        # time as UTC.
        now = now.astimezone()
    return now.astimezone(timezone.utc).isoformat()


class EventLogger:
    """Append-only JSONL emitter for wifiscope events.

    Construct with ``EventLogger.to_path(path)`` for a file sink,
    ``EventLogger.to_stdout()`` for stdout (the historical monitor
    behaviour), or ``EventLogger.disabled()`` for a no-op (the
    TUI default — opt in via ``--log`` or WIFISCOPE_LOG).

    All ``emit_*`` calls are best-effort: an exception writing to
    the sink is logged once and then swallowed so the producer
    side keeps running. Callers can ignore the return value.
    """

    def __init__(
        self,
        sink: IO[str] | None,
        *,
        owns_sink: bool = False,
    ) -> None:
        self._sink = sink
        self._owns_sink = owns_sink
        # Last associated BSSID (lower-cased), used to derive
        # link_state edges from raw ConnectionUpdate snapshots.
        # Starts at the sentinel _UNSET so the very first poll
        # always emits an initial state — useful for seeing
        # "session began on AP X" in long-running logs. After that
        # we only emit on connect/disconnect transitions; BSSID-
        # to-BSSID changes go through emit_roam instead.
        self._last_assoc_bssid: str | None | object = _UNSET
        self._io_failed: bool = False

    # ---------- factories ----------

    @classmethod
    def to_path(cls, path: str) -> "EventLogger":
        """Open ``path`` in append mode with line buffering. The
        directory must exist; create it before constructing if
        needed. We never silently mkdir — that would mask typos.

        Each file-mode logger registers a weak-ref atexit hook so
        an unexpected exit path (Textual exception, kill -15,
        a worker calling sys.exit) still flushes and closes the
        file. Already-flushed bytes survive even harder kills
        because line-buffering pushes them through write(2) on
        every newline."""
        sink = open(path, "a", buffering=1, encoding="utf-8")
        logger = cls(sink, owns_sink=True)
        # Weakref so we don't keep the logger alive past intended
        # explicit close(); atexit just needs a function it can
        # call, not the logger object itself.
        ref = weakref.ref(logger)

        def _atexit_close() -> None:
            obj = ref()
            if obj is not None:
                obj.close()

        atexit.register(_atexit_close)
        return logger

    @classmethod
    def to_stdout(cls) -> "EventLogger":
        return cls(sys.stdout, owns_sink=False)

    @classmethod
    def disabled(cls) -> "EventLogger":
        """No-op logger. ``emit_*`` calls return immediately;
        useful as a default in code paths that want a logger
        attribute they can call unconditionally."""
        return cls(None, owns_sink=False)

    # ---------- public emit surface ----------

    def emit_connection_update(
        self,
        conn: Connection | None,
        *,
        now: datetime | None = None,
    ) -> None:
        """Synthesise link_state events from a connection snapshot.

        Edge-triggered: a transition between unassociated and
        associated produces one event. BSSID-to-BSSID changes
        within the same session do NOT — those are surfaced as
        roam events by the consumer separately, and emitting a
        link_state too would double-count the same observation.
        """
        if self._sink is None:
            return
        if now is None:
            now = datetime.now(timezone.utc)
        new_bssid = conn.bssid.lower() if conn and conn.bssid else None
        prev = self._last_assoc_bssid
        if prev is _UNSET:
            # First poll: emit a synthetic "associated" if we have
            # a connection, else stay quiet (no point emitting
            # "session started disassociated" — that's the boring
            # case and it shows up in the next real event anyway).
            if new_bssid is not None and conn is not None:
                self._write({
                    "ts": _iso(now),
                    "type": "link_state",
                    "state": "associated",
                    "ssid": conn.ssid,
                    "bssid": new_bssid,
                })
            self._last_assoc_bssid = new_bssid
            return
        if (prev is None) == (new_bssid is None):
            # Either both None (still disassociated) or both set
            # (still associated, possibly on a different BSSID
            # which roam handles). No link_state edge.
            self._last_assoc_bssid = new_bssid
            return
        if new_bssid is None:
            self._write({
                "ts": _iso(now),
                "type": "link_state",
                "state": "disassociated",
                "ssid": None,
                "bssid": None,
            })
        else:
            assert conn is not None  # for type checker; new_bssid → conn
            self._write({
                "ts": _iso(now),
                "type": "link_state",
                "state": "associated",
                "ssid": conn.ssid,
                "bssid": new_bssid,
            })
        self._last_assoc_bssid = new_bssid

    def emit_link_state(self, event: LinkStateEvent) -> None:
        """Emit a pre-built LinkStateEvent. Provided for callers
        that already produce the event dataclass and want their
        own state-machine; the connection-update path above is
        what wifi consumers should normally use."""
        if self._sink is None:
            return
        self._write({
            "ts": _iso(event.timestamp),
            "type": "link_state",
            "state": event.state,
            "ssid": event.ssid,
            "bssid": event.bssid.lower() if event.bssid else None,
        })

    def emit_roam(
        self, event: RoamEvent, *, kind: str | None = None,
    ) -> None:
        """Emit a roam event. ``kind`` is an optional discriminator
        ('band_switch' if the two BSSIDs belong to the same physical
        AP, 'inter_ap' otherwise) — callers with inventory access
        should compute and pass it; consumers without inventory
        omit it and downstream tooling can re-derive."""
        if self._sink is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "roam",
            "previous_bssid": (
                event.previous_bssid.lower()
                if event.previous_bssid else None
            ),
            "new_bssid": (
                event.new_bssid.lower() if event.new_bssid else None
            ),
            "previous_channel": event.previous_channel,
            "new_channel": event.new_channel,
        }
        if kind is not None:
            payload["kind"] = kind
        self._write(payload)

    def emit_rf_stir(self, event: RFStirEvent) -> None:
        if self._sink is None:
            return
        self._write({
            "ts": _iso(event.timestamp),
            "type": "rf_stir",
            "magnitude_db": event.magnitude_db,
            "location": event.location,
            "bssid": event.bssid.lower() if event.bssid else None,
            "duration_s": event.duration_s,
            "confidence": event.confidence,
            "mode": event.mode,
        })

    def emit_latency_spike(self, event: LatencySpikeEvent) -> None:
        if self._sink is None:
            return
        self._write({
            "ts": _iso(event.timestamp),
            "type": "latency_spike",
            "target": event.target,
            "target_ip": event.target_ip,
            "rtt_ms": event.rtt_ms,
            "loss_pct": event.loss_pct,
        })

    def emit_loss_burst(self, event: LossBurstEvent) -> None:
        if self._sink is None:
            return
        self._write({
            "ts": _iso(event.timestamp),
            "type": "loss_burst",
            "target": event.target,
            "target_ip": event.target_ip,
            "loss_pct": event.loss_pct,
            "lost_in_window": event.lost_in_window,
        })

    # ---------- lifecycle ----------

    def close(self) -> None:
        """Flush and close a file sink. Stdout / no-op are left
        alone. Idempotent — safe to call from multiple teardown
        paths in the TUI."""
        sink = self._sink
        if sink is not None and self._owns_sink:
            try:
                sink.flush()
                sink.close()
            except OSError:
                pass
        self._sink = None

    # ---------- internals ----------

    def _write(self, payload: dict[str, Any]) -> None:
        sink = self._sink
        if sink is None:
            return
        # ensure_ascii=False keeps Chinese / emoji / accented
        # characters readable in `tail -F` instead of escaping
        # them to \uXXXX. Disk size is also smaller.
        # separators=(",", ":") yields the compact one-liner
        # form jq / parsers expect.
        try:
            line = json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            sink.write(line + "\n")
            # Append-mode files set buffering=1 → already line-
            # buffered; stdout may not be when redirected so we
            # call flush() defensively.
            try:
                sink.flush()
            except OSError:
                pass
        except OSError as exc:
            if not self._io_failed:
                # Only log once per logger lifetime so a stuck
                # disk does not spam stderr at 1 Hz.
                print(
                    f"wifiscope: event log write failed: {exc}",
                    file=sys.stderr,
                )
                self._io_failed = True


# Sentinel separate from None so the very first ConnectionUpdate
# can emit a synthetic "associated" event without a prior poll
# being treated as "previously associated to None" (which would
# mean the next None update is a no-op disassociate).
_UNSET = object()
