# Design

## D1. Why v1.1.2's cache-refresh isn't enough

zeroconf's DNS cache holds each record for the TTL the announce specified — typically 4500 s for AirPlay, but only 120 s for many HomePods, ~60 s for some printers and IoT bridges, and similarly short for the local loopback announce. Once the cache TTL expires, `Zeroconf.cache.entries_with_name(...)` returns the same records with `is_expired(now) == True`, and our refresh path doesn't bump `last_seen`. After our 300 s backstop the entry falls off.

The hole is closed by **actively re-querying** each tracked service on a periodic tick. The query is an mDNS `QM` request for the service-instance name; live devices respond with fresh SRV / TXT records, which:

1. Land back in zeroconf's cache (refreshing it),
2. Get observed by our `AsyncServiceInfo.async_request` await result,
3. Let `_apply_callback("update", ...)` write fresh data into `_state[key]` and bump `last_seen`.

If no device responds within the timeout, the probe is a no-op — `_state` isn't mutated, the TTL backstop eventually evicts the entry naturally. No false positives.

## D2. Probe cadence + fire-and-forget discipline

**Cadence:** every 30 s per entry. Lower would be polite to the network; higher risks falling close to the device-side TTL window. 30 s is well within typical TTLs (60 s+) while still being polite — a network with 50 tracked services issues ~1.7 queries / s averaged, which is below the multicast rate-limit threshold.

**Fire-and-forget:** the probes are scheduled via `self._loop.create_task(self._apply_callback("update", type, name))`. The snapshot loop does NOT await them — a slow / unresponsive device must not block the next yield. The 1500 ms timeout inside `AsyncServiceInfo.async_request` caps each individual probe's worst-case runtime; tasks complete or error out independently.

**Re-using `_apply_callback`:** the existing "update" code path already issues `AsyncServiceInfo(type, name).async_request(self._zc, 1500)` and merges results into `_state`. The active-probe scheduler just enqueues "update" ops without going through the `_Listener` queue. Avoids any new code path.

## D3. State of the world after this fix

Three layers, each with a clear role:

| Layer | Cadence | What it does |
|---|---|---|
| zeroconf's `ServiceBrowser` + listener callbacks | event-driven | `add` / `update` / `remove` callbacks when zeroconf observes records changing |
| Cache-refresh path (v1.1.2) | 2 s (every snapshot tick) | Bumps `last_seen` when zeroconf still has non-expired records — handles the case where some other zeroconf path (e.g. its own periodic re-queries) already refreshed |
| Active-probe path (this change) | 30 s per entry | Sends explicit query to each tracked device; refreshes zeroconf's cache; `_apply_callback("update", ...)` updates state |
| TTL backstop (v1.1.2) | last-resort | 300 s sweep for entries that get neither callback, cache hit, nor probe response |

The active-probe layer is the new primary keep-alive; the cache-refresh layer becomes a cheap fast path; the TTL is now genuinely a backstop.

## D4. Tx Rate > Max heuristic

`MacOSWiFiBackend` already exposes `tx_rate_mbps` and `max_link_speed_mbps` (the latter via the private `maximumLinkSpeed` selector — see `_safe_call(iface, "maximumLinkSpeed")`). When CoreWLAN returns `Max < Tx`, the row reads as nonsense.

Fix lives in the connection-panel renderer (`tui.py::ConnectionPanel._paint`), not in the backend — the backend has no opinion about what's "right", it just passes values through. The renderer's check is:

```python
max_str = _fmt(conn.max_link_speed_mbps, " Mbps")
if (
    conn.tx_rate_mbps is not None
    and conn.max_link_speed_mbps is not None
    and conn.tx_rate_mbps > conn.max_link_speed_mbps
):
    # CoreWLAN's maximumLinkSpeed is stale / under-reported.
    # Surface the Tx half alone to avoid the contradiction.
    row_value = _fmt(conn.tx_rate_mbps, " Mbps")
else:
    row_value = t("{tx}  /  {max}", tx=..., max=max_str)
```

The footnote about "Tx and Max may diverge from different CoreWLAN APIs" stays — when divergence is plausible (Max ≥ Tx but the Max is conservative for some other reason) the row keeps both numbers; we only hide Max when it's literally wrong.

## D5. Test surface

`tests/test_mdns.py`:
- `test_poller_active_probe_scheduled_per_state_entry_every_30s` — drive the events loop for >30 s, assert `_apply_callback` gets called for each tracked entry at least twice (initial seed + one probe tick).
- `test_poller_active_probe_does_not_block_snapshot_yield` — make the AsyncServiceInfo mock hang; the snapshot loop SHALL still yield within `snapshot_interval_s + 100 ms`.
- `test_poller_active_probe_keeps_state_alive_through_cache_expiry` — combine: the cache returns expired records, the active probe still succeeds, `last_seen` gets bumped on the next tick.

`tests/test_tui_helpers.py`:
- `test_connection_panel_hides_max_when_tx_exceeds_it` — assert the rendered text contains `Tx 286 Mbps` without `/ 229 Mbps`.
- `test_connection_panel_shows_both_when_max_ge_tx` — sanity-check the legacy path stays intact when Max ≥ Tx.

## D6. Surface impact

- `mdns.py`: new `_kick_active_probes()` method + scheduling in `events()`. No new public API.
- `tui.py`: `ConnectionPanel._paint` gets a 5-line branch. No new dependency.
- No i18n keys added or changed.
- README + ZH README unchanged.
