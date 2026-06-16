## Context

`RelayClient.flush()` (`src/diting/companion/relay_client.py`) drains the whole
queue in one `while self._queue:` loop, POSTing each envelope synchronously and
stopping only when the queue empties or a POST returns non-2xx. `flush_loop`
(`src/diting/companion/runtime.py`) calls it off the event loop via
`asyncio.to_thread` every `FLUSH_INTERVAL_S` (3 s) whenever `pending` is truthy.

On a healthy link this is fine (POSTs are sub-second). On a slow proxy
(~1.2 s/POST measured on a corporate `workers.dev` transparent proxy) a backlog
of N envelopes makes one `flush()` block its thread for `N × latency` — minutes
for hundreds of events — and a single POST that exceeds the 10 s socket timeout
returns transport-error `0`, breaking the loop with `sent == 0` so the whole
attempt counts as a failure. The result seen live: a frozen backlog under a
sticky `relay unreachable` chip.

## Goals / Non-Goals

**Goals:**
- Bound the work (and thus the blocking time) of a single `flush()` call.
- Let a large backlog drain incrementally and visibly across the existing 3 s
  periodic cycles.
- Keep ordering, the bounded-queue drop-oldest-with-count, and the
  `consecutive_failures` / `relay unreachable` accounting exactly as they are.

**Non-Goals:**
- Changing socket timeouts, retry/backoff strategy, or the relay Worker.
- Diagnosing or working around the corporate DNS/proxy interception (that is an
  environment issue, not a code defect).
- Concurrent / parallel POSTing — the relay is idempotent on `seq` but order is
  a spec guarantee, so delivery stays strictly sequential.

## Decisions

**1. Add `max_batch: int | None = None` to `flush()`.**
`None` preserves today's drain-all semantics (existing callers/tests unchanged).
A positive `max_batch` caps the per-call send count: the `while` loop also stops
once `sent >= max_batch`, leaving the remainder queued in order. Chosen over a
separate `flush_batch()` method to keep one code path and one place where the
failure-counter accounting lives.

**2. `flush_loop` passes a module constant `DEFAULT_FLUSH_BATCH`.**
A constant (proposed 50) keeps the periodic driver simple and the per-cycle
blocking bounded (~`50 × latency`). Because `flush_loop` re-checks `pending` each
3 s cycle, a backlog of 404 drains in ~9 cycles without any extra looping logic.
Alternative considered — looping `flush()` until drained inside one cycle — was
rejected because it reintroduces the unbounded blocking we are removing.

**3. Failure accounting stays keyed on "attempted and sent zero".**
The existing `attempted = bool(self._queue)` / `if sent … elif attempted` logic
is unchanged; a batch that sends ≥1 resets `consecutive_failures`, a batch that
attempts and sends 0 increments it. Hitting the batch cap is a *success* path
(it sent a full batch), so it resets the counter — correct, because a link that
moves a full batch is reachable.

## Risks / Trade-offs

- [A reachable-but-slow backlog now takes several cycles to clear] → Acceptable
  and strictly better than before: it drains monotonically and visibly instead
  of blocking one thread for minutes; the chip count ticks down each cycle.
- [Batch size is a fixed constant, not tuned to measured latency] → 50 is a safe
  default; if it ever needs tuning it is a one-line constant, and `flush()` stays
  parameterized so a caller can override.
- [Behavior change could regress existing flush tests] → Mitigated by keeping the
  no-arg default unbounded; new behavior is covered by new tests asserting the
  batch cap and multi-cycle drain.
