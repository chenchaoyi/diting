"""Human-readable one-line summary for a push notification.

Simplified scheme (per product call): the doorbell carries the actual
event detail in cleartext so the phone notification is useful at a glance,
rather than a content-free "new activity". The event detail here is the
same low-sensitivity data the app already shows; the full event still
rides the E2E-encrypted envelope for the timeline / report. Localised via
``t()`` so the push follows the desktop's language.
"""

from __future__ import annotations

from typing import Any

from ..i18n import t


def _label(*candidates: Any) -> str:
    for c in candidates:
        if c:
            return str(c)
    return "?"


def push_summary(payload: dict[str, Any]) -> str:
    """A short notification body for one wire event."""
    etype = payload.get("type")
    p = payload
    if etype == "ble_device_seen":
        return t("BLE nearby: {name}", name=_label(p.get("name"), p.get("vendor"), p.get("identifier")))
    if etype == "bonjour_service_seen":
        return t("New service: {name}", name=_label(p.get("name"), p.get("service_type")))
    if etype == "lan_host_seen":
        return t("New on Wi-Fi: {name}", name=_label(p.get("hostname"), p.get("bonjour_name"), p.get("ip"), p.get("mac")))
    if etype == "lan_host_dhcp_rotation":
        return t("{name} moved to {ip}", name=_label(p.get("hostname"), p.get("bonjour_name"), p.get("mac")), ip=_label(p.get("new_ip")))
    if etype == "roam":
        return t("Roamed to {bssid}", bssid=_label(p.get("new_bssid")))
    if etype == "link_state":
        if p.get("state") == "associated":
            return t("Connected: {ssid}", ssid=_label(p.get("ssid"), p.get("bssid")))
        return t("Disconnected")
    if etype == "latency_spike":
        return t("Latency spike on {target}: {ms} ms", target=_label(p.get("target_ip"), p.get("target")), ms=_label(p.get("rtt_ms")))
    if etype == "loss_burst":
        return t("Packet loss on {target}: {pct}%", target=_label(p.get("target_ip"), p.get("target")), pct=_label(p.get("loss_pct")))
    if etype == "rf_stir":
        return t("RF stir at {loc}", loc=_label(p.get("location"), p.get("bssid")))
    if etype == "network_change":
        return t("Network changed → {ip}", ip=_label(p.get("new_router_ip")))
    if etype == "insight":
        # The localised one-liner for the insight/threat (from its code +
        # nested detail), so the phone's doorbell shows the actual finding.
        from ..insights import format_insight_summary
        return format_insight_summary(str(p.get("code", "")), p.get("detail"))
    return str(etype)
