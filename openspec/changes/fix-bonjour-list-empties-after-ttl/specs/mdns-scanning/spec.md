## MODIFIED Requirements

### Requirement: The state map SHALL expire entries on `remove_service` callbacks AND fall back to a TTL when no remove is observed
The `ServiceListener` `remove_service` callback is the primary source of truth: when the library fires it, the entry SHALL be removed from the snapshot. Before applying the TTL backstop on each snapshot tick, the poller SHALL walk its state map and bump each entry's `last_seen` to `now` whenever zeroconf's DNS cache still holds any non-expired record for that service instance (looked up via `Zeroconf.cache.entries_with_name(name.lower())` filtered through `record.is_expired(now)`). This keeps the local TTL aligned with zeroconf's own record-cache lifetimes — a HomePod re-asserting an unchanged AirPlay record fires no `update_service` callback (zeroconf is change-driven), but zeroconf still holds the record in its cache and the poller SHALL treat the service as alive.

As a last-resort sweep for the rare case where zeroconf neither fires `remove_service` nor keeps the record cached (network change, library bug), the poller SHALL also expire entries whose `last_seen` is older than `_BROWSE_TTL_S` (default 300 seconds, exposed for tests). This default replaces the prior 60 s value — a 1-minute TTL was evicting most of a normal home network's mDNS surface because stable services (HomePods, printers, cameras) rarely change their announced info.

#### Scenario: Graceful disappearance
- **WHEN** `zeroconf` fires `remove_service` for a previously-announced service instance
- **THEN** the next snapshot does NOT include that `BonjourDevice`

#### Scenario: Stable service stays alive via cache liveness
- **WHEN** a HomePod re-announces the same AirPlay record every 30 s, so zeroconf does NOT fire `update_service` (the record's info is unchanged) and `last_seen` would otherwise stay frozen at the original `add_service` time
- **AND** zeroconf's DNS cache still holds at least one non-expired record for the service-instance name
- **THEN** the poller bumps the entry's `last_seen` to `now` on the next snapshot tick
- **AND** the entry SHALL NOT be evicted by the TTL backstop, regardless of how long the service has been silent at the callback layer

#### Scenario: Silent disappearance falls back to TTL
- **WHEN** a service stopped advertising and zeroconf's DNS cache no longer holds any non-expired record for the service-instance name
- **AND** `_BROWSE_TTL_S` (default 300 s) has elapsed since the last cache hit
- **THEN** the entry is removed from the snapshot at the next interval

#### Scenario: Cache-refresh is a no-op when the cache returns only expired records
- **WHEN** zeroconf's cache returns records for the service-instance name BUT every record reports `is_expired(now) == True`
- **THEN** the poller SHALL NOT bump `last_seen`; the entry's age is governed solely by the TTL backstop from this point
