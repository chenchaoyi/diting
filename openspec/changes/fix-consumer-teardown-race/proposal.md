# Absorb the consumer-worker teardown race

## Why

CI's regression job failed once on a spec-only PR (#171) with
`WorkerFailed: NoMatches("No nodes match '#conn' on Screen(id='_default')")`
out of `_consume_events`. The shape: Textual's test-context shutdown
(`run_test().__aexit__`) unmounts the screen's children while an
event-consumer worker is still draining a queued event; the worker's
`query_one("#conn")` then raises and the whole run dies. A re-run passed —
classic teardown race, costing a full CI round-trip every time it fires.

The fixed panels (`#conn`, `#roam`, `#scan`, …) never unmount in a running
app — view cycling only flips `display`, and the panels are composed once.
So a `NoMatches` inside a consumer worker can only mean teardown, never a
live condition worth crashing on.

## What Changes

A `_consumer_guard` wrapper on the App runs each event-consumer coroutine
and absorbs exactly `NoMatches`, ending the worker quietly; every other
exception still propagates (a typo'd selector or real bug keeps failing
loudly). The five consumer launch sites (`poller`, `ble-poller`, `latency`,
`mdns`, `lan-inventory`) wrap their coroutine in it. No behavior change in
a running app — the guard can only trigger once the panels are gone.

## Impact

- Affected specs: `tui-shell` (new requirement: consumer workers tolerate
  screen teardown).
- Affected code: `src/diting/tui.py` — one helper + five one-line wraps.
- Tests: helper semantics (NoMatches absorbed, other exceptions propagate)
  in `test_tui_smoke.py`.
