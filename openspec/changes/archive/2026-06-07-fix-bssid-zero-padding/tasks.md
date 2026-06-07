# fix-bssid-zero-padding — tasks

## 1. Test plan first

- [x] 1.1 Add normalization + merge-regression rows to `tests/TESTING.md`
- [x] 1.2 Mirror in `docs/zh/TESTING.md`
- [x] 1.3 Failing tests: `normalize_bssid` unit cases (padded passthrough,
      un-padded heal, case fold, fail-soft junk, None) + `_merge_current`
      merges an un-padded Connection BSSID with its padded scan row

## 2. Fix

- [x] 2.1 `normalize_bssid()` in `models.py`
- [x] 2.2 Apply in `_dynamic_store.read_current_identity`
- [x] 2.3 Apply in `macos_backend.get_connection` + `scan`
- [x] 2.4 Apply in `_helper` scan parse
- [x] 2.5 `_merge_current` compares normalized forms

## 3. Verify

- [x] 3.1 `uv run pytest`
- [x] 3.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 3.3 `openspec validate --specs --strict` +
      `openspec validate fix-bssid-zero-padding --strict`
