# Live insight events — synthesized "valuable change" + live-ified analyzer

## Why

Phases 1–2a gave each raw transition a `familiarity` class and a `salience`
tier, and gated the push so routine noise stops flooding. But diting still only
emits *raw* transitions. The "what actually mattered" intelligence —
"three unfamiliar devices appeared together", "the link keeps dropping",
"loss on the gateway" — exists only retrospectively in `analyze.py`
(offline, whole-log). Nothing surfaces it live.

This is Phase 2b + 2c of the event-design deepening: a live **insight engine**
that watches the enriched event stream and emits synthesized `insight` events
when a *valuable change* is detected — both new familiarity-aware patterns (2b)
and the live-able subset of the offline `analyze.py` heuristics (2c).

## What Changes

- **A new `insight` event type** (`InsightEvent` in `events.py`): carries a
  stable English `code` (which insight fired), a `severity`
  (`info`/`note`/`warn`), and a structured `detail` dict. The human one-liner is
  generated from `code` + `detail` at display/notify time (locale-stable JSONL,
  user-facing text localised via `t()`), mirroring the analyzer's `Insight`
  shape. Salience maps from severity (`warn`→`high`, `note`→`notable`,
  `info`→`low`).

- **A live insight engine** (new `src/diting/insights.py`): hermetic + stateless
  w.r.t. the real environment — it `observe`s the same enriched wire payloads
  the logger emits (familiarity + salience already stamped) into bounded rolling
  windows, and `collect(now)` evaluates the detectors (per-code cooldown so a
  sustained condition fires once per window, not per tick). Detectors:
  - **2b — synthesized:** `new_device_cluster` — N `first_time` arrivals within
    a short window ("an unfamiliar group appeared / you entered a new place").
  - **2c — live-ified `analyze.py` heuristics** on a rolling window:
    `repeated_disassociates`, `loss_observed`, `latency_without_loss`,
    `band_steering`. (Offline-only / low-value-live heuristics — timezone
    mismatch, short-window, stale-latency-after-roam — stay in `analyze.py`.)

- **Live surfacing ("push-insights")**: fired insights flow through the normal
  path — JSONL log + the TUI Events ring/modal (a new `[INSIGHT]` row) — and,
  for `note`/`warn` severity, a macOS notification via the existing watchdog
  notifier (the desktop "push"). Insights are **desktop-local** this phase: they
  are not in the companion push set, so they never cross the wire (forwarding
  insights to the phone is a later paired `companion-protocol` change).

## Impact

- Affected specs: a NEW `insights` capability (engine + event contract),
  `events` (the `insight` type), `anomaly-watchdog` (insight notifications).
- Affected code: new `src/diting/insights.py`; `events.py` (`InsightEvent`),
  `event_log.py` (`emit_insight` + multi-observer support so the engine taps
  alongside the companion sink), `salience.py` (insight severity → tier),
  `_watchdog.py` (insight notify gate + message), `tui.py` (construct the engine,
  register the observer, periodic `collect` → ring + emit + panel + notify, and
  the modal/panel render branch).
- **Scope limit (honest):** the detector set is the high-value live-able subset,
  not every `analyze.py` rule; the offline analyzer is unchanged (not deleted or
  rewritten). Insights do not cross the companion wire yet. No threat detections
  (evil-twin / deauth-storm / follows-you) — those are Phase 3.
- No name-based input: detectors read only authoritative payload fields
  (`familiarity` — itself authoritatively keyed — `type`, `state`, `kind`,
  counts), never a Bonjour name or hostname.
