## ADDED Requirements

### Requirement: `BonjourPoller` SHALL emit transition events when services enter and leave its tracked state
`BonjourPoller` SHALL emit `BonjourServiceSeenEvent` when a `(service_type, name)` pair newly enters `_state` — either via the zeroconf `add_service` callback OR via an `update_service` callback that lands on a previously-absent key (the "cache warm-up" race).

`BonjourPoller` SHALL emit `BonjourServiceLeftEvent` when a `(service_type, name)` pair is removed from `_state` — either via the zeroconf `remove_service` callback OR via the TTL backstop's eviction sweep.

The poller's events queue SHALL carry these new transition events alongside the existing `BonjourScanUpdate` snapshots so a single TUI consumer loop receives both kinds.

#### Scenario: `add_service` fires `BonjourServiceSeenEvent`
- **WHEN** zeroconf fires `add_service` for `(_airplay._tcp.local., Blue Pod._airplay._tcp.local.)` and the entry didn't exist in `_state`
- **THEN** `BonjourServiceSeenEvent` is enqueued with the resolved fields (`host`, `category`, `vendor`, `addresses`)

#### Scenario: TTL backstop fires `BonjourServiceLeftEvent`
- **WHEN** a tracked Bonjour entry's `last_seen` exceeds `_BROWSE_TTL_S` AND zeroconf has not fired `remove_service` for it
- **THEN** `BonjourServiceLeftEvent` is enqueued with `seen_for_seconds = last_seen - first_seen`; the entry is removed from `_state`

#### Scenario: Active probe refresh does NOT re-emit seen
- **WHEN** the active per-service re-probe finds a tracked service still alive (cache-refresh path bumps `last_seen`)
- **THEN** no `BonjourServiceSeenEvent` is emitted — only first-time entries fire seen
