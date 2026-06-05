# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `tui-shell` row:
  consumer guard absorbs NoMatches, propagates everything else.

## 2. Guard
- [x] 2.1 `tui.py` — `_consumer_guard` helper; wrap the five consumer
  launch sites.

## 3. Tests
- [x] 3.1 `test_tui_smoke.py` — guard absorbs NoMatches; ValueError
  propagates.

## 4. Gates
- [x] 4.1 `uv run pytest`, snapshot regression,
  `openspec validate --specs --strict`,
  `openspec validate fix-consumer-teardown-race --strict`.
