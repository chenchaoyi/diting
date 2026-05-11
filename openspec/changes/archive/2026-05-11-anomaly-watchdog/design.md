## Context

Today's notification surface is two flag-controlled lines in
`src/diting/cli.py`:

```python
notify = "--notify" in args                                # bool
...
async def maybe_notify(payload: dict) -> None:
    if notify and payload.get("confidence") == "high":     # gate
        await _macos_notify(...)
```

And `maybe_notify()` is only called from the two `rf_stir` paths
(connection-update and scan-update consumers in `wifi_consumer()`).
The latency consumer never calls it, even though
`_notify_message()` knows how to format both `latency_spike` and
`loss_burst` payloads.

There's no per-event-type cooldown. `EnvironmentMonitor.fire_events`
has its own cooldown for emission (so `rf_stir` JSONL events don't
chain-fire), but that's spec'd at the σ-detector level and the
notification side-effect rides whatever it produces.

The TUI (`src/diting/tui.py`) ingests the SAME events via its own
event handlers (event_log writer + EventRing append) but doesn't
notify at all. A user with the TUI in a backgrounded terminal
tab gets no signal that anything has fired.

So the gaps are:
1. Two event types that should notify, don't.
2. No silence window on the notification side — only on the
   detector side.
3. No way to loosen the confidence gate for `rf_stir` when a user
   wants every disturbance, not just high-confidence ones.
4. The TUI — where most users live — has no notification path
   at all, forcing a choice between live view and OS banners.

This change adds a thin "watchdog" layer that owns those gaps,
shared by both the headless `monitor --notify` path and the
TUI's new `--notify` flag.

## Goals / Non-Goals

**Goals:**

- A long-running `diting monitor --notify` is usable as an actual
  watchdog for hours without producing a Notification Centre
  rolling banner of duplicates.
- Latency spikes and loss bursts produce notifications they're
  already designed to produce (via `_notify_message()`).
- The TUI gains the same `--notify` semantics. Running
  `diting --notify` in a terminal tab gets you live view AND
  OS banners — no choice between them.
- One module owns the notification logic; both call sites
  (TUI + `monitor`) consume it. Behaviour is consistent across
  both — same silence window, same severity gate, same env vars.
- The user can tune silence window and stir-confidence gate via
  env vars — no recompile, no CLI proliferation.
- Backward compat: zero behaviour change when `--notify` is not
  set on either subcommand. `diting monitor --notify` with no
  env overrides behaves exactly as v0.7.0 for `rf_stir` events;
  new coverage (latency / loss / TUI) is additive opt-in.

**Non-Goals:**

- **No new notification channels.** Slack webhook, file sink,
  email, Pushover — all later. v1 keeps `osascript` only.
- **No new subcommand.** `diting watch` doc-alias is appealing
  but adds a CLI vocabulary entry that needs its own spec
  Requirement. Defer.
- **No config file.** Env vars are enough for v1. If the surface
  grows (per-event-type silence windows, per-target overrides,
  channel routing), a `~/.diting/watchdog.yaml` becomes worth it
  — but not yet.
- **No threshold configurability.** The roadmap line mentions
  "configurable thresholds" but those are intrinsic to the
  detectors (`EnvironmentMonitor` ratio/floor, `detect_latency_spike`
  multiplier). Surfacing them as CLI flags is a separate scope
  with its own Requirement on `environment-monitor` /
  `link-health`. Out of scope here.
- **No per-(event-type) silence override.** v1 has ONE silence
  window. If users complain that 300 s is wrong for one type
  but right for another, we add the per-type knob then.
- **No persistent state.** Silence-window timers are in-memory
  only. Restart resets them.

## Decisions

### New capability `anomaly-watchdog`, separate from `cli`

The CLI capability is about subcommand vocabulary and flag
parsing — what entry points exist and what flags they take.
Notification semantics (which events notify, when, with what
gate, with what silence window, with what env-var configuration)
is a fundamentally different concern that:

- Has its own surface area (silence windows, gates, future
  channels).
- Will grow (multi-channel, per-event-type overrides, config
  file).
- Has its own testable unit (`SilenceClock`).
- Spans multiple entry points (TUI + monitor) — owning it in
  one capability spec keeps both surfaces aligned.

`cli` gets one small ADDED Requirement for the new flag
("`--notify` SHALL be valid on both `monitor` and the default
TUI subcommand"). All the semantic content lives in
`anomaly-watchdog`.

### Two call sites, one module

The two call sites have different event-ingest plumbing:

- **`monitor --notify`** (`src/diting/cli.py:_run_monitor`):
  consumes `WiFiPoller.events()` + `LatencyPoller.events()`
  directly in a pair of asyncio consumers. Today calls
  `maybe_notify()` from inside the consumer.

- **TUI `--notify`** (`src/diting/tui.py:DitingApp`): events
  flow through the App's own event handlers, end up in the
  `EventRing` + EventsPanel + EventLogger. The notification
  call site is naturally where the EventRing append happens
  — same point that already builds the `payload` shape used
  for the JSONL serialisation.

Both call sites do the SAME three things:
1. Build the payload dict (already happening).
2. Pass it to `watchdog.maybe_notify(payload, target, ...)`.
3. The watchdog applies severity gate + silence window + body
   composition + `osascript` invocation.

The shared module exposes one async function:

```python
async def maybe_notify(
    payload: dict,
    *,
    target: str,
    clock: SilenceClock,
    config: WatchdogConfig,
) -> None:
    ...
```

Both call sites construct their own `SilenceClock` and
`WatchdogConfig` at startup (one each, both from env vars). The
clocks are independent between the TUI and `monitor` because
they're different processes — there's no shared-process scenario
to worry about.

### Silence window: per-(event-type, target) tuple

The natural cooldown grain is `(kind, target)`:

- `rf_stir` events name an AP location (`AS11-2_4`); each AP gets
  its own silence clock.
- `latency_spike` / `loss_burst` events name a probe target
  (`gateway:192.168.x.1` or `WAN:1.1.1.1`); each gets its own
  silence clock.

Doing it any coarser (global cooldown) would mean a single gateway
spike silences all stir notifications, which is the wrong
relationship. Any finer (per-event ID) is meaningless — events
don't have stable IDs.

The same `(kind, target)` shape is already used in `cli.py`'s
`should_fire()` helper for the JSONL emission side; the watchdog
keeps a parallel clock for the notification side. They aren't
unified — they have different policies (the JSONL cooldown is for
detector debouncing, the notification cooldown is for user UX).

### Silence window: 60 seconds default

Picking the default:

- **15 s** (too aggressive): a Zoom call with intermittent loss
  produces a banner every 15 s. Spam.
- **60 s**: each `(kind, target)` quiet for a minute. A
  recurring anomaly still produces a banner once a minute —
  enough to act, not enough to drown the user. Notification
  Centre on macOS stacks same-title alerts within a tight
  window so 60 s gives a clean "one banner, then another" cadence.
- **300 s (5 min)** (too slow): a second loss burst 4 minutes
  after the first reads as "still broken" to the user; waiting
  the full 5 min before re-notifying loses signal.
- **900 s (15 min)**: definitely too slow.

60 s as the default. The env var lets the user dial up or down
(clamped 3 ≤ N ≤ 3600 to keep things sane).

### `rf_stir` confidence gate: env-var enum, default `high`

Today's hardcoded `confidence == "high"` is preserved as the
default (preserves v0.7.0 behaviour byte-for-byte). The env var
takes three values:

- `high` (default): notify only on high-confidence stir.
- `medium`: notify on medium OR high.
- `all`: notify on every stir regardless of confidence.

An invalid value (`mid`, `med`, `yes`, etc.) prints a one-line
warning to stderr and falls back to the default. The watchdog
doesn't crash on user typos.

### `_watchdog.py` is small enough to be one module

Not splitting into multiple files. The module contains:

- `SilenceClock` — one `dict[tuple[str, str], float]` + one
  method `should_fire(kind, target, now) -> bool`. Mirrors the
  existing `should_fire()` closure in cli.py but as a class so
  it can hold the configurable window.
- `WatchdogConfig` — small dataclass parsed from env vars.
- `should_notify_stir(payload, confidence_gate) -> bool` —
  the severity-gate logic for stir events.

Total target size: under 80 lines. Tests in a single
`test_watchdog.py`.

### Env-var bounds checking is loud, not silent

Invalid `DITING_NOTIFY_SILENCE_S=foo` prints
`diting: warning: DITING_NOTIFY_SILENCE_S=foo not an integer in
[3, 3600]; using default 300` to stderr and continues. A user who
typo'd will see it on the first `monitor` run. A daemon-style
deployment that has `DITING_NOTIFY_SILENCE_S=300` correctly will
see nothing.

## Risks / Trade-offs

- **Risk**: 60 s default still feels noisy in a flap-prone
  network where every minute produces a banner for the same
  AP.
  → **Mitigation**: env var lets the user dial up (or down).
  Also, the JSONL stream is unfiltered — if you're piping to
  Home Assistant or `tail -f`, every event still arrives.

- **Risk**: notification deluge on first launch when the user
  has many APs each producing a stir during the warm-up window.
  → **Mitigation**: silence window already activates on first
  notification per `(kind, target)`. The N-th AP gets one
  notification, then quiets for 60 s.

- **Trade-off**: env vars for config means daemon-style
  deployments need to remember to set them in their service
  file / launchd plist. A config file would be more discoverable.
  → **Acceptance**: out of scope for v1. Single env-var knob is
  fine until users actually run into the problem.

- **Risk**: someone reads "anomaly watchdog" and expects machine-
  learning anomaly detection (z-score, isolation forest, etc.).
  → **Mitigation**: docs are explicit — this is the rule-based
  detectors that already exist (latency spike + loss burst + RF
  stir), plus a notification layer. Same honesty as the README's
  "NOT Wi-Fi sensing" callout.

## Migration Plan

1. Cut `feature/anomaly-watchdog` (already done).
2. Phase A: OpenSpec scaffolding (proposal/design/specs/tasks). ← we are here
3. Phase B: implement
   - `src/diting/_watchdog.py` (new)
   - Wire into `src/diting/cli.py` (`_run_monitor` + `maybe_notify`)
   - Tests in `tests/test_watchdog.py`
   - TESTING.md (EN + ZH) rows
   - CHANGELOG.md (EN + ZH) `[Unreleased] → ### Added`
4. Self-test all four CI gates.
5. Commit, push, open PR.
6. After merge: `openspec archive anomaly-watchdog` applies the
   new `anomaly-watchdog` capability spec under canonical
   `openspec/specs/`.

Rollback: revert the merge commit. Nothing persistent.

## Open Questions

- **60 s default silence window** — picked over 300 s after
  maintainer feedback ("5 min too slow"). Easy to revisit via
  env var.
- **Single env var vs per-event-type** — if 60 s globally turns
  out to be wrong-direction for one event type (e.g. user wants
  every loss burst notified but is fine with longer cooldown on
  stir), adding `DITING_NOTIFY_SILENCE_RF_STIR_S` /
  `_LATENCY_SPIKE_S` / `_LOSS_BURST_S` is a follow-up change.
  v1 stays simple.
