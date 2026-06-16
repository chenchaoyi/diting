## Why

On a slow / flaky link the companion relay backlog can stall. Observed live on a
corporate network that routes `*.workers.dev` through an internal transparent
proxy (~1.2 s per POST): 404 envelopes sat queued behind a persistent
`relay unreachable` chip. The cause is in the flush path, not the network —
`RelayClient.flush()` drains the **entire** queue in one synchronous burst, so
the flush thread blocks for `queue_len × per-POST latency` (minutes for a large
backlog) and a single slow / timed-out POST mid-burst aborts the whole attempt,
leaving the backlog effectively frozen.

## What Changes

- `RelayClient.flush()` gains an optional `max_batch` parameter that caps how
  many envelopes one call sends; the periodic `flush_loop` passes a default
  batch size so a backlog drains **incrementally** across its 3 s cycles instead
  of one all-or-nothing burst. Per-call blocking time is bounded by the batch,
  not the backlog depth.
- In-order delivery, the bounded-queue drop-oldest-with-count behavior, and the
  `consecutive_failures` / `relay unreachable` semantics (partial success
  resets) are all preserved.
- `flush()` with no argument stays unbounded (drain-all), so existing callers
  and tests keep their behavior.
- No new user-facing strings (no i18n change) and no README surface change.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `companion-bridge`: the relay-client flush requirement gains a bounded-batch
  guarantee — a single flush sends at most a configured batch and a large
  backlog drains across successive periodic flushes while preserving order.

## Impact

- Code: `src/diting/companion/relay_client.py` (`flush` signature + batch loop),
  `src/diting/companion/runtime.py` (`flush_loop` passes the batch size; new
  `DEFAULT_FLUSH_BATCH` constant).
- Tests: `tests/test_companion_sender.py` (bounded-batch flush behavior),
  `tests/test_companion_runtime.py` (backlog drains across cycles);
  `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` (ZH) rows.
- No dependency, protocol, or wire-format change; relay Worker untouched.
