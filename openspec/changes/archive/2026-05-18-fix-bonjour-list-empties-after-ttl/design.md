# Design

## D1. Why `update_service` doesn't fire on a "still here" announce

RFC 6762 / 6763 has services re-announce at a backoff cadence
(typically 30 s for the first re-announce, growing toward an hour).
zeroconf's `ServiceListener` callbacks are change-driven:

- `add_service` fires when a record for a new `(type, name)` first
  enters the cache.
- `update_service` fires when an existing record's *info* changes
  (TXT records mutate, port flips, address set grows / shrinks).
- `remove_service` fires when the last record for a `(type, name)`
  expires from the cache.

A HomePod that re-asserts its existing record fires no callback at
all — zeroconf simply refreshes the record's own internal TTL inside
its DNS cache. Our state-map's `last_seen` stayed bound to the most
recent callback firing, so a stable HomePod aged out after 60 s.

## D2. The cache-refresh path

Each snapshot tick, before applying `_expire_stale`, the poller walks
its `_state` map and asks zeroconf's DNS cache whether any
non-expired record exists for each tracked `(type, name)` pair. The
check uses `Zeroconf.cache.entries_with_name(name.lower())` (the
library's documented lookup) and filters out expired records via
`record.is_expired(now)`.

When at least one record is still alive, the poller writes
`replace(dev, last_seen=now)` back into `_state`. When zero records
remain, the entry is left alone — `_expire_stale` is the next step
in the loop and will drop it normally.

Performance: an O(N) walk where N is the number of tracked services
(typically 5 – 50 on a home network, 50 – 200 on a corporate one).
Each lookup is a dict access plus an iteration over a list that's
usually 1 – 3 records long. Cheap; runs at the snapshot cadence
(every 2 s by default).

## D3. Why bump the TTL from 60 s to 300 s

The TTL is now a true backstop, not a primary eviction mechanism.
The reasons it might still fire:

1. zeroconf's socket dropped (interface flap, sleep / wake) — the
   library stopped receiving any traffic for some seconds.
2. A library-level bug where the cache holds a record past its
   real RFC-specified lifetime.
3. `entries_with_name` returns a record that's expired but we
   missed the `record.is_expired(now)` check (defensive: the
   helper handles this).

300 s lines up with the longest typical Bonjour re-announce
backoff. A service that's been quiet for 5 full minutes AND that
zeroconf no longer caches is almost certainly gone; the user is
not actively missing it.

## D4. Test strategy

Three new unit tests against `BonjourPoller`:

1. **Cache liveness bumps `last_seen`.** Seed `_state` with an entry
   whose `last_seen` is 90 s ago, stub `zc.cache.entries_with_name`
   to return one non-expired record, run a snapshot tick, assert
   the entry is still present and `last_seen` is now.
2. **Cache miss leaves the entry alone for the TTL fallback.** Same
   shape, stub the cache to return zero / only-expired records,
   assert the entry survives until the 300 s TTL kicks in but goes
   away after that.
3. **`remove_service` still wins instantly.** Demonstrate that the
   `remove` queue path is independent of the cache-refresh tick —
   a remove callback dispatched between snapshots still drops the
   entry on the next tick.

No regression-snapshot change: the panel rendering shape is
unchanged. The bug is in the data path, not in the renderer.

## D5. Surface impact

Touches `src/diting/mdns.py` only. No model changes. No i18n
changes. The TUI consumer (DitingApp's `_consume_mdns_events`) is
unchanged — it still receives `BonjourScanUpdate` snapshots and
writes them into `_latest_mdns`.
