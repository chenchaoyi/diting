# fix-familiarity-tz-mismatch — tasks

## 1. Test plan first (test-first discipline)

- [x] 1.1 Update `tests/TESTING.md` with the mixed-tz familiarity cases
- [x] 1.2 Mirror the same rows in `docs/zh/TESTING.md`
- [x] 1.3 Write failing regression tests in `tests/test_familiarity.py`:
      mixed naive/aware observe → flush survives; naive persisted
      record loads/classifies/prunes; flush guard in the TUI path

## 2. Store fix

- [x] 2.1 Add `_aware()` normalization helper in `familiarity.py`
- [x] 2.2 Normalize incoming `now` in `observe_seen`
- [x] 2.3 Normalize read-back timestamps in `_parse`

## 3. TUI guard

- [x] 3.1 Wrap the periodic `_familiarity_flush` body in the same
      fail-soft try/except as the `on_unmount` flush

## 4. Verify

- [x] 4.1 `uv run pytest`
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 4.3 `openspec validate --specs --strict` and
      `openspec validate fix-familiarity-tz-mismatch --strict`
