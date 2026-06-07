# fix-familiarity-tz-mismatch

## Why

A live session crashed (2026-06-07) with `TypeError: can't compare
offset-naive and offset-aware datetimes` in `FamiliarityStore._prune`,
killing the TUI ~60 s after launch. The store records each sighting's
timestamp verbatim: BLE / Bonjour / LAN pollers stamp events tz-aware
(UTC), but the Wi-Fi connection snapshot — and therefore every
`RoamEvent` — is stamped with naive `datetime.now()`. One roam plants a
naive `last_seen` in memory, and the next periodic flush compares it
against an aware prune cutoff and raises. The periodic flush timer has
no crash guard, so the whole TUI dies.

## What Changes

- `FamiliarityStore` normalizes every timestamp to tz-aware local at
  its boundary (the same naive-means-local convention `event_log._iso`
  documents): `observe_seen` normalizes the incoming `now` before
  storing; `_parse` normalizes records read back from disk, healing any
  already-persisted naive strings without a migration.
- `_classify`'s `now - last` subtraction is covered by the same
  normalization (same latent hazard, same fix).
- The TUI's periodic familiarity flush gets the same fail-soft guard
  the shutdown flush already has — a store bug must degrade the
  baseline, never crash the monitor.
- **Producer hardening (follow-up in the same change):** every runtime
  producer that stamped naive `datetime.now()` now stamps aware-local
  (`Connection` / `ScanResult` in `macos_backend` + `_helper`,
  `LatencySample` in `latency`, `NetworkChangeEvent` and the
  environment-collection ticks in `tui`, `session_meta` in
  `event_log`), and `EnvironmentMonitor` — which had the same latent
  naive-vs-aware comparison hazard in its rolling-window math — gets
  the same boundary normalization as the familiarity store. The
  snapshot script's synthetic backends follow.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `familiarity-store`: the persist/fail-soft requirement is extended —
  the store SHALL tolerate any mix of naive and tz-aware timestamps
  across observe, classify, and prune without raising, normalizing
  naive values as local time.

## Impact

- `src/diting/familiarity.py` — timestamp normalization at the store
  boundary (`observe_seen`, `_parse`).
- `src/diting/tui.py` — guard the periodic `_familiarity_flush`; flip
  the naive-cluster sites (sparkline default now, last-event-ago,
  joining deadline, environment ticks, `NetworkChangeEvent`).
- `src/diting/environment.py` — `_aware()` boundary normalization on
  `ingest` / `fire_events` / `aggregate_sigma`; internal nows aware.
- `src/diting/macos_backend.py`, `src/diting/_helper.py`,
  `src/diting/latency.py`, `src/diting/event_log.py` — producers stamp
  aware-local.
- `scripts/tui_snapshot.py` — synthetic backends stamp aware-local.
- `tests/test_familiarity.py`, `tests/test_environment.py`,
  `tests/test_tui_helpers.py` — mixed-tz regression coverage.
- No wire-format, schema, or companion-protocol impact (`event_log.
  _iso` already normalized emitted timestamps); the on-disk store file
  stays back-compatible (naive strings simply parse to local-aware on
  the next load).
