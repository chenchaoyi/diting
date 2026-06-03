"""Threat engine — Phase 3 of the event-design deepening.

The defensive-security tier. Where the insight engine surfaces *operational*
changes, this watches the same enriched stream for *hostile* ones and emits
`critical`-severity `insight` events (the threat tier):

- ``evil_twin``    — the user lands on the same SSID via a different-vendor AP
                     (OUI mismatch under one network name → impersonation).
- ``deauth_storm`` — a tight burst of disassociations (forced-disconnect
                     pattern; inferred from link state, not 802.11 frames).
- ``follows_you``  — an unfamiliar BLE device present across ≥2 location epochs
                     (a ``network_change`` advances the epoch).

Every detector keys on authoritative, hard-to-spoof signals — BSSID,
OUI/vendor, disassociation timing, the rotation-folded device identity — never a
user-controllable name (the SSID is precisely what an attacker forges).

Like the insight engine it is hermetic + bounded: feed it the wire payloads via
:meth:`observe`, pull fired threats via :meth:`collect` with an injected
``now``. It never raises, ignores its own ``insight`` output, and debounces each
threat per (code, target). It does NOT emit — the TUI drains it on the same
timer that drains the insight engine.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any

from .events import InsightEvent
from .insights import _parse_ts

# Defaults (scene-tunable in a later phase).
_STORM_WINDOW_S = 90      # tight window for a deauth-style burst
_STORM_MIN = 4
_FOLLOWS_MIN_LOCATIONS = 2
_COOLDOWN_S = 300
_MAX_TRACKED_DEVICES = 4096

_UNFAMILIAR = frozenset({"first_time", "occasional"})


class ThreatEngine:
    """Stateful defensive-security detector over the recent event stream."""

    def __init__(
        self,
        *,
        storm_window_s: int = _STORM_WINDOW_S,
        storm_min: int = _STORM_MIN,
        follows_min_locations: int = _FOLLOWS_MIN_LOCATIONS,
        cooldown_s: int = _COOLDOWN_S,
    ) -> None:
        self._storm_window_s = storm_window_s
        self._storm_min = storm_min
        self._follows_min_locations = follows_min_locations
        self._cooldown_s = cooldown_s
        # evil_twin: vendors seen per SSID this session + a point-in-time queue.
        self._ssid_vendors: dict[str, set[str]] = {}
        self._pending: list[tuple[str, str, dict[str, Any], str]] = []
        # deauth_storm: disassociation timestamps.
        self._disassoc: deque[datetime] = deque()
        # follows_you: location epoch + the epochs each unfamiliar device spans.
        self._epoch = 0
        self._device_epochs: dict[str, set[int]] = {}
        self._last_fired: dict[tuple[str, str], datetime] = {}

    # ---------- ingest ----------

    def observe(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        etype = payload.get("type")
        if etype == "insight":
            return
        if etype == "link_state":
            state = payload.get("state")
            if state == "associated":
                self._note_association(
                    payload.get("ssid"), payload.get("bssid"),
                    payload.get("vendor"),
                )
            elif state == "disassociated":
                ts = _parse_ts(payload)
                if ts is not None:
                    self._disassoc.append(ts)
        elif etype == "roam":
            self._note_association(
                payload.get("new_ssid") or payload.get("ssid"),
                payload.get("new_bssid"),
                payload.get("new_vendor"),
            )
        elif etype == "network_change":
            self._epoch += 1
        elif etype == "ble_device_seen":
            if payload.get("familiarity") in _UNFAMILIAR:
                ident = payload.get("identifier")
                if isinstance(ident, str):
                    self._track_device(ident)

    def _note_association(
        self, ssid: Any, bssid: Any, vendor: Any,
    ) -> None:
        # evil_twin keys on the OUI-derived vendor, never the SSID-as-trust.
        # A None vendor (unknown OUI) can't be compared, so it can't fire.
        if not isinstance(ssid, str) or not isinstance(vendor, str) or not vendor:
            return
        seen = self._ssid_vendors.setdefault(ssid, set())
        if seen and vendor not in seen:
            self._pending.append((
                "evil_twin", "critical",
                {
                    "ssid": ssid,
                    "known_vendor": sorted(seen)[0],
                    "new_vendor": vendor,
                    "bssid": bssid,
                },
                ssid,  # cooldown target
            ))
        seen.add(vendor)

    def _track_device(self, ident: str) -> None:
        epochs = self._device_epochs.get(ident)
        if epochs is None:
            if len(self._device_epochs) >= _MAX_TRACKED_DEVICES:
                # Bound the map — drop the oldest-inserted identifier.
                self._device_epochs.pop(next(iter(self._device_epochs)), None)
            epochs = self._device_epochs[ident] = set()
        epochs.add(self._epoch)

    # ---------- evaluate ----------

    def collect(self, now: datetime) -> list[InsightEvent]:
        out: list[InsightEvent] = []

        # evil_twin — point-in-time threats queued during observe.
        pending, self._pending = self._pending, []
        for code, severity, detail, target in pending:
            self._maybe(out, now, code, severity, detail, target)

        # deauth_storm — tight-window disassociation burst.
        cutoff = now - timedelta(seconds=self._storm_window_s)
        while self._disassoc and self._disassoc[0] < cutoff:
            self._disassoc.popleft()
        if len(self._disassoc) >= self._storm_min:
            self._maybe(out, now, "deauth_storm", "critical", {
                "count": len(self._disassoc),
                "window_s": self._storm_window_s,
            }, "")

        # follows_you — an unfamiliar device across ≥N location epochs.
        for ident, epochs in self._device_epochs.items():
            if len(epochs) >= self._follows_min_locations:
                self._maybe(out, now, "follows_you", "critical", {
                    "identifier": ident,
                    "locations": len(epochs),
                }, ident)

        return out

    # ---------- internals ----------

    def _maybe(
        self,
        out: list[InsightEvent],
        now: datetime,
        code: str,
        severity: str,
        detail: dict[str, Any],
        target: str,
    ) -> None:
        key = (code, target)
        last = self._last_fired.get(key)
        if last is not None and (now - last) < timedelta(seconds=self._cooldown_s):
            return
        self._last_fired[key] = now
        out.append(InsightEvent(
            timestamp=now, code=code, severity=severity, detail=detail,
        ))
