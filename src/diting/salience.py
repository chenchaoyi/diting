"""Event salience — a coarse, familiarity-weighted ranking of how much an
event should grab attention.

Phase 2a of the event-design deepening. Phase 1 stamped each seen event with a
``familiarity`` class; this turns that (plus the event's intrinsic kind and
signal strength) into a single ordered tier — ``noise`` < ``low`` <
``notable`` < ``high`` — that the push gate (and, later, the analyzer + TUI)
ranks on. The user's habitual ambient environment scores ``noise`` and stops
flooding the phone; genuine newcomers and anomalies still surface.

Pure + stateless: it reads only the wire payload (``type``, ``familiarity``,
authoritative signal fields), never a spoofable display name, and never raises
— an unrecognised shape abstains (returns ``None``) so the caller omits the
field.
"""

from __future__ import annotations

from typing import Any

from .familiarity import FIRST_TIME, HABITUAL, OCCASIONAL, RETURNING

# Ordered tiers. Keep the names stable — they land in the JSONL and gate the
# push, so renaming is a wire/format change.
NOISE = "noise"
LOW = "low"
NOTABLE = "notable"
HIGH = "high"

_RANK: dict[str, int] = {NOISE: 0, LOW: 1, NOTABLE: 2, HIGH: 3}

# A BLE arrival this strong is physically close — a first-time device right
# next to you is more worth knowing about than one at the edge of range.
_CLOSE_RSSI_DBM = -60

# Arrivals whose salience is weighted by how familiar the entity is.
_ARRIVAL_TYPES = frozenset({
    "ble_device_seen",
    "bonjour_service_seen",
    "lan_host_seen",
})


def tier_rank(tier: str | None) -> int:
    """Numeric rank for comparison; an unknown / absent tier ranks below
    ``noise`` so it never satisfies a positive threshold on its own."""
    if tier is None:
        return -1
    return _RANK.get(tier, -1)


def meets_threshold(tier: str | None, minimum: str) -> bool:
    """True when ``tier`` is at least ``minimum``. An unknown/absent ``tier``
    does NOT meet any threshold — callers that want a missing field to *pass*
    must special-case its absence (the push gate does)."""
    return tier_rank(tier) >= _RANK.get(minimum, 0)


def _arrival_tier(payload: dict[str, Any]) -> str:
    """Familiarity-weighted tier for an arrival. Absent familiarity yields
    ``low`` (never ``noise``) so a run without a familiarity store keeps its
    pre-Phase-2 push behaviour."""
    fam = payload.get("familiarity")
    if fam == HABITUAL:
        base = NOISE
    elif fam == OCCASIONAL:
        base = LOW
    elif fam == RETURNING:
        base = NOTABLE
    elif fam == FIRST_TIME:
        base = NOTABLE
        rssi = payload.get("rssi_dbm")
        if (
            payload.get("type") == "ble_device_seen"
            and isinstance(rssi, (int, float))
            and rssi >= _CLOSE_RSSI_DBM
        ):
            base = HIGH
    else:
        # No familiarity signal — can't rank, so don't invent noise.
        base = LOW
    # The at-launch warmup dump is "what was already here", not a fresh
    # arrival — never let it elevate past low.
    if payload.get("at_launch") and tier_rank(base) > _RANK[LOW]:
        base = LOW
    return base


def salience(payload: dict[str, Any]) -> str | None:
    """Rank one wire payload, or ``None`` for types we don't score.

    Never raises: a missing / wrong-typed field falls through to a sensible
    default or abstains.
    """
    if not isinstance(payload, dict):
        return None
    etype = payload.get("type")

    # Insights carry their own severity — map it straight to a tier.
    if etype == "insight":
        sev = payload.get("severity")
        if sev in ("warn", "critical"):  # critical = the threat tier
            return HIGH
        if sev == "note":
            return NOTABLE
        return LOW

    # Intrinsic anomalies — salient regardless of familiarity.
    if etype == "loss_burst":
        return HIGH
    if etype == "latency_spike":
        return NOTABLE
    if etype == "network_change":
        return NOTABLE
    if etype == "rf_stir":
        conf = payload.get("confidence")
        if conf == "high":
            return HIGH
        if conf == "medium":
            return NOTABLE
        return LOW
    if etype == "link_state":
        return NOTABLE if payload.get("state") == "disassociated" else LOW

    # Roam: routine radio hops are low; cross-AP roams rank by AP familiarity.
    if etype == "roam":
        if payload.get("kind") == "band_switch":
            return LOW
        return _arrival_tier(payload)

    if etype in _ARRIVAL_TYPES:
        return _arrival_tier(payload)

    # Departures + DHCP churn: rarely attention-worthy.
    if isinstance(etype, str) and etype.endswith("_left"):
        return NOISE
    if etype == "lan_host_dhcp_rotation":
        return LOW

    # session_meta, connection_update, audit lines, unknown types: abstain.
    return None
