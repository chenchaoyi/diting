## Context

The mDNS surface in diting is lazy by design: `diting.mdns` is
imported only when the user activates the view, so users who never
press `n` past Wi-Fi pay nothing for `zeroconf`. The current
trigger is exactly when the user enters the mDNS view (second `n`
press in the wifi → ble → mdns cycle).

That choice optimises for users who never reach mDNS. For users
who do, the cost is concentrated on the single keystroke that
should immediately reveal the mDNS panel:

| Stage | Cost | Today |
|---|---|---|
| First `from .mdns import BonjourPoller` (transitively imports `zeroconf`) | ~200 – 500 ms | on the asyncio event loop |
| `Zeroconf(InterfaceChoice.Default)` (multicast socket setup) | ~100 – 500 ms | on the asyncio event loop |
| `ServiceBrowser(...)` | <50 ms (browser already runs on its own threads) | on the asyncio event loop |

Both heavy stages run inline on the event loop, so the BLE view
stays frozen and `n` taps queue up until the work clears. The
user-facing symptom is a 300 ms – 1 s dead pause on the second `n`.

## Goals / Non-Goals

**Goals:**
- Hide the Bonjour startup cost behind a step the user is *not*
  trying to act on — the BLE view, which is already populated by
  its own poller.
- Keep the event loop responsive throughout startup so the BLE
  view paints immediately and subsequent `n` taps register.
- Make the consumer task restartable: an unexpected error in the
  Bonjour stream should not leave the view permanently dead.

**Non-Goals:**
- Eager-loading `zeroconf` at TUI start. Users who never leave
  Wi-Fi still pay nothing.
- Caching state across processes. The poller stops on TUI exit
  and re-warms next run.
- Changing the BonjourPoller polling cadence or the curated
  service-type list.

## Decisions

### D1 — Trigger pre-warm on wifi → BLE, not on mDNS entry.

Two alternatives:

| Option | Where the cost lands | Why not chosen |
|---|---|---|
| A. Status quo (warm on first mDNS entry) | The `n` press the user wants to act on | This is the symptom we are fixing. |
| B. Eager warm at app start | App startup | Slows down `diting` start for every user, including those who never leave Wi-Fi. Burns CPU on a path that may never matter. |
| **C (chosen). Warm on first non-Wi-Fi view** | First `n` press; user is reading BLE, not racing to mDNS | The cost is hidden behind real reading time. The "user never leaves Wi-Fi" optimisation is preserved. |

The trade-off vs A: users who land on BLE and quit before ever
pressing `n` again pay the warm-up cost for nothing. We accept
this — BLE-only sessions are rare, and the cost runs on a worker
thread anyway (the event loop and the BLE view do not block).

### D2 — Run the heavy stages off the asyncio event loop via `asyncio.to_thread`.

`BonjourPoller()` itself is cheap; the two slow stages are the
import and the `Zeroconf()` constructor. Both are synchronous and
both spend most of their wall-clock time on I/O (file reads during
import, socket setup for multicast join). `asyncio.to_thread`
wraps them in a thread pool task so the asyncio loop continues
running.

Alternative: rewrite `BonjourPoller._start_browser` to be properly
async-native using `zeroconf.asyncio`'s `AsyncZeroconf`. Rejected
because (a) the synchronous `Zeroconf()` is what the rest of the
poller is built around, (b) `AsyncZeroconf.__aenter__` still does
the same blocking socket work internally, and (c) the thread-hop
solution is two `await asyncio.to_thread(...)` lines.

### D3 — Module-level `_import_bonjour_poller` helper, not a bound method.

Passing `self._import` to `asyncio.to_thread` would bind `self`
across the thread boundary. The import path should not touch any
App state — keeping it module-level makes that visible and
unambiguous.

### D4 — Single consumer worker covers prewarm + drain.

The consumer task already runs in the background; folding the
prewarm into the same coroutine avoids a separate worker and the
state-machine question of "what if the user presses `n` again
while the prewarm is mid-flight." A boolean `_mdns_starting`
guards `_ensure_mdns_poller` against firing twice in the gap
between the worker starting and `self._mdns_poller` being assigned.

### D5 — Exception path clears `_mdns_poller`.

Today the consumer task `pass`-es on unexpected errors, leaving
`self._mdns_poller` set to a stopped object. `_ensure_mdns_poller`
sees a non-None poller and refuses to rebuild, so the mDNS view
stays dead until the user restarts. New behaviour: on an exception
the consumer task calls `poller.stop()` and resets
`self._mdns_poller = None` so the next `n` press re-creates it.

## Risks / Trade-offs

- **[Risk]** Users who enter BLE and quit pay the Bonjour warm-up
  cost for nothing. → Acceptable: cost runs in a thread, no UI
  impact; rare in practice.
- **[Risk]** The first BLE view paint races with the import
  finishing on the worker thread, so a *very* quick second `n` tap
  (sub-200 ms) could still arrive before `_mdns_poller` exists.
  → The existing "wait for `_mdns_poller`" gate inside `events()`
  is not a UI block — the user sees an empty Bonjour panel
  refreshed once data arrives. Same end state, milder symptom.
- **[Risk]** Spec relaxes "user who only uses Wi-Fi and BLE never
  imports `zeroconf`." → Documented as a deliberate BREAKING note
  in the proposal.

## Migration Plan

No data, no on-disk state, no API surface. Code change ships in a
single PR. Rollback is `git revert`.
