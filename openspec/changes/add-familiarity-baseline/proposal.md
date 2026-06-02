# Familiarity / baseline layer for transition events

## Why

diting emits ~15 flat, equal-weight transition events (`ble_device_seen`,
`lan_host_seen`, `roam`, …). Each first-sight fires `seen` whether it's the
user's own habitual phone or a stranger's device that just walked past. The
live path has no notion of *familiar vs new*, so it can't surface the actually
valuable signal — "an **unfamiliar** device appeared / lingered." The "what
mattered" intelligence today is retrospective and manual (`analyze.py` /
`--for-llm`); nothing live distinguishes the user's ambient norm from a genuine
newcomer.

This is Phase 1 of the event-design deepening, and the single highest-leverage
piece: a persistent **familiarity baseline** that every later phase (salience
scoring, insight events, threat detection) reads from.

## What Changes

- **A persistent familiarity store** (new `src/diting/familiarity.py`) keyed by
  a STABLE per-entity identity — never a spoofable name:
  - BLE → the payload-fusion key (`manufacturer_hex` for non-Apple; fall back to
    `(vendor_id, name)` when no stable payload), NOT the rotating UUID.
  - Wi-Fi AP → BSSID (+ SSID); LAN host → MAC; Bonjour → service identity.
  Per entity it records `first_seen_ever`, `last_seen`, `total_sightings`,
  `distinct_days_seen` (recurrence), and a typical dwell / RSSI band. It is
  bounded (capped + age-out of entities unseen for N days), fail-soft on read
  (skip corrupt records, like `ReportStore`), and lives as a git-ignored local
  state file (it holds real BSSIDs/MACs/fingerprints).

- **A derived familiarity class** computed when a `seen` event is emitted:
  `first_time` / `occasional` / `habitual` / `returning`, from sighting count +
  distinct-days + absence gap, with sensible defaults (scene-tunable later).

- **A new optional `familiarity` field** on the seen-side transition events
  (`ble_device_seen`, `bonjour_service_seen`, `lan_host_seen`; plus an AP
  familiarity signal on `roam`). Additive and back-compatible: consumers
  tolerate its absence (helper-schema rule); if it crosses the companion wire,
  the `companion-protocol` fixtures regenerate at the same protocol version.

## Impact

- Affected specs: `events` (seen events gain optional `familiarity`), a NEW
  `familiarity-store` capability (the store's contract), and
  `companion-protocol` only if the field crosses the wire (with fixtures
  regenerated; otherwise the field stays desktop-local for now).
- Affected code: new `src/diting/familiarity.py`; `src/diting/events.py` +
  `event_log.py` (carry/emit the field); the seen/left emit sites in
  `ble.py` (reuse the payload-fusion key), `lan.py`, the Bonjour poller, and
  `poller.py` (roam); wiring in `cli.py` to construct + persist the store.
- **Scope limit (honest):** this phase ONLY adds the familiarity signal + the
  store. It does NOT change push/log surfacing, and adds no salience scores,
  insight events, or threat detections — those are Phase 2 (salience + insights,
  live-ified `analyze.py`) and Phase 3 (evil-twin / deauth-storm / follows-you
  tracker). The field is emitted and persisted; nothing yet consumes it for
  ranking.
- No name-based classification: the store key is authoritative (payload
  fingerprint / BSSID / MAC), never a Bonjour name or hostname.
