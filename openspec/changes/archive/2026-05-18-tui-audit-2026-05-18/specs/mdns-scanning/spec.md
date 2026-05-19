## MODIFIED Requirements

### Requirement: The state map SHALL expire entries on `remove_service` callbacks AND fall back to a TTL when no remove is observed
The `ServiceListener` `remove_service` callback is the primary source of truth: when the library fires it, the entry SHALL be removed from the snapshot.

The poller SHALL keep tracked entries alive against zeroconf's own record-cache expiry via two complementary paths, applied on every snapshot tick before the TTL backstop:

1. **Cache-refresh (passive).** Walk the state map and bump each entry's `last_seen` to `now` whenever `Zeroconf.cache.entries_with_name(name.lower())` returns at least one non-expired record (filtered via `record.is_expired(now)`). Handles the case where some other zeroconf path (e.g. the library's own periodic re-queries) already refreshed the cache.

2. **Active per-service re-probe.** Periodically (cadence ≥ every 30 s per entry, default 30 s) the poller SHALL schedule a fire-and-forget `AsyncServiceInfo.async_request(zc, 1500)` for each tracked `(type, name)` pair. The probe is dispatched via `self._loop.create_task(self._apply_callback("update", type, name))`; the snapshot loop does NOT await it. A live device responds with fresh SRV / TXT records; `_apply_callback` writes them into `_state` and bumps `last_seen`. An unresponsive device's probe is a no-op (`_state` is not mutated); the entry then falls through to the cache-refresh and TTL paths normally.

As a last-resort sweep for the rare case where neither callback nor cache-hit nor probe-response observes a tracked service (network change, library bug, zeroconf instance died), the poller SHALL also expire entries whose `last_seen` is older than `_BROWSE_TTL_S` (default 300 seconds, exposed for tests). With the active-probe path keeping live services indefinitely-alive, the TTL is a genuine backstop, not the primary eviction mechanism.

#### Scenario: Graceful disappearance
- **WHEN** `zeroconf` fires `remove_service` for a previously-announced service instance
- **THEN** the next snapshot does NOT include that `BonjourDevice`

#### Scenario: Stable service stays alive via cache liveness
- **WHEN** a HomePod re-announces the same AirPlay record every 30 s, so zeroconf does NOT fire `update_service` (the record's info is unchanged) and `last_seen` would otherwise stay frozen at the original `add_service` time
- **AND** zeroconf's DNS cache still holds at least one non-expired record for the service-instance name
- **THEN** the poller bumps the entry's `last_seen` to `now` on the next snapshot tick

#### Scenario: Stable service whose announce TTL is shorter than 300 s stays alive via active probe
- **WHEN** a Bonjour device's announce-published record TTL is 120 s (typical for some HomePods / printers) so zeroconf's DNS cache holds the record only briefly
- **AND** the cache-refresh path runs out of non-expired records after ~2 min of no callback updates
- **THEN** the active per-service re-probe fires every 30 s, hits the device's mDNS responder, gets back fresh SRV / TXT records, refreshes zeroconf's cache, and writes a fresh `last_seen` into `_state` via `_apply_callback`
- **AND** the entry stays in the snapshot indefinitely so long as the device responds

#### Scenario: Active probe does NOT block the snapshot loop
- **WHEN** an unresponsive device causes the probe to hang the full 1500 ms timeout
- **AND** the snapshot interval is 2 s
- **THEN** the snapshot tick still yields within `snapshot_interval_s + ε` (probe runs in its own task; the events generator does NOT await it)

#### Scenario: Silent disappearance falls back to TTL
- **WHEN** a service stopped advertising AND zeroconf's DNS cache no longer holds any non-expired record AND the active probe gets no response for the TTL window
- **AND** `_BROWSE_TTL_S` (default 300 s) has elapsed since `last_seen`
- **THEN** the entry is removed from the snapshot at the next interval

#### Scenario: Cache-refresh is a no-op when the cache returns only expired records
- **WHEN** zeroconf's cache returns records for the service-instance name BUT every record reports `is_expired(now) == True`
- **THEN** the cache-refresh path SHALL NOT bump `last_seen`; the active probe and the TTL backstop govern the entry's fate from this point
