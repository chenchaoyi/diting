# capture-sampling

## Why

`capture-context` made the `associated` link_state carry quality, but that's a
single snapshot at association — a 13 h static session still has one quality
reading and no sense of how it varied. And the log records roams but never the
*neighborhood*: how many other BSSIDs are around, how many share the current
channel. Both are exactly the context an AI needs to reason about a quiet
session ("RSSI held steady at −50 over 13 h" / "9 co-channel neighbors → likely
contention even with no roam").

## What Changes

- **Periodic `link_sample` events.** While associated, the capture loop emits a
  `link_sample` at a fixed cadence (default 60 s) carrying the nested `quality`
  object — yielding an RSSI / SNR / tx-rate distribution over the session, not
  just the join snapshot.
- **`scan_summary` events.** On each scan pass (throttled to the same cadence),
  a `scan_summary` records the neighbor count and the co-channel count relative
  to the current connection's channel — interference context the roam events
  can't convey.
- Both are **local-only event types**: emitted via a sink-only path that
  bypasses the companion observer, so they never reach the versioned wire and
  the protocol is untouched.

## Capabilities

### Modified Capabilities

- `event-log`: the writer SHALL emit periodic `link_sample` events (quality over
  time, while associated) and `scan_summary` events (neighbor + co-channel
  count), both local-only.

## Out of scope

- analyze consuming these into report sections (`analyze-observability`).
- Pushing either type to the companion (deliberately local-only).

## Impact

- `src/diting/event_log.py` — `_emit_local` (sink-only); throttled
  `emit_link_sample` / `emit_scan_summary` with internal cadence state.
- `src/diting/cli.py` (`_run_monitor`) + `src/diting/tui.py` — call the new
  emitters from the Connection / Scan consumers; track the current channel for
  the co-channel count.
- `tests/test_event_log.py` + `tests/TESTING.md` (EN + ZH).
