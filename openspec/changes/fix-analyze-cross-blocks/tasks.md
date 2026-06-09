# fix-analyze-cross-blocks — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) — cross-block localization + stable-key contributors
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Update `test_top_contributors_ranks_ble_identifiers_by_seen_count`
      to the stable-key behaviour; add a zh-localization test

## 2. Fix

- [x] 2.1 `aggregate_top_contributors` BLE → `_ble_stable_key` (skip unkeyable)
- [x] 2.2 wrap `events` / `total` literals in `t()`; header "BLE device"
- [x] 2.3 i18n ZH for all cross-block headers + weekday names + events/total
- [x] 2.4 clarify the top-level usage line: `--for-llm [-o DIR]`

## 3. Verify

- [x] 3.1 `uv run pytest`
- [x] 3.2 re-run the real log `--lang zh` — cross-blocks Chinese, contributors meaningful
- [x] 3.3 `tui_snapshot --mode regression`
- [x] 3.4 `openspec validate --specs --strict` + the change
