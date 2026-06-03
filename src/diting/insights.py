"""Live insight engine — Phase 2b + 2c of the event-design deepening.

Phases 1–2a enriched each raw transition with a ``familiarity`` class and a
``salience`` tier. This watches the enriched stream and synthesizes
``InsightEvent``s when a *valuable change* is detected: a cluster of unfamiliar
arrivals (2b), or the live-able subset of the offline ``analyze.py`` heuristics
(2c — repeated disassociations, loss, latency-without-loss, band-steering).

The engine is hermetic + testable without a real environment: feed it the same
wire payloads the logger emits via :meth:`observe`, then pull fired insights via
:meth:`collect` with an injected ``now``. It keeps bounded rolling windows,
never raises on a malformed payload, ignores its own ``insight`` output, and
debounces each insight ``code`` with a cooldown so a sustained condition fires
once per window rather than once per observation.

It does NOT emit — emitting from inside the logger's observer tap would re-enter
the logger. The caller (the TUI) drains :meth:`collect` on a timer and routes
the results through the normal ring + log + notify path.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any

from .events import InsightEvent
from .i18n import t

# Window + threshold defaults (scene-tunable in a later phase).
_CLUSTER_WINDOW_S = 120
_CLUSTER_MIN = 3
_WINDOW_S = 600           # rolling window for the 2c heuristics
_COOLDOWN_S = 300         # per-code debounce
_DISASSOC_MIN = 3
_ROAM_MIN = 5
_BAND_STEER_RATIO = 0.7

_ARRIVAL_TYPES = frozenset({
    "ble_device_seen", "bonjour_service_seen", "lan_host_seen",
})


def _parse_ts(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class InsightEngine:
    """Stateful detector over the recent enriched event stream."""

    def __init__(
        self,
        *,
        cluster_window_s: int = _CLUSTER_WINDOW_S,
        cluster_min: int = _CLUSTER_MIN,
        window_s: int = _WINDOW_S,
        cooldown_s: int = _COOLDOWN_S,
    ) -> None:
        self._cluster_window_s = cluster_window_s
        self._cluster_min = cluster_min
        self._window_s = window_s
        self._cooldown_s = cooldown_s
        # Rolling windows (timestamps, newest at the right).
        self._arrivals: deque[datetime] = deque()           # first_time arrivals
        self._disassoc: deque[datetime] = deque()
        self._loss: deque[tuple[datetime, float]] = deque()
        self._latency: deque[datetime] = deque()
        self._roams: deque[tuple[datetime, bool]] = deque()  # (ts, is_band_switch)
        self._last_fired: dict[str, datetime] = {}

    # ---------- ingest ----------

    def observe(self, payload: Any) -> None:
        """Fold one wire payload into the rolling windows. Best-effort: a
        malformed payload (non-dict, missing/!parseable ts, missing fields) is
        silently skipped. ``insight`` payloads are ignored so the engine never
        feeds on its own output."""
        if not isinstance(payload, dict):
            return
        etype = payload.get("type")
        if etype == "insight":
            return
        ts = _parse_ts(payload)
        if ts is None:
            return
        if etype in _ARRIVAL_TYPES:
            if payload.get("familiarity") == "first_time":
                self._arrivals.append(ts)
        elif etype == "link_state":
            if payload.get("state") == "disassociated":
                self._disassoc.append(ts)
        elif etype == "loss_burst":
            loss = payload.get("loss_pct")
            self._loss.append((ts, float(loss) if isinstance(loss, (int, float)) else 0.0))
        elif etype == "latency_spike":
            self._latency.append(ts)
        elif etype == "roam":
            self._roams.append((ts, payload.get("kind") == "band_switch"))

    # ---------- evaluate ----------

    def collect(self, now: datetime) -> list[InsightEvent]:
        """Prune the windows to ``now``, evaluate the detectors, and return the
        insights that fired (respecting per-code cooldown). Idempotent w.r.t.
        cooldown: calling twice in quick succession yields a fired insight only
        on the first call."""
        self._prune(now)
        out: list[InsightEvent] = []

        # 2b — a cluster of unfamiliar arrivals.
        recent_arrivals = self._within(self._arrivals, now, self._cluster_window_s)
        if len(recent_arrivals) >= self._cluster_min:
            self._maybe(out, now, "new_device_cluster", "note", {
                "count": len(recent_arrivals),
                "window_s": self._cluster_window_s,
            })

        # 2c — repeated disassociations.
        disassoc = self._within(self._disassoc, now, self._window_s)
        if len(disassoc) >= _DISASSOC_MIN:
            self._maybe(out, now, "repeated_disassociates", "warn", {
                "count": len(disassoc),
            })

        # 2c — loss observed.
        loss = [(ts, pct) for ts, pct in self._loss if ts >= now - timedelta(seconds=self._window_s)]
        if loss:
            self._maybe(out, now, "loss_observed", "warn", {
                "peak_loss_pct": round(max(pct for _, pct in loss), 1),
            })

        # 2c — latency spikes WITHOUT loss (jitter, not link failure).
        latency = self._within(self._latency, now, self._window_s)
        if latency and not loss:
            self._maybe(out, now, "latency_without_loss", "note", {
                "spikes": len(latency),
            })

        # 2c — aggressive band-steering.
        roams = [(ts, b) for ts, b in self._roams if ts >= now - timedelta(seconds=self._window_s)]
        if len(roams) >= _ROAM_MIN:
            band = sum(1 for _, b in roams if b)
            if band / len(roams) > _BAND_STEER_RATIO:
                self._maybe(out, now, "band_steering", "info", {
                    "roams": len(roams),
                    "band_switches": band,
                })

        return out

    # ---------- internals ----------

    def _maybe(
        self,
        out: list[InsightEvent],
        now: datetime,
        code: str,
        severity: str,
        detail: dict[str, Any],
    ) -> None:
        last = self._last_fired.get(code)
        if last is not None and (now - last) < timedelta(seconds=self._cooldown_s):
            return
        self._last_fired[code] = now
        out.append(InsightEvent(
            timestamp=now, code=code, severity=severity, detail=detail,
        ))

    @staticmethod
    def _within(dq: "deque[datetime]", now: datetime, window_s: int) -> list[datetime]:
        cutoff = now - timedelta(seconds=window_s)
        return [ts for ts in dq if ts >= cutoff]

    def _prune(self, now: datetime) -> None:
        # Drop entries older than the widest window we care about.
        widest = max(self._window_s, self._cluster_window_s)
        cutoff = now - timedelta(seconds=widest)
        while self._arrivals and self._arrivals[0] < cutoff:
            self._arrivals.popleft()
        while self._disassoc and self._disassoc[0] < cutoff:
            self._disassoc.popleft()
        while self._loss and self._loss[0][0] < cutoff:
            self._loss.popleft()
        while self._latency and self._latency[0] < cutoff:
            self._latency.popleft()
        while self._roams and self._roams[0][0] < cutoff:
            self._roams.popleft()


def format_insight_summary(code: str, detail: dict[str, Any] | None) -> str:
    """A localised one-line summary for an insight, from its stable ``code`` +
    structured ``detail``. Used by the TUI row + the macOS notification body;
    never stored in the JSONL (which keeps only ``code`` + ``detail``)."""
    d = detail or {}
    if code == "new_device_cluster":
        return t("{n} unfamiliar devices appeared together", n=d.get("count", "?"))
    if code == "repeated_disassociates":
        return t("Wi-Fi dropped {n} times recently", n=d.get("count", "?"))
    if code == "loss_observed":
        return t("Packet loss observed (peak {pct}%)", pct=d.get("peak_loss_pct", "?"))
    if code == "latency_without_loss":
        return t("Latency spikes without loss — likely jitter")
    if code == "band_steering":
        return t(
            "AP band-steering: {n} roams, mostly band switches",
            n=d.get("roams", "?"),
        )
    # Phase 3 threats (critical severity).
    if code == "evil_twin":
        return t(
            "Possible evil twin: SSID {ssid} now on a {vendor} AP",
            ssid=d.get("ssid", "?"), vendor=d.get("new_vendor", "?"),
        )
    if code == "deauth_storm":
        return t("Possible deauth storm: {n} rapid disconnects", n=d.get("count", "?"))
    if code == "follows_you":
        return t(
            "A device has stayed with you across {n} locations",
            n=d.get("locations", "?"),
        )
    return code
