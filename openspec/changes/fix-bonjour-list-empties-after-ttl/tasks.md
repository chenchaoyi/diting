## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — append entries under `mdns-scanning` for the cache-refresh liveness path and the bumped 300 s TTL default.
- [x] 1.2 `docs/zh/TESTING.md` — mirror entries in ZH.

## 2. Cache-refresh implementation

- [x] 2.1 `src/diting/mdns.py` — add `_refresh_liveness_from_cache(now)` method that walks `self._state` and bumps `last_seen` to `now` for each entry whose service-instance name still has any non-expired record in `self._zc.cache.entries_with_name(name.lower())`. Guard on `self._zc is None` (called before browser start).
- [x] 2.2 Call `_refresh_liveness_from_cache(now)` in `events()` right before `_expire_stale(now)` on every snapshot tick.
- [x] 2.3 Bump `_BROWSE_TTL_S` default from 60.0 to 300.0 in `BonjourPoller.__init__`. Update the docstring sentence about TTL semantics — it's now a last-resort sweep, not a primary eviction mechanism.

## 3. Tests

- [x] 3.1 `tests/test_mdns.py` — `test_poller_cache_refresh_bumps_last_seen_for_alive_entry`: seed `_state` with an entry whose `last_seen` is 200 s old, monkeypatch `_zc.cache.entries_with_name` to return a single non-expired DNSRecord, drive one snapshot tick, assert the entry survives and `last_seen` is now.
- [x] 3.2 `tests/test_mdns.py` — `test_poller_cache_refresh_skips_when_only_expired_records`: same shape, monkeypatch the cache to return only records with `is_expired(now) == True`; assert `last_seen` is untouched, entry survives until the TTL kicks in.
- [x] 3.3 `tests/test_mdns.py` — `test_poller_cache_refresh_skips_when_no_records`: cache returns an empty iterable; `last_seen` untouched, entry survives until TTL.
- [x] 3.4 `tests/test_mdns.py` — `test_poller_ttl_default_is_five_minutes`: assert `BonjourPoller()._ttl_s == 300.0`.
- [x] 3.5 `tests/test_mdns.py` — refresh the existing `test_poller_ttl_fallback_when_no_remove_observed` to use the new 300 s default (or to construct the poller with an explicit short TTL to keep test runtime fast).

## 4. CI gates

- [x] 4.1 `uv run pytest`
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 4.3 `openspec validate --specs --strict`
- [x] 4.4 `openspec validate fix-bonjour-list-empties-after-ttl --strict`
