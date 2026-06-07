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
- `src/diting/tui.py` — guard the periodic `_familiarity_flush`.
- `tests/test_familiarity.py` — mixed-tz regression coverage.
- No wire-format, schema, or companion-protocol impact; the on-disk
  store file stays back-compatible (naive strings simply parse to
  local-aware on the next load).
