## Context

`EnvironmentMonitor.fire_events` (`src/diting/environment.py`) guards against a
single stir re-firing every tick with an `armed` flag per AP. After firing,
`armed=False`; the AP re-arms in this branch:

```python
if not state["armed"]:
    current = self._current_sigma(state, now)
    if current is None or current < self._rearm_db:
        state["armed"] = True
    continue
```

`_current_sigma` returns `None` when the 5 s spike window holds `< 3` samples.
A neighbour AP is sampled only at scan cadence (~7 s), so its 5 s window is
frequently under-populated → `current is None` → the AP re-arms → the next tick
that lands 3 samples re-fires. Result in a real 22 h log: 2453 events for one
continuous episode. The cooldown (8 s) doesn't help because re-arm clears it.

## Goals / Non-Goals

**Goals:**
- A sustained stir episode yields ~one event regardless of whether σ is
  continuously computable.
- Re-arm only on observed, sustained quiet — never on missing data or a single
  fluke-low sample.
- Preserve detection of a genuinely new disturbance after a real quiet gap.

**Non-Goals:**
- Changing thresholds, fusion modes, the event schema, salience mapping, or the
  push policy. Those are correct; the bug is purely the re-arm condition.
- Per-AP "chronic source" demotion or rate-limiting (a heavier alternative —
  see Decisions).

## Decisions

**1. Don't re-arm on uncomputable σ.** Treat `current is None` as "no evidence
the stir ended" → stay disarmed, reset the debounce streak. This alone fixes the
dominant cause (the under-sampled neighbour case).

**2. Debounce the re-arm with a sustained below-floor window.** Add
`DEFAULT_REARM_DEBOUNCE_S` (proposed 30.0 s) and a per-AP `rearm_below_since`
timestamp. Re-arm only once σ has been *computable and below* `DEFAULT_REARM_DB`
continuously for the debounce window:
- `current is None` or `current >= rearm_db` → `rearm_below_since = None` (reset), stay disarmed.
- `current < rearm_db` → set `rearm_below_since` if unset; when `now - rearm_below_since >= debounce`, set `armed=True` and clear it.

This also absorbs a single fluke-low σ mid-episode. 30 s is comfortably longer
than the 8 s cooldown and the 5 s spike window, and far shorter than the 300 s
baseline, so a real new disturbance after a genuine lull still fires promptly.

**Alternatives considered.** (a) Chronic-source demotion (downgrade an AP that
fires > N times/window to LOW confidence) — heavier, adds state and a second
tunable, and treats the symptom; rejected in favour of fixing the re-arm logic
that is plainly wrong. (b) Coalescing in the event-log/push layer — would hide
the duplicates but still compute and store them, and wouldn't fix `--notify`;
rejected.

**3. `_APState` already lists fields as a frozen dataclass but the monitor
stores plain dicts** (`setdefault({...})`). The new `rearm_below_since` key is
added to that dict literal and the dataclass docstring, consistent with the
existing `last_event_at` / `armed` keys.

## Risks / Trade-offs

- [A second genuine disturbance < 30 s after the first ends is merged into the
  first episode] → Acceptable: within 30 s of a just-ended stir, re-reporting is
  noise; the cooldown already implied spacing. The debounce is configurable.
- [Connected AP (1 Hz, σ almost always computable) behavior changes slightly] →
  Minimal: for a real spike that ends, σ drops below 1.5 and, held 30 s, re-arms
  — the existing "two disturbances" scenario still holds, just with an explicit
  sustained-quiet requirement instead of a single sample.
- [Regression risk to existing environment tests] → Existing scenarios are
  preserved; the "two separate disturbances" test is updated to hold the quiet
  for the debounce window. New tests cover the undersampled and fluke-low cases.
