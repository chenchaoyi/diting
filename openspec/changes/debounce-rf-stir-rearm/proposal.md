## Why

A real 22-hour capture (`office`, SSID Meituan) shows one chronically-noisy
co-located neighbour AP firing **2453 `rf_stir` events** — 41% of the entire
log — all `confidence: medium` → `salience: notable` → push-worthy. 99.8% carry
`duration_s ≥ 298` (pinned at the 300 s cap) with a 0.6 dB magnitude spread:
this is **one continuous stir episode re-emitted ~every 8.7 s**, not 2453
disturbances. It floods `--notify` banners and the companion phone (and was a
major contributor to the earlier relay backlog).

Root cause is the re-arm guard in `EnvironmentMonitor.fire_events`. It re-arms
when `_current_sigma()` returns `None`, but `None` means "fewer than 3 samples
in the 5 s spike window" — the common case for a neighbour AP sampled at ~7 s
scan cadence. Absence of evidence is treated as evidence the stir ended, so the
AP re-arms almost every tick and re-fires the next time three samples align.
The spec already intends "exactly ONE event for a sustained stir"; the
implementation violates it whenever σ is momentarily uncomputable.

## What Changes

- The re-arm guard SHALL require **positive evidence** that the stir ended: a
  *computable* σ below `DEFAULT_REARM_DB`. An uncomputable σ (too few samples)
  SHALL NOT re-arm — it holds the AP disarmed.
- Re-arming SHALL additionally require the below-floor condition to **persist
  for a debounce window** (`DEFAULT_REARM_DEBOUNCE_S`, new constant) rather than
  a single fluke-low reading, so an ongoing-but-oscillating episode stays one
  event. A genuinely new disturbance after a sustained quiet gap still fires.
- No wire/protocol change, no new user-facing strings, no push-policy change.
  The fix is entirely in the detector's re-arm bookkeeping; the event shape,
  thresholds, cooldown, and salience mapping are untouched.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `environment-monitor`: the cooldown/re-arm requirement gains a debounce — the
  detector re-arms only on observed (computable) sustained σ below the floor;
  insufficient-sample (uncomputable σ) ticks never re-arm.

## Impact

- Code: `src/diting/environment.py` — re-arm branch in `fire_events`, new
  `DEFAULT_REARM_DEBOUNCE_S` constant, per-AP `rearm_below_since` state field.
- Tests: `tests/test_environment.py` (undersampled-neighbour episode fires once;
  debounced re-arm); `tests/TESTING.md` + `docs/zh/TESTING.md` rows.
- No dependency, schema, or companion change.
