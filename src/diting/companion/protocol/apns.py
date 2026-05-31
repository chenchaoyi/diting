"""APNs trigger — a content-free doorbell, never a delivery.

The push payload carries only a channel id, a count, and a coarse
category. It MUST NOT contain any real identifier (BSSID, SSID, device
name, hostname, IP). The consumer is woken, pulls + decrypts the actual
events from the relay, and only then assembles human-readable text
locally. The builder here takes only the three safe fields, so it is
structurally incapable of leaking event detail.
"""

from __future__ import annotations

from typing import Any

from .errors import ProtocolError

# The closed set of coarse categories. Each leaks nothing beyond "which
# subsystem" — deliberately broad.
CATEGORIES: frozenset[str] = frozenset({"link", "ble", "lan", "bonjour", "env"})

# Wire event ``type`` -> coarse category. ``session_meta`` maps to None:
# it is a log header, never a push. ``network_change`` is control-plane
# but, if ever forwarded, reads as a link-layer change.
_CATEGORY_BY_TYPE: dict[str, str] = {
    "rf_stir": "env",
    "latency_spike": "link",
    "loss_burst": "link",
    "link_state": "link",
    "roam": "link",
    "network_change": "link",
    "ble_device_seen": "ble",
    "ble_device_left": "ble",
    "bonjour_service_seen": "bonjour",
    "bonjour_service_left": "bonjour",
    "lan_host_seen": "lan",
    "lan_host_left": "lan",
    "lan_host_dhcp_rotation": "lan",
    "lan_active_probe_consented": "lan",
}


def coarse_category(event_type: str) -> str | None:
    """Map a wire event ``type`` to its coarse category, or None for a
    type that is never pushed (e.g. ``session_meta``)."""
    return _CATEGORY_BY_TYPE.get(event_type)


def build_trigger(*, channel: str, count: int, category: str) -> dict[str, Any]:
    """Build the content-free trigger payload: ``{"ch", "n", "c"}``.

    Raises :class:`ProtocolError` on an unknown category or a
    non-positive count. There is no field through which an identifier
    could be passed.
    """
    if category not in CATEGORIES:
        raise ProtocolError(f"unknown coarse category: {category!r}")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ProtocolError("trigger count must be an integer >= 1")
    if not channel:
        raise ProtocolError("trigger channel must be non-empty")
    return {"ch": channel, "n": count, "c": category}
