# fix-familiarity-tz-mismatch — design

## Context

`FamiliarityStore` receives a `now: datetime` from every event producer
and stores `now.isoformat()` verbatim as `last_seen`. Producers are
mixed: BLE (`ble.py`), Bonjour (`mdns.py`) and LAN (`lan.py`) pollers
stamp `datetime.now(timezone.utc)` (tz-aware), while the Wi-Fi
connection snapshot (`macos_backend.py`) and therefore `RoamEvent`
(`poller.py`) carry naive `datetime.now()`. The store's own
`flush()` default and the prune cutoff are aware
(`datetime.now().astimezone()`). One AP roam during a session injects a
naive `last_seen` in memory; the next 60-second periodic flush hits
`naive >= aware` in `_prune`'s dictcomp and raises `TypeError`, and
because the TUI's interval-timer flush (`tui.py _familiarity_flush`)
has no guard — unlike the `on_unmount` flush — the whole TUI dies.

The repo already has a documented naive-means-local convention:
`event_log._iso` converts naive datetimes via `.astimezone()` before
emitting.

## Goals / Non-Goals

**Goals:**

- The store never raises on tz-ness, regardless of what producers send
  now or sent in the past (persisted strings included).
- Classification arithmetic (`now - last`, prune cutoff, recency sort)
  is correct across the naive/aware mix, treating naive as local time.
- The periodic TUI flush is fail-soft like every other store touchpoint.

**Non-Goals:**

- Migrating / rewriting the on-disk store file. Normalizing at parse
  time heals old naive strings on the next load with no format change.

## Decisions

- **Normalize at the store boundary, not at every producer.** A single
  `_aware(dt)` helper (`dt.astimezone()` when `dt.tzinfo is None`,
  else `dt` unchanged — `astimezone()` on a naive value interprets it
  as local time, matching `event_log._iso`). Applied in
  `observe_seen` (incoming `now`, so new writes are uniformly aware)
  and `_parse` (read-back, so old records and any record written by a
  future naive caller still compare cleanly). Fixing only the
  producers was rejected as the *sole* fix because it leaves the store
  one new naive caller away from the same crash.
- **Producer hardening on top (second commit).** The codebase had two
  self-consistent tz clusters: BLE/Bonjour/LAN (aware-UTC) and
  Wi-Fi/environment/latency (naive-local). The naive cluster flips to
  aware-local in one move — producers (`macos_backend`, `_helper`,
  `latency`, `tui`'s `NetworkChangeEvent`, `event_log` session_meta)
  AND the consumers doing arithmetic on them (environment ticks,
  sparkline, last-event-ago, joining deadline) — because flipping
  either side alone would create the same naive-vs-aware mix in the
  other direction. The snapshot script's synthetic backends follow for
  the same reason.
- **`EnvironmentMonitor` gets the same boundary normalization.** Its
  rolling-window math (`ingest` trim, `_current_sigma`,
  `aggregate_sigma`) had the identical latent hazard — a mixed-tz
  ingest raised `TypeError` (pinned by the new regression test before
  the fix). Normalizing `ingest`/`fire_events`/`aggregate_sigma` at
  the boundary makes the monitor immune to any future producer mix,
  exactly like the familiarity store.
- **Treat naive as local, not UTC.** Matches the repo-wide `_iso`
  convention and the actual producers (`datetime.now()` is local wall
  clock). Treating naive as UTC would skew classification by the UTC
  offset (8 h here) — enough to flip a `returning` boundary.
- **Guard the periodic flush in the TUI.** `_familiarity_flush` wraps
  `store.flush()` in try/except like `on_unmount` already does. The
  store contract says persistence is best-effort and must never crash
  the monitor; the timer path was the one unguarded touchpoint.

## Risks / Trade-offs

- [Naive-as-local is wrong if a log was produced in another timezone]
  → The store file is machine-local (git-ignored, same host), so the
  producing and reading timezone are the same in practice.
- [`.astimezone()` consults the system tz database on every parse] →
  Negligible: prune runs once a minute over ≤5000 records.
- [Guarding the periodic flush can hide real store bugs] → The same
  trade-off was already accepted for `observe_seen` / `observe_left` /
  shutdown flush; a silently-degraded baseline beats a dead monitor,
  and the regression tests pin the underlying tz behaviour directly.
