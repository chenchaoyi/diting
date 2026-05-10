"""Unified event ring buffer + JSONL serialisation.

Five event types share one schema and one in-memory ring (last 100):

    rf_stir       — RSSI variance crossed threshold
    latency_spike — rtt > 200 ms AND > 5× median
    loss_burst    — 3 of last 5 ping samples lost
    roam          — BSSID change
    link_state    — associated / disassociated

Layer 1 (Events panel) and Layer 2 (modal EventsScreen) read from
the same in-memory ring buffer; Layer 3 (``wifiscope monitor``)
streams JSON Lines to stdout / file.

The contract — five-event vocabulary, ring-buffer semantics, JSONL
key stability, NetworkChangeEvent-as-control-plane — is pinned in
``openspec/specs/events/spec.md``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .environment import RFStirEvent
from .latency import LatencySample
from .poller import RoamEvent


@dataclass(frozen=True, slots=True)
class LatencySpikeEvent:
    timestamp: datetime
    target: str           # 'router' | 'wan'
    target_ip: str
    rtt_ms: float
    loss_pct: float


@dataclass(frozen=True, slots=True)
class LossBurstEvent:
    timestamp: datetime
    target: str
    target_ip: str
    loss_pct: float
    lost_in_window: int


@dataclass(frozen=True, slots=True)
class LinkStateEvent:
    timestamp: datetime
    state: str            # 'associated' | 'disassociated'
    bssid: str | None
    ssid: str | None


@dataclass(frozen=True, slots=True)
class NetworkChangeEvent:
    """The user's gateway IP changed (subnet hop).

    Fires when ConnectionUpdate.router_ip transitions to a new
    value — typically because the user roamed to a physically
    different network (home → office, café → mobile hotspot)
    even when the SSID happens to match. The TUI uses this event
    as the trigger to rebuild the LatencyPoller around the new
    gateway / WAN-anchor; downstream analysis tools use it as a
    segmentation marker so per-network statistics do not get
    smeared together.
    """
    timestamp: datetime
    previous_router_ip: str | None
    new_router_ip: str | None
    previous_ssid: str | None = None
    new_ssid: str | None = None
    previous_bssid: str | None = None
    new_bssid: str | None = None


# Union of every event the ring buffer accepts. ``RoamEvent`` is
# imported from poller so we don't redefine it.
Event = (
    RFStirEvent
    | LatencySpikeEvent
    | LossBurstEvent
    | LinkStateEvent
    | NetworkChangeEvent
    | RoamEvent
)


class EventRing:
    """Bounded FIFO of recent events.

    Default capacity 100 (per spec's "ring buffer of last 100 events").
    Newest events live at the right; readers either iterate or copy
    via :meth:`snapshot`.
    """

    def __init__(self, capacity: int = 100) -> None:
        self._buf: deque[Event] = deque(maxlen=capacity)

    def push(self, event: Event) -> None:
        self._buf.append(event)

    def extend(self, events: Iterable[Event]) -> None:
        for ev in events:
            self.push(ev)

    def snapshot(self) -> list[Event]:
        """Newest-first list. The TUI's Events panel renders the
        leading entries straight; the modal scrolls through the
        whole thing."""
        return list(reversed(self._buf))

    def __len__(self) -> int:
        return len(self._buf)


def event_to_jsonl(event: Event) -> str:
    """Serialize one event to a single-line JSON document.

    Matches the schema from the spec (UTC ISO-8601 timestamp, type
    discriminator, type-specific fields). All timestamps are
    rendered as ``...Z`` UTC suffixes regardless of the original
    timezone, since downstream consumers (Home Assistant, log
    pipelines) tend to assume UTC.
    """
    return json.dumps(_event_to_dict(event), separators=(",", ":"))


def _event_to_dict(event: Event) -> dict[str, Any]:
    ts = _to_utc_iso(event.timestamp)
    if isinstance(event, RFStirEvent):
        return {
            "ts": ts,
            "type": "rf_stir",
            "magnitude_db": event.magnitude_db,
            "location": event.location,
            "bssid": event.bssid,
            "duration_s": event.duration_s,
            "confidence": event.confidence,
            "mode": event.mode,
        }
    if isinstance(event, LatencySpikeEvent):
        return {
            "ts": ts,
            "type": "latency_spike",
            "target": event.target,
            "target_ip": event.target_ip,
            "rtt_ms": round(event.rtt_ms, 1),
            "loss_pct": round(event.loss_pct, 1),
        }
    if isinstance(event, LossBurstEvent):
        return {
            "ts": ts,
            "type": "loss_burst",
            "target": event.target,
            "target_ip": event.target_ip,
            "loss_pct": round(event.loss_pct, 1),
            "lost_in_window": event.lost_in_window,
        }
    if isinstance(event, LinkStateEvent):
        return {
            "ts": ts,
            "type": "link_state",
            "state": event.state,
            "bssid": event.bssid,
            "ssid": event.ssid,
        }
    if isinstance(event, RoamEvent):
        kind = "inter_ap"
        # Spec's roam JSON allows 'kind: inter_ap' / 'kind: band_switch';
        # we cannot tell the two apart without an inventory lookup, so
        # callers wanting band_switch label re-emit through their own
        # wrapper. The default JSONL output reports inter_ap for
        # downstream pipelines, which is the safe / informative default.
        return {
            "ts": ts,
            "type": "roam",
            "previous_bssid": event.previous_bssid,
            "new_bssid": event.new_bssid,
            "kind": kind,
        }
    raise TypeError(f"unsupported event type: {type(event).__name__}")


def _to_utc_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
