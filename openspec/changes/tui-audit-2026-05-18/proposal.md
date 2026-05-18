## Why

A 2026-05-18 self-driven `/tui-audit` against the v1.1.2 build surfaced two issues that user reports already corroborate.

1. **Bonjour list still ages out**, even after v1.1.2's cache-refresh path. User confirmation: ~5-10 min on the home network, and on Meituan's corporate Wi-Fi the local Mac's own loopback entry got evicted within minutes too. Root cause is that zeroconf's DNS cache holds records only for the announce-published TTL — many Bonjour devices use 60-120 s TTLs, shorter than our 300 s last-resort backstop. The passive cache-refresh path then runs out of non-expired records to bump `last_seen` from, and the entries fall off our window. The fix is to actively re-query each tracked service via `AsyncServiceInfo.async_request` on a periodic tick; a live device responds, the record lands back in zeroconf's cache, and our state stays alive indefinitely.

2. **Connection panel shows `Tx 286 Mbps / Max 229 Mbps`** — current Tx Rate higher than the negotiated maximum link speed. CoreWLAN's `maximumLinkSpeed()` returns a stale or under-reported value on macOS 26 (a known flakiness; not something we can fix at the source). The footnote ("Tx and Max use different CoreWLAN APIs and may diverge") is honest but the resulting display is nonsense — the radio cannot transmit faster than its negotiated max. Fix: when `transmitRate > maximumLinkSpeed`, the Max field is treated as unreliable and omitted; the row reads `Tx 286 Mbps` instead of the contradiction.

## What Changes

### `mdns-scanning` — active per-service re-probe
- **MODIFIED:** the `BonjourPoller` SHALL periodically re-query every tracked service via `AsyncServiceInfo.async_request` so that devices whose announce-record TTL is shorter than `_BROWSE_TTL_S` don't age out. Probe cadence SHALL be ≥ every 30 s and SHALL be fire-and-forget (one `asyncio.create_task` per entry per tick, with no awaiting from the snapshot loop — a slow non-responding probe MUST NOT delay the next snapshot yield). The active path SHALL coexist with the v1.1.2 cache-refresh path (still runs every snapshot tick) and the TTL backstop (still the last-resort sweep).

### `wifi-scanning` — Connection panel renders Tx Rate honestly when Max is stale
- **MODIFIED:** the connection-panel renderer SHALL detect the CoreWLAN inconsistency where `transmit_rate_mbps > max_link_speed_mbps` (Max field is stale / under-reported on macOS 26) and omit the Max half of the row in that case. The result reads `Tx <rate> Mbps` instead of the contradictory `Tx <rate> Mbps  /  <smaller> Mbps`. When Max is unknown or omitted, the row continues to render Tx alone — this is the existing behaviour and is unchanged.

## Out of Scope

- A general retry / reconnect path for the zeroconf instance itself (sleep / wake, network change). The active-probe path handles the common "record TTL too short" scenario; the rarer "zeroconf is dead" path is a separate fix.
- Patching CoreWLAN's `maximumLinkSpeed` — we don't control the API; the renderer just handles its known wrong-output case.
- Surfacing a hint to the user when the device count is suspiciously low (e.g. corporate AP filters mDNS multicast). That's a separate product question.
