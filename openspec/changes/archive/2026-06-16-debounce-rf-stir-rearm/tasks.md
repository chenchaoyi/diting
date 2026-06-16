## 1. Test plan (test-first)

- [x] 1.1 Add EN row to `tests/TESTING.md` under `environment-monitor` for the debounced re-arm (undersampled neighbour fires once; fluke-low does not re-arm; sustained quiet re-arms)
- [x] 1.2 Add the matching ZH row to `docs/zh/TESTING.md` (EN↔ZH parity)

## 2. Implementation

- [x] 2.1 `environment.py`: add `DEFAULT_REARM_DEBOUNCE_S = 30.0` and a `rearm_debounce_s` ctor param; add `rearm_below_since` to the per-AP state dict + `_APState` docstring
- [x] 2.2 `environment.py`: rewrite the re-arm branch in `fire_events` — never re-arm on `current is None`; re-arm only after a computable σ < `rearm_db` held continuously for the debounce window; reset the streak otherwise

## 3. Tests

- [x] 3.1 `test_environment.py`: undersampled neighbour in a sustained stir (spike window drops <3 samples between fires) fires exactly once, not per-tick
- [x] 3.2 `test_environment.py`: a single fluke-low σ mid-episode does not re-arm; a sustained below-floor period (≥ debounce) does; two genuinely separated disturbances still fire twice
- [x] 3.3 Update any existing re-arm test to hold the quiet for the debounce window

## 4. Gates

- [x] 4.1 `uv run pytest`
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 4.3 `openspec validate --specs --strict` and `openspec validate debounce-rf-stir-rearm --strict`
