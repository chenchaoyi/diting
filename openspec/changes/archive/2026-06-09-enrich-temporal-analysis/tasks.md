# enrich-temporal-analysis — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) for the new aggregations + heuristics + LLM lenses
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Failing tests in `tests/test_analyze.py`: stable-key matches
      familiarity_key; long-span gate boundary; arrival-rhythm; dwell split;
      population resident/passer-by; off-hours (scene); co-peak; LLM lenses
      present; short-log stays lean

## 2. Aggregations (pure)

- [x] 2.1 `_ble_stable_key(row)` mirroring `familiarity.familiarity_key` ladder
- [x] 2.2 `aggregate_ble_dwell` (p50/p90 + transient/lingering/resident)
- [x] 2.3 `aggregate_ble_population` (distinct stable key + hours-present split)
- [x] 2.4 `aggregate_hourly_rhythm` (per-category peak/quiet + top-3 share)
- [x] 2.5 `aggregate_co_peaks` (hours where ≥2 categories peak)
- [x] 2.6 new `Report` fields + broaden the temporal-enable gate to long span

## 3. Heuristics

- [x] 3.1 arrival-rhythm, off-hours (scene), population/dwell, co-peak blocks
      appended to `_run_heuristics` in priority order

## 4. Surfaces

- [x] 4.1 terminal "Temporal & population" render block (gated like cross-session)
- [x] 4.2 `build_llm_prompt` temporal lenses + rhythm in scene paragraph
- [x] 4.3 i18n EN + ZH for every new string

## 5. Verify

- [x] 5.1 `uv run pytest`
- [x] 5.2 re-run the real log (`uv run diting analyze --lang zh <log>`) +
      `--for-llm` bundle — confirm numbers
- [x] 5.3 `tui_snapshot --mode regression`
- [x] 5.4 `openspec validate --specs --strict` + the change
