# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `events` row:
  ring default 1000, overflow drops oldest, custom capacity honored.

## 2. Ring
- [x] 2.1 `events.py` — `EventRing` default capacity 100 → 1000 +
  docstring.

## 3. Docs
- [x] 3.1 `README.md` + `docs/zh/README.md` — three "last 100" mentions
  each → 1000.

## 4. Tests
- [x] 4.1 `test_events.py` — default-capacity overflow (1001st drops
  oldest); custom `capacity=5` honored.

## 5. Gates
- [x] 5.1 `uv run pytest`, snapshot regression,
  `openspec validate --specs --strict`,
  `openspec validate expand-event-ring --strict`.
