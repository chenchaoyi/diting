## Why

User report (2026-05-18): the Bonjour list shows real services for
the first ~1 minute after launch, then goes back to the
"(no Bonjour devices yet — scanning...)" empty state and never
recovers. Other surfaces (Wi-Fi, BLE) are unaffected; the user's
network is still alive and the same HomePods / printers / cameras
are still on it.

Root cause: `BonjourPoller._expire_stale` evicts entries whose
`last_seen` is older than 60 seconds. `last_seen` only refreshes when
zeroconf fires `add_service` or `update_service` — and
`update_service` only fires when the service's **info** changes
(TXT records / port / addresses). A HomePod re-announcing the same
AirPlay record every 30 seconds does NOT trigger any callback in
zeroconf's API. After 60 seconds with no info change, the entry
expires from our state map even though the service is alive and
zeroconf's own DNS cache still holds the records.

The TTL backstop was sound in principle (last-resort sweep for
silent disappearances), but at 60s it's evicting most of the link's
mDNS surface. The HomePod / Apple TV / printer population is full
of services whose info is stable over hours.

## What Changes

### `mdns-scanning` — bump `last_seen` from zeroconf's own cache each snapshot tick
- **MODIFIED:** every snapshot iteration of `BonjourPoller.events`
  SHALL, before applying `_expire_stale`, walk the current state map
  and bump each entry's `last_seen` to `now` whenever zeroconf's
  DNS cache still holds any non-expired record for that service
  instance. This keeps the local TTL aligned with zeroconf's own
  record-cache lifetimes (which respect each record's published
  TTL value), so a service whose info is stable but whose records
  are still being seen on the wire SHALL NOT prematurely expire.
- **MODIFIED:** the `_BROWSE_TTL_S` default SHALL be raised from
  60 s to 300 s. With the cache-refresh path above this is now a
  last-resort sweep for the rare case where zeroconf neither fires
  `remove_service` nor keeps the record cached (network change,
  library bug); 300 s gives a noticeably-disappeared service
  enough time to be flagged before we drop it.

### Backwards compatibility
- No public API change. `BonjourScanUpdate` shape unchanged.
- The `ttl_s` constructor kwarg keeps its meaning ("how long to
  hold a state entry when zeroconf has lost the cache"), only the
  default value moves.

## Out of Scope

- Replacing our state map with zeroconf's own cache entirely.
  Bigger refactor; the cache-refresh approach keeps the rest of
  the poller's contract (snapshot interval, sort order, vendor
  resolution chain) verbatim.
- Restructuring how Apple-side services handle "goodbye"
  announces. zeroconf already fires `remove_service` on those;
  our state map cleans up via that path today and that path is
  unchanged.
