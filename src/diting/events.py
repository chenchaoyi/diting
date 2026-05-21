"""Unified event ring buffer + JSONL serialisation.

Twelve event types share one schema and one in-memory ring (last 100):

    rf_stir              — RSSI variance crossed threshold
    latency_spike        — rtt > 200 ms AND > 5× median
    loss_burst           — 3 of last 5 ping samples lost
    roam                 — BSSID change
    link_state           — associated / disassociated
    ble_device_seen      — BLE device first observed
    ble_device_left      — BLE device aged out of TTL
    bonjour_service_seen — Bonjour service first announced
    bonjour_service_left — Bonjour service removed / TTL evicted
    lan_host_seen        — non-self / non-gateway MAC entered ARP cache
    lan_host_left        — host gone silent past _HOST_LEFT_TIMEOUT_S
    lan_host_dhcp_rotation — known MAC observed at a new IP

Layer 1 (Events panel) and Layer 2 (modal EventsScreen) read from
the same in-memory ring buffer; Layer 3 (``diting monitor``)
streams JSON Lines to stdout / file.

The contract — twelve-event vocabulary, ring-buffer semantics,
JSONL key stability, NetworkChangeEvent-as-control-plane — is
pinned in ``openspec/specs/events/spec.md``.
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


# ---------- BLE / Bonjour / LAN transition events ----------
#
# Seven new event types covering subsystem state transitions. Each
# follows the same `@dataclass(frozen=True, slots=True)` shape as
# the original five and rides the same EventRing + JSONL writer.
# Emission contracts live in the BLE / Bonjour / LAN poller specs;
# the schema lives here.

@dataclass(frozen=True, slots=True)
class BLEDeviceSeenEvent:
    timestamp: datetime
    identifier: str        # rotation-folded stable id
    name: str | None
    vendor: str | None
    rssi_dbm: int | None
    service_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BLEDeviceLeftEvent:
    timestamp: datetime
    identifier: str
    name: str | None
    vendor: str | None
    last_rssi_dbm: int | None
    service_categories: tuple[str, ...]
    seen_for_seconds: float


@dataclass(frozen=True, slots=True)
class BonjourServiceSeenEvent:
    timestamp: datetime
    service_type: str
    name: str
    host: str | None
    category: str | None
    vendor: str | None
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BonjourServiceLeftEvent:
    timestamp: datetime
    service_type: str
    name: str
    host: str | None
    category: str | None
    vendor: str | None
    seen_for_seconds: float


@dataclass(frozen=True, slots=True)
class LANHostSeenEvent:
    timestamp: datetime
    mac: str
    ip: str
    vendor: str | None
    hostname: str | None
    bonjour_name: str | None
    is_randomised_mac: bool


@dataclass(frozen=True, slots=True)
class LANHostLeftEvent:
    timestamp: datetime
    mac: str
    ip: str
    vendor: str | None
    hostname: str | None
    bonjour_name: str | None
    is_randomised_mac: bool
    seen_for_seconds: float
    # None when the host never responded to ICMP this session.
    last_reachable_ago_seconds: float | None


@dataclass(frozen=True, slots=True)
class LANHostDHCPRotationEvent:
    timestamp: datetime
    mac: str
    previous_ip: str
    new_ip: str
    vendor: str | None
    hostname: str | None
    bonjour_name: str | None


# Union of every event the ring buffer accepts. ``RoamEvent`` is
# imported from poller so we don't redefine it.
Event = (
    RFStirEvent
    | LatencySpikeEvent
    | LossBurstEvent
    | LinkStateEvent
    | NetworkChangeEvent
    | RoamEvent
    | BLEDeviceSeenEvent
    | BLEDeviceLeftEvent
    | BonjourServiceSeenEvent
    | BonjourServiceLeftEvent
    | LANHostSeenEvent
    | LANHostLeftEvent
    | LANHostDHCPRotationEvent
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
    # ---------- new transition events ----------
    #
    # None fields are omitted via `_drop_none`; tuple fields go
    # through unchanged so callers see [] for empty (informative —
    # "no services" is distinct from "field absent").
    if isinstance(event, BLEDeviceSeenEvent):
        return _drop_none({
            "ts": ts,
            "type": "ble_device_seen",
            "identifier": event.identifier,
            "name": event.name,
            "vendor": event.vendor,
            "rssi_dbm": event.rssi_dbm,
            "service_categories": list(event.service_categories),
        })
    if isinstance(event, BLEDeviceLeftEvent):
        return _drop_none({
            "ts": ts,
            "type": "ble_device_left",
            "identifier": event.identifier,
            "name": event.name,
            "vendor": event.vendor,
            "last_rssi_dbm": event.last_rssi_dbm,
            "service_categories": list(event.service_categories),
            "seen_for_seconds": round(event.seen_for_seconds, 1),
        })
    if isinstance(event, BonjourServiceSeenEvent):
        return _drop_none({
            "ts": ts,
            "type": "bonjour_service_seen",
            "service_type": event.service_type,
            "name": event.name,
            "host": event.host,
            "category": event.category,
            "vendor": event.vendor,
            "addresses": list(event.addresses),
        })
    if isinstance(event, BonjourServiceLeftEvent):
        return _drop_none({
            "ts": ts,
            "type": "bonjour_service_left",
            "service_type": event.service_type,
            "name": event.name,
            "host": event.host,
            "category": event.category,
            "vendor": event.vendor,
            "seen_for_seconds": round(event.seen_for_seconds, 1),
        })
    if isinstance(event, LANHostSeenEvent):
        return _drop_none({
            "ts": ts,
            "type": "lan_host_seen",
            "mac": event.mac,
            "ip": event.ip,
            "vendor": event.vendor,
            "hostname": event.hostname,
            "bonjour_name": event.bonjour_name,
            "is_randomised_mac": event.is_randomised_mac,
        })
    if isinstance(event, LANHostLeftEvent):
        payload = {
            "ts": ts,
            "type": "lan_host_left",
            "mac": event.mac,
            "ip": event.ip,
            "vendor": event.vendor,
            "hostname": event.hostname,
            "bonjour_name": event.bonjour_name,
            "is_randomised_mac": event.is_randomised_mac,
            "seen_for_seconds": round(event.seen_for_seconds, 1),
        }
        if event.last_reachable_ago_seconds is not None:
            payload["last_reachable_ago_seconds"] = round(
                event.last_reachable_ago_seconds, 1,
            )
        return _drop_none(payload)
    if isinstance(event, LANHostDHCPRotationEvent):
        return _drop_none({
            "ts": ts,
            "type": "lan_host_dhcp_rotation",
            "mac": event.mac,
            "previous_ip": event.previous_ip,
            "new_ip": event.new_ip,
            "vendor": event.vendor,
            "hostname": event.hostname,
            "bonjour_name": event.bonjour_name,
        })
    raise TypeError(f"unsupported event type: {type(event).__name__}")


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    """Strip keys whose value is None.

    Tuple-typed empty values pass through as `[]` (informative —
    "no services" is distinct from "field absent"). Bools (e.g.
    `is_randomised_mac=False`) survive unchanged.
    """
    return {k: v for k, v in d.items() if v is not None}


def _to_utc_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
