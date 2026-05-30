"""JSONL event logger shared by `diting monitor` and the TUI.

Single point of truth for the wire format so both modes produce
byte-identical streams. Schema is locale-stable English (event
type names, state strings, field names) — log analysis scripts
should not break when the user toggles DITING_LANG. User-
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
import socket
import sys
import weakref
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import IO, Any, Callable

from .events import (
    BLEDeviceLeftEvent,
    BLEDeviceSeenEvent,
    BonjourServiceLeftEvent,
    BonjourServiceSeenEvent,
    LANActiveProbeConsentedEvent,
    LANHostDHCPRotationEvent,
    LANHostLeftEvent,
    LANHostSeenEvent,
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
    NetworkChangeEvent,
    RFStirEvent,
    RoamEvent,
)
from .models import Connection


def _iso(now: datetime) -> str:
    """Compact ISO-8601 anchored to the producer's LOCAL timezone.

    Naive datetimes (Python's `datetime.now()`) carry the device's
    local clock by convention; aware UTC datetimes get converted
    back to local. Every emitted timestamp therefore looks like
    ``2026-05-08T08:50:31.123456+08:00`` — the wall-clock value is
    immediately readable to the user reading the file in the
    timezone they were sitting in, *and* the explicit ``+08:00``
    offset means downstream cross-timezone analysis (sorting,
    AI consumers, comparing logs across machines) stays correct
    via standard ISO-8601 parsing.

    Earlier versions wrote either naive-as-UTC (the bug we just
    fixed) or true UTC. The latter forced every reader to do
    mental arithmetic when grepping their own log; the user
    explicitly asked to swap to local+offset, which gives both
    sides what they need.
    """
    if now.tzinfo is None:
        now = now.astimezone()       # naive → local-aware
    else:
        now = now.astimezone()       # aware → local-aware (no-op tz already local)
    return now.isoformat()


class EventLogger:
    """Append-only JSONL emitter for diting events.

    Construct with ``EventLogger.to_path(path)`` for a file sink,
    ``EventLogger.to_stdout()`` for stdout (the historical monitor
    behaviour), or ``EventLogger.disabled()`` for a no-op (the
    TUI default — opt in via ``--log`` or DITING_LOG).

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
        # Session-meta is written exactly once, on first call. The
        # idempotency flag lets callers ask for it unconditionally
        # without double-writing if the codepath fires twice.
        self._session_meta_written: bool = False
        # Optional tap: receives each emitted payload dict (a copy) just
        # before it is written. The companion sink registers here so it
        # forwards the exact bytes the JSONL writer produces — no second
        # serialiser to drift. None by default; an observer makes the
        # logger build + tap payloads even when there is no file sink.
        self._observer: "Callable[[dict[str, Any]], None] | None" = None

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

    def emit_session_meta(
        self,
        *,
        scene: str,
        scene_source: str,
        ssid: str | None = None,
        gateway_ip: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Write the JSONL session header. Idempotent — only the
        first call per logger emits.

        Called by the CLI immediately after constructing the logger,
        before any other ``emit_*``. Downstream tools (the analyzer,
        the ``--for-llm`` bundle, third-party ``jq`` consumers) read
        this line to know what kind of environment the data came
        from. Per-event lines don't carry the scene, only this
        header does — keeps JSONL size honest at scale.

        Fields included are those listed in
        ``openspec/specs/event-log/spec.md``. PII surface kept
        intentionally narrow: hostname is in (anonymizable downstream);
        BSSID is NOT (could doxx physical location).
        """
        if self._sink is None and self._observer is None:
            return
        if self._session_meta_written:
            return
        if now is None:
            now = datetime.now()
        try:
            version = _pkg_version("diting")
        except PackageNotFoundError:
            # Editable install in a worktree where the dist-info
            # hasn't been laid down (rare; CI / source checkouts).
            # Surface as "unknown" rather than crash session header.
            version = "unknown"
        payload: dict[str, Any] = {
            "ts": _iso(now),
            "type": "session_meta",
            "scene": scene,
            "scene_source": scene_source,
            "diting_version": version,
            "ssid": ssid,
            "gateway_ip": gateway_ip,
            "hostname": socket.gethostname(),
        }
        self._emit(payload)
        self._session_meta_written = True

    def emit_connection_update(
        self,
        conn: Connection | None,
        *,
        now: datetime | None = None,
        vendor: str | None = None,
    ) -> None:
        """Synthesise link_state events from a connection snapshot.

        Edge-triggered: a transition between unassociated and
        associated produces one event. BSSID-to-BSSID changes
        within the same session do NOT — those are surfaced as
        roam events by the consumer separately, and emitting a
        link_state too would double-count the same observation.

        ``vendor`` is the manufacturer name resolved from the
        BSSID's OUI prefix (caller's responsibility — keeps the
        logger free of inventory/network dependencies). Included
        verbatim in the associated-state payload when supplied.
        """
        if self._sink is None and self._observer is None:
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
                payload = {
                    "ts": _iso(now),
                    "type": "link_state",
                    "state": "associated",
                    "ssid": conn.ssid,
                    "bssid": new_bssid,
                }
                if vendor:
                    payload["vendor"] = vendor
                self._emit(payload)
            self._last_assoc_bssid = new_bssid
            return
        if (prev is None) == (new_bssid is None):
            # Either both None (still disassociated) or both set
            # (still associated, possibly on a different BSSID
            # which roam handles). No link_state edge.
            self._last_assoc_bssid = new_bssid
            return
        if new_bssid is None:
            self._emit({
                "ts": _iso(now),
                "type": "link_state",
                "state": "disassociated",
                "ssid": None,
                "bssid": None,
            })
        else:
            assert conn is not None  # for type checker; new_bssid → conn
            payload = {
                "ts": _iso(now),
                "type": "link_state",
                "state": "associated",
                "ssid": conn.ssid,
                "bssid": new_bssid,
            }
            if vendor:
                payload["vendor"] = vendor
            self._emit(payload)
        self._last_assoc_bssid = new_bssid

    def emit_link_state(self, event: LinkStateEvent) -> None:
        """Emit a pre-built LinkStateEvent. Provided for callers
        that already produce the event dataclass and want their
        own state-machine; the connection-update path above is
        what wifi consumers should normally use."""
        if self._sink is None and self._observer is None:
            return
        self._emit({
            "ts": _iso(event.timestamp),
            "type": "link_state",
            "state": event.state,
            "ssid": event.ssid,
            "bssid": event.bssid.lower() if event.bssid else None,
        })

    def emit_roam(
        self,
        event: RoamEvent,
        *,
        kind: str | None = None,
        ssid: str | None = None,
        previous_vendor: str | None = None,
        new_vendor: str | None = None,
    ) -> None:
        """Emit a roam event with optional context.

        ``kind`` discriminates 'band_switch' (same physical AP,
        different radio) vs 'inter_ap' (different physical AP) —
        the caller computes this from inventory.

        ``ssid`` is the network name at roam time. Carried so a
        log reader can spot SSID changes that imply a different
        physical network (rare, but it does happen — same SSID
        across home and office triggers seamless laptop roams
        the user did not intend).

        ``previous_vendor`` / ``new_vendor`` are the manufacturer
        names resolved from the two BSSIDs' OUI prefixes. A
        vendor change across a roam (e.g. Xiaomi → Aruba) is the
        clearest single signal that the user has crossed between
        physically separate networks.
        """
        if self._sink is None and self._observer is None:
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
        if ssid is not None:
            payload["ssid"] = ssid
        # The new schema carries the SSID on each side of the
        # roam (added in wifi-event-ssid-and-name-enrichment). Emit
        # when set; skip when None so old log entries stay
        # diff-stable against pre-enrichment runs.
        if event.previous_ssid is not None:
            payload["previous_ssid"] = event.previous_ssid
        if event.new_ssid is not None:
            payload["new_ssid"] = event.new_ssid
        if previous_vendor:
            payload["previous_vendor"] = previous_vendor
        if new_vendor:
            payload["new_vendor"] = new_vendor
        self._emit(payload)

    def emit_rf_stir(self, event: RFStirEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "rf_stir",
            "magnitude_db": event.magnitude_db,
            "location": event.location,
            "bssid": event.bssid.lower() if event.bssid else None,
            "duration_s": event.duration_s,
            "confidence": event.confidence,
            "mode": event.mode,
        }
        # SSID added in wifi-event-ssid-and-name-enrichment. Emit
        # when set; skip when None so old log entries stay
        # diff-stable against pre-enrichment runs.
        if event.ssid is not None:
            payload["ssid"] = event.ssid
        self._emit(payload)

    def emit_latency_spike(self, event: LatencySpikeEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        self._emit({
            "ts": _iso(event.timestamp),
            "type": "latency_spike",
            "target": event.target,
            "target_ip": event.target_ip,
            "rtt_ms": event.rtt_ms,
            "loss_pct": event.loss_pct,
        })

    def emit_loss_burst(self, event: LossBurstEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        self._emit({
            "ts": _iso(event.timestamp),
            "type": "loss_burst",
            "target": event.target,
            "target_ip": event.target_ip,
            "loss_pct": event.loss_pct,
            "lost_in_window": event.lost_in_window,
        })

    def emit_network_change(self, event: NetworkChangeEvent) -> None:
        """Emit a subnet-change event. The TUI fires one whenever
        the gateway IP transitions — even within the same SSID —
        so downstream readers can split per-network statistics
        cleanly.
        """
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "network_change",
            "previous_router_ip": event.previous_router_ip,
            "new_router_ip": event.new_router_ip,
        }
        if event.previous_ssid is not None:
            payload["previous_ssid"] = event.previous_ssid
        if event.new_ssid is not None:
            payload["new_ssid"] = event.new_ssid
        if event.previous_bssid is not None:
            payload["previous_bssid"] = event.previous_bssid.lower()
        if event.new_bssid is not None:
            payload["new_bssid"] = event.new_bssid.lower()
        self._emit(payload)

    # ---------- BLE / Bonjour / LAN transition events ----------
    #
    # All seven follow the same shape as the existing emit methods:
    # locale-stable English `type` value, snake_case keys, None
    # fields omitted, tuple fields emit as JSON arrays even when
    # empty. The no-op (sink=None) logger silently swallows all
    # seven, matching the existing methods' contract.

    def emit_ble_device_seen(self, event: BLEDeviceSeenEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "ble_device_seen",
            "identifier": event.identifier,
            "service_categories": list(event.service_categories),
        }
        if event.name is not None:
            payload["name"] = event.name
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        if event.rssi_dbm is not None:
            payload["rssi_dbm"] = event.rssi_dbm
        # Device type under `device_type`, NOT `type` — the envelope
        # already owns `type` for the event kind. Optional + None-omitted.
        if event.device_type is not None:
            payload["device_type"] = event.device_type
        if event.device_class is not None:
            payload["device_class"] = event.device_class
        if event.at_launch:
            payload["at_launch"] = True
        self._emit(payload)

    def emit_ble_device_left(self, event: BLEDeviceLeftEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "ble_device_left",
            "identifier": event.identifier,
            "service_categories": list(event.service_categories),
            "seen_for_seconds": round(event.seen_for_seconds, 1),
        }
        if event.name is not None:
            payload["name"] = event.name
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        if event.last_rssi_dbm is not None:
            payload["last_rssi_dbm"] = event.last_rssi_dbm
        if event.device_type is not None:
            payload["device_type"] = event.device_type
        if event.device_class is not None:
            payload["device_class"] = event.device_class
        self._emit(payload)

    def emit_bonjour_service_seen(self, event: BonjourServiceSeenEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "bonjour_service_seen",
            "service_type": event.service_type,
            "name": event.name,
            "addresses": list(event.addresses),
        }
        if event.host is not None:
            payload["host"] = event.host
        if event.category is not None:
            payload["category"] = event.category
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        self._emit(payload)

    def emit_bonjour_service_left(self, event: BonjourServiceLeftEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "bonjour_service_left",
            "service_type": event.service_type,
            "name": event.name,
            "seen_for_seconds": round(event.seen_for_seconds, 1),
        }
        if event.host is not None:
            payload["host"] = event.host
        if event.category is not None:
            payload["category"] = event.category
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        self._emit(payload)

    def emit_lan_host_seen(self, event: LANHostSeenEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "lan_host_seen",
            "mac": event.mac.lower(),
            "ip": event.ip,
            "is_randomised_mac": event.is_randomised_mac,
        }
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        if event.hostname is not None:
            payload["hostname"] = event.hostname
        if event.bonjour_name is not None:
            payload["bonjour_name"] = event.bonjour_name
        self._emit(payload)

    def emit_lan_host_left(self, event: LANHostLeftEvent) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "lan_host_left",
            "mac": event.mac.lower(),
            "ip": event.ip,
            "is_randomised_mac": event.is_randomised_mac,
            "seen_for_seconds": round(event.seen_for_seconds, 1),
        }
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        if event.hostname is not None:
            payload["hostname"] = event.hostname
        if event.bonjour_name is not None:
            payload["bonjour_name"] = event.bonjour_name
        if event.last_reachable_ago_seconds is not None:
            payload["last_reachable_ago_seconds"] = round(
                event.last_reachable_ago_seconds, 1,
            )
        self._emit(payload)

    def emit_lan_host_dhcp_rotation(
        self, event: LANHostDHCPRotationEvent,
    ) -> None:
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "lan_host_dhcp_rotation",
            "mac": event.mac.lower(),
            "previous_ip": event.previous_ip,
            "new_ip": event.new_ip,
        }
        if event.vendor is not None:
            payload["vendor"] = event.vendor
        if event.hostname is not None:
            payload["hostname"] = event.hostname
        if event.bonjour_name is not None:
            payload["bonjour_name"] = event.bonjour_name
        self._emit(payload)

    def emit_lan_active_probe_consented(
        self, event: LANActiveProbeConsentedEvent,
    ) -> None:
        """Audit-trail entry: user explicitly consented to a one-shot
        LAN active-probe in public scene. See proposal D3 / D12 in
        `openspec/changes/expand-lan-identification/design.md`.
        """
        if self._sink is None and self._observer is None:
            return
        payload: dict[str, Any] = {
            "ts": _iso(event.timestamp),
            "type": "lan_active_probe_consented",
            "scene": event.scene,
            "nbns_packets": event.nbns_packets,
            "ssdp_packets": event.ssdp_packets,
            "mdns_packets": event.mdns_packets,
        }
        if event.ssid is not None:
            payload["ssid"] = event.ssid
        self._emit(payload)

    def set_observer(self, observer: "Callable[[dict[str, Any]], None] | None") -> None:
        """Register (or clear) a tap that receives every emitted payload.

        The companion sink uses this so it forwards the exact dict the
        JSONL writer emits. The observer is best-effort and must never
        raise into the logger; exceptions from it are swallowed.
        """
        self._observer = observer

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

    def _emit(self, payload: dict[str, Any]) -> None:
        """Tap the observer (best-effort) then write to the sink if any.
        Every emitted payload flows through here."""
        if self._observer is not None:
            try:
                self._observer(dict(payload))
            except Exception:  # an observer must never break logging
                pass
        if self._sink is not None:
            self._write(payload)

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
                    f"diting: event log write failed: {exc}",
                    file=sys.stderr,
                )
                self._io_failed = True


# Sentinel separate from None so the very first ConnectionUpdate
# can emit a synthetic "associated" event without a prior poll
# being treated as "previously associated to None" (which would
# mean the next None update is a no-op disassociate).
_UNSET = object()
