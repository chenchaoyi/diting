# Design — live insight engine

## Event shape

```python
@dataclass(frozen=True, slots=True)
class InsightEvent:
    timestamp: datetime
    code: str                      # stable English id (new_device_cluster, …)
    severity: str                  # info | note | warn
    detail: dict[str, Any] | None  # structured supporting data
```

JSONL: `{"type":"insight","code":…,"severity":…, …detail keys flattened…}`.
The `code` is locale-stable (the analysis key); the human one-liner is produced
by `format_insight_summary(code, detail)` via `t()` at render / notify time, so
no localised text lands in the log. Salience: `warn`→`high`, `note`→`notable`,
`info`→`low` (added to the `salience` scorer's `insight` branch).

## Why an engine fed by the logger observer

`EventLogger._emit` is the one choke point, and by the time a payload reaches it
the `familiarity` and `salience` fields are already stamped. The engine registers
as a logger **observer** (the same tap the companion sink uses) so it sees those
enriched payloads directly — the cluster detector can read
`familiarity == "first_time"` with no extra plumbing, and no consumer call-site
needs to change.

The logger gains multi-observer support: `add_observer` / `remove_observer`
(the engine), while `set_observer` keeps managing its single back-compat slot
(the companion sink) so neither clobbers the other.

`observe(payload)` only updates bounded rolling windows (it ignores
`type == "insight"`, so the engine never feeds on its own output). It does NOT
emit — emitting from inside `_emit` would re-enter the logger. Instead a TUI
timer calls `collect(now)`, which evaluates the detectors and returns the fired
`InsightEvent`s; the TUI then rings + `emit_insight`s + notifies them through the
normal path. A ~20 s collect cadence is fine — an insight is a summary, not a
keystroke.

Single-threaded safety: both `observe` (from async consumers) and `collect`
(from the Textual timer) run on the one event loop, so the engine needs no locks.

## Detectors (per-code cooldown)

Each detector shares a cooldown (default 300 s) keyed by `code` (+ target where
relevant) so a sustained condition produces one insight per window, not one per
tick — the same principle as the watchdog `SilenceClock`.

- **`new_device_cluster`** (2b): a sliding `cluster_window_s` (120 s) of
  `first_time` arrival timestamps across BLE/LAN/Bonjour. Fires `note` when the
  count reaches `cluster_min` (3). detail `{count, window_s}`.
- **`repeated_disassociates`** (2c): `link_state` disassociated count in the
  rolling `window_s` (600 s); fires `warn` at ≥ 3. detail `{count}`.
- **`loss_observed`** (2c): a `loss_burst` in the window fires `warn` with the
  peak loss. detail `{peak_loss_pct}`.
- **`latency_without_loss`** (2c): a `latency_spike` in the window with no
  `loss_burst` → `note` (jitter, not link failure). detail `{spikes}`.
- **`band_steering`** (2c): ≥ 5 roams in the window with > 70 % `band_switch`
  → `info`. detail `{roams, band_switches}`.

Offline-only / low-value-live heuristics (timezone mismatch, short-window,
stale-latency-after-roam, sustained-RF, inter-AP-roam) stay in `analyze.py` and
are explicitly NOT live-ified here — `log()`-ged as a deferred set in tasks.

## Surfacing

- **JSONL**: `emit_insight` writes the event (analyze.py can later read them).
- **TUI**: the collect handler `ring.push`es each insight + `append_event`s a
  `[INSIGHT]` row (new branch in `_event_format_line` → `_format_insight_event`,
  rendered from `format_insight_summary`). The Events modal shows it under the
  `all` filter (no new filter key this phase).
- **macOS notify ("push")**: `note`/`warn` insights fire a banner via the
  watchdog notifier (`maybe_notify` gains an `insight` branch, gated on severity,
  silence-clock keyed by `code`). `info` insights stay log+TUI only.
- **Companion wire**: insights are NOT added to `DEFAULT_PUSH_TYPES`, so the sink
  never forwards them. No `companion-protocol` change; fixtures untouched.

## Alternatives considered

- **Emit insights from inside `_emit`/the engine directly.** Rejected:
  re-entrancy into the logger; the drain-on-timer pattern (mirroring the
  pollers' `drain_transitions`) is cleaner and keeps the engine pure/testable.
- **Feed the engine from the 7 TUI consumer sites.** Rejected: the enriched
  payload (familiarity/salience) only exists post-`_emit`; the observer tap is
  the single place it exists, and avoids touching every consumer.
- **A generic detector registry.** Deferred: each detector has bespoke window
  state; explicit methods sharing one cooldown helper are simpler to get right
  for five detectors. Revisit if the set grows large.
