"""Familiarity / baseline store — the foundation of the event-design's
"valuable change" intelligence.

Every entity diting observes (BLE device, Wi-Fi AP, LAN host, Bonjour
service) is recorded under a STABLE identity — never a spoofable name —
so the live path can tell an UNFAMILIAR newcomer apart from the user's
habitual ambient environment. A seen event is classified as
``first_time`` / ``occasional`` / ``habitual`` / ``returning`` against the
entity's history BEFORE the current sighting is folded in.

Phase 1 only produces + persists the signal; nothing yet ranks or routes
on it (that is Phases 2–3). The store is process-scoped, persisted to a
git-ignored JSON file, bounded (capped + aged out), and reads fail-soft
(a corrupt record is skipped, never raised) — mirroring ``ReportStore``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Classification thresholds (fixed defaults; a later phase makes these
# scene-tunable).
_HABITUAL_DAYS = 3  # seen on >= this many distinct days -> habitual
_RETURNING_GAP_DAYS = 7  # was habitual, absent > this, now back -> returning

# Bounds so the store can't grow without limit.
_MAX_ENTITIES = 5000
_AGE_OUT_DAYS = 30

# Apple Continuity manufacturer payloads are generic (shared across many
# devices), so they are NOT a per-device key — fall back to (vendor_id,
# name). Mirrors the bluetooth-scanning payload-fusion exclusion.
_COMPANY_APPLE = 0x004C
_PAYLOAD_KEY_MIN_HEXLEN = 8

FIRST_TIME = "first_time"
OCCASIONAL = "occasional"
HABITUAL = "habitual"
RETURNING = "returning"


def default_store_path() -> Path:
    """Default on-disk location for the familiarity store.

    ``./diting-familiarity.json`` in the working directory, overridable via
    ``DITING_FAMILIARITY_STORE`` — mirroring how the companion-pairing state
    (``diting-companion.json``) is sited. The file holds real BSSIDs / MACs /
    BLE payloads, so it is git-ignored like the captures; a public
    ``diting-familiarity.example.json`` documents the shape."""
    override = os.environ.get("DITING_FAMILIARITY_STORE")
    return Path(override).expanduser() if override else Path("diting-familiarity.json")


def familiarity_key(
    kind: str,
    *,
    manufacturer_hex: str | None = None,
    vendor_id: int | None = None,
    name: str | None = None,
    service_data_id: str | None = None,
    vendor: str | None = None,
    bssid: str | None = None,
    mac: str | None = None,
    service: str | None = None,
) -> str | None:
    """A stable, authoritative identity key for an entity, or ``None`` when
    no stable identity exists (caller should then skip familiarity).

    NEVER uses a user-controllable display name as the key. The BLE ladder,
    strongest identity first:

      1. ``ble:<manufacturer_hex>`` — the manufacturer payload (the per-device
         token the payload-fusion uses), non-Apple only.
      2. ``ble:sd:<service_data_id>`` — a per-device id decoded out of a known
         service-data schema (e.g. the MAC a MiBeacon FE95 frame embeds). This
         covers the large class — Mi Band / Huami / Huawei wearables — that
         advertise via service-data with NO manufacturer payload, NO name, and
         a rotating UUID, which would otherwise have no stable identity at all.
      3. ``ble:vn:<vendor_id>/<name>`` — the (company-id, name) fallback.
      4. ``ble:vg:<vendor>`` — a coarse vendor GROUP, the last resort when a
         device was confidently attributed to a manufacturer (via OUI / SIG
         company-id / member-UUID / service-data UUID — all authoritative) but
         carries none of the above per-device tokens. It folds that vendor's
         payload-less, rotating devices into one ambient group rather than
         leaving them unclassified; it is recurrence grouping, not a per-device
         or trust claim.

    Never the rotating UUID.
    """
    if kind == "ble":
        if (
            vendor_id != _COMPANY_APPLE
            and manufacturer_hex
            and len(manufacturer_hex) >= _PAYLOAD_KEY_MIN_HEXLEN
        ):
            return f"ble:{manufacturer_hex}"
        if service_data_id:
            return f"ble:sd:{service_data_id}"
        if vendor_id is not None or name:
            return f"ble:vn:{vendor_id}/{name or ''}"
        if vendor:
            return f"ble:vg:{vendor}"
        return None
    if kind == "ap":
        return f"ap:{bssid}" if bssid else None
    if kind == "lan":
        return f"lan:{mac.lower()}" if mac else None
    if kind == "bonjour":
        return f"bonjour:{service}" if service else None
    return None


@dataclass
class _Record:
    kind: str
    first_seen_ever: str
    last_seen: str
    total_sightings: int = 0
    days: set[str] = field(default_factory=set)
    dwell_ewma_s: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "first_seen_ever": self.first_seen_ever,
            "last_seen": self.last_seen,
            "total_sightings": self.total_sightings,
            "days": sorted(self.days),
            "dwell_ewma_s": self.dwell_ewma_s,
        }

    @classmethod
    def from_json(cls, o: dict[str, Any]) -> "_Record":
        return cls(
            kind=str(o["kind"]),
            first_seen_ever=str(o["first_seen_ever"]),
            last_seen=str(o["last_seen"]),
            total_sightings=int(o.get("total_sightings", 0)),
            days=set(o.get("days", []) or []),
            dwell_ewma_s=(
                float(o["dwell_ewma_s"])
                if o.get("dwell_ewma_s") is not None
                else None
            ),
        )


def _classify(rec: _Record | None, now: datetime) -> str:
    """Familiarity class from the record state BEFORE this sighting."""
    if rec is None:
        return FIRST_TIME
    was_habitual = len(rec.days) >= _HABITUAL_DAYS
    if was_habitual:
        last = _parse(rec.last_seen)
        if last is not None and (now - last) > timedelta(days=_RETURNING_GAP_DAYS):
            return RETURNING
        return HABITUAL
    return OCCASIONAL


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class FamiliarityStore:
    """Persistent per-entity familiarity record. Inject ``path`` for tests."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._records: dict[str, _Record] = {}
        self._load()

    # ---- read (fail-soft) ----

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text("utf-8"))
        except (OSError, ValueError):
            return  # corrupt/unreadable file → start empty, never raise
        if not isinstance(raw, dict):
            return
        for key, obj in raw.items():
            try:
                self._records[key] = _Record.from_json(obj)
            except (KeyError, TypeError, ValueError):
                continue  # skip the corrupt record, keep the rest

    # ---- observe ----

    def observe_seen(
        self, key: str | None, kind: str, now: datetime
    ) -> str | None:
        """Classify ``key`` against its prior history, then fold this sighting
        in. Returns the familiarity class, or ``None`` when ``key`` is None
        (no stable identity — caller omits the field)."""
        if key is None:
            return None
        rec = self._records.get(key)
        cls = _classify(rec, now)
        day = now.date().isoformat()
        ts = now.isoformat()
        if rec is None:
            self._records[key] = _Record(
                kind=kind, first_seen_ever=ts, last_seen=ts,
                total_sightings=1, days={day},
            )
        else:
            rec.last_seen = ts
            rec.total_sightings += 1
            rec.days.add(day)
        return cls

    def observe_left(self, key: str | None, dwell_s: float) -> None:
        """Fold an observed dwell (seen→left span) into the entity's EWMA."""
        if key is None:
            return
        rec = self._records.get(key)
        if rec is None or dwell_s < 0:
            return
        rec.dwell_ewma_s = (
            dwell_s if rec.dwell_ewma_s is None
            else 0.3 * dwell_s + 0.7 * rec.dwell_ewma_s
        )

    # ---- persist (bounded) ----

    def flush(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        self._prune(now)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: r.to_json() for k, r in self._records.items()}
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
            tmp.replace(self._path)
        except OSError:
            pass  # best-effort persistence; never crash the monitor

    def _prune(self, now: datetime) -> None:
        # Age out stale entities, then cap to the most-recently-seen.
        cutoff = now - timedelta(days=_AGE_OUT_DAYS)
        live = {
            k: r for k, r in self._records.items()
            if (_parse(r.last_seen) or now) >= cutoff
        }
        if len(live) > _MAX_ENTITIES:
            ordered = sorted(
                live.items(),
                key=lambda kv: _parse(kv[1].last_seen) or now,
                reverse=True,
            )
            live = dict(ordered[:_MAX_ENTITIES])
        self._records = live

    # ---- introspection (tests / future phases) ----

    def __len__(self) -> int:
        return len(self._records)

    def record(self, key: str) -> _Record | None:
        return self._records.get(key)
