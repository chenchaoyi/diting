"""Which events are worth forwarding to the phone.

Reuses the ``_watchdog`` primitives so "worth a push" stays aligned with
"worth a macOS banner": the same per-(type, target) silence window
coalesces bursts, and ``rf_stir`` rides the same confidence gate. Routine
high-volume departures (``*_left``), the ``session_meta`` header, and the
audit-only ``lan_active_probe_consented`` are not pushed by default.
"""

from __future__ import annotations

from typing import Any

from .._watchdog import SilenceClock, WatchdogConfig, should_notify_stir

# Event types worth a push by default — arrivals / transitions / anomalies.
DEFAULT_PUSH_TYPES: frozenset[str] = frozenset({
    "roam",
    "link_state",
    "latency_spike",
    "loss_burst",
    "rf_stir",
    "network_change",
    "ble_device_seen",
    "bonjour_service_seen",
    "lan_host_seen",
    "lan_host_dhcp_rotation",
})


def _target(payload: dict[str, Any]) -> str:
    """A stable per-event key for the silence window, so repeated events
    about the same thing coalesce rather than each firing a push."""
    t = payload.get("type")
    if t in ("latency_spike", "loss_burst"):
        return str(payload.get("target_ip", "?"))
    if t == "rf_stir":
        return str(payload.get("location") or payload.get("bssid") or "?")
    if t == "roam":
        return str(payload.get("new_bssid", "?"))
    if t == "link_state":
        return str(payload.get("bssid") or payload.get("state", "?"))
    if t == "ble_device_seen":
        return str(payload.get("identifier", "?"))
    if t == "bonjour_service_seen":
        return str(payload.get("name", "?"))
    if t in ("lan_host_seen", "lan_host_dhcp_rotation"):
        return str(payload.get("mac", "?"))
    if t == "network_change":
        return str(payload.get("new_router_ip", "?"))
    return str(t)


class PushPolicy:
    """Decides, statefully, whether a wire payload should be forwarded."""

    def __init__(
        self,
        *,
        config: WatchdogConfig | None = None,
        push_types: frozenset[str] = DEFAULT_PUSH_TYPES,
    ) -> None:
        self._config = config or WatchdogConfig()
        self._push_types = push_types
        self._clock = SilenceClock(self._config.silence_window_s)

    def should_push(self, payload: dict[str, Any], now: float) -> bool:
        etype = payload.get("type")
        if etype not in self._push_types:
            return False
        if etype == "rf_stir" and not should_notify_stir(payload, self._config.stir_confidence):
            return False
        return self._clock.should_fire(etype, _target(payload), now)
