## Why

`diting monitor --notify` exists today (v0.7.0) but is the bare seed
of a real anomaly watchdog. The roadmap (PR #11) put "anomaly
watchdog mode" in the near-term bucket:

> **Anomaly watchdog mode.** Headless long-runs that push macOS
> Notification Centre alerts on high-confidence events (stir,
> loss burst, latency spike). Today's `diting monitor --notify`
> is the seed; it grows configurable thresholds and per-event
> silence windows.

Two gaps in the current state:

1. **Notification coverage**: `cli.py:291 maybe_notify()` only fires
   for `rf_stir` (and only when `confidence == "high"`).
   `latency_spike` and `loss_burst` events have full notification-
   body templates in `_notify_message()` but are NEVER passed to it
   — dead code paths. No silence window either; a sustained stir
   produces a banner every detector tick.

2. **The TUI doesn't notify at all.** A user with `diting` open in
   a terminal tab that's backgrounded behind their email client
   sees nothing when σ spikes or the gateway drops packets — they
   have to switch back to the terminal to know. The watchdog
   functionality is locked behind the headless `monitor --notify`
   path, which means a TUI user has to choose between live view
   AND notifications.

This change closes both gaps so:

- `diting monitor --notify` becomes a real headless watchdog you
  can leave running for hours (or via launchd / systemd) without
  spam, and it covers all three anomaly types.
- The TUI gains the same `--notify` flag, so a user with diting
  in a backgrounded terminal gets banners on critical events.
- Both call sites share one `_watchdog.py` module — the silence-
  window / severity-gate / env-var logic is written once.

## What Changes

- **Notification coverage extended** to all three anomaly event
  types — `rf_stir`, `latency_spike`, `loss_burst`. The
  `_notify_message()` templates for the latter two already exist;
  this PR wires them up.
- **`--notify` flag added to the default TUI subcommand** so a
  user running `diting --notify` in a terminal tab gets OS
  banners when anomalies fire, even while the terminal is
  backgrounded. The existing `diting monitor --notify` keeps
  working for headless / daemon deployments.
- **Per-(event-type, target) silence window** so the watchdog
  doesn't spam during a sustained anomaly. After a notification
  fires for `(rf_stir, AS11-2_4)`, no further `rf_stir`
  notification for `AS11-2_4` until the silence window elapses.
  Each (kind, target) tuple has its own clock. Default window:
  60 seconds. The JSONL event stream is NOT filtered — the
  silence window only gates the OS notification side-effect.
  Same silence logic applies to BOTH call sites (TUI + monitor)
  so behaviour is consistent.
- **`DITING_NOTIFY_SILENCE_S=<int>`** env var to override the
  default silence window (3 ≤ N ≤ 3600). Invalid values fall
  back to the default with a stderr warning.
- **`DITING_NOTIFY_STIR_CONFIDENCE=high|medium|all`** env var to
  loosen the `rf_stir` confidence gate. Default `high` preserves
  v0.7.0 behaviour exactly. `medium` notifies on medium- and
  high-confidence stir. `all` notifies on every stir regardless
  of confidence.
- **Backward compatible**: `diting monitor --notify` with no env
  overrides behaves exactly as before for `rf_stir` events; new
  coverage for `latency_spike` and `loss_burst` is additive.
  Plain `diting` (no flag) doesn't notify — `--notify` is opt-in
  on both subcommands.
- **No new subcommand**: the watchdog functionality is a flag on
  existing entry points, not a third subcommand. A `diting watch`
  doc-alias is intentionally out of scope.
- **No persistent state**: silence-window timers reset on process
  restart. That's a feature, not a bug — restart-after-crash
  legitimately wants one notification per active anomaly class.

## Capabilities

### New Capabilities

- `anomaly-watchdog` — notification-side-effect semantics on top
  of the event stream. Owns: which event types notify, severity
  gates, silence windows, env-var configuration, notification
  body composition, the contract that both TUI and `monitor`
  call sites share. Lives separately from `events` (the event
  vocabulary itself) and `event-log` (the JSONL serialisation).
  Future expansions (richer channels, config file, persistent
  state) land here without touching the JSONL-stream, TUI, or
  environment-monitor surfaces.

### Modified Capabilities

- `cli` — adds one ADDED Requirement for `--notify` on the
  default TUI subcommand. The flag already exists on
  `monitor`; making it valid on the default subcommand is a
  flag-vocabulary change that belongs in the `cli` spec
  alongside `--lang` / `--log` / `--config`.

## Impact

- **Files**:
  - `src/diting/_watchdog.py` (new — silence bookkeeping +
    env-var parsing + severity gate). One module, both call
    sites consume it.
  - `src/diting/cli.py` (rewire `maybe_notify` and the
    latency-consumer call sites for `monitor --notify`; parse
    `--notify` flag for the default subcommand and pass it
    through to the TUI app).
  - `src/diting/tui.py` (the App accepts a `notify: bool`
    constructor argument; when set, instantiates a
    `WatchdogConfig` + `SilenceClock` and calls into them at
    the same event-ingest points where the EventRing gets the
    new event).
  - `tests/test_watchdog.py` (new — unit tests for
    `SilenceClock`, `WatchdogConfig`, `should_notify_stir`).
  - `tests/test_tui_smoke.py` (extend with one test that
    `DitingApp(notify=True)` constructs cleanly and the
    notification hook is called when an event flows through;
    `osascript` is patched).
  - `tests/TESTING.md` + `docs/zh/TESTING.md` (new capability
    rows for `anomaly-watchdog`; modified row for `cli`'s
    `--notify` flag).
  - `CHANGELOG.md` + `docs/zh/CHANGELOG.md`
    (`[Unreleased] → ### Added`).
- **Tests**: unit coverage of `_watchdog` module + one TUI
  smoke test for the wire-up. No live `osascript` execution
  (mocked / patched). Snapshot regression unaffected.
- **CI gates**: all four expected to pass.
- **External**: no version bump (will accumulate under
  `[Unreleased]` until the maintainer cuts v0.8.1 / v0.9.0).
