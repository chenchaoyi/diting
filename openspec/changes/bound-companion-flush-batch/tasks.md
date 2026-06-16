## 1. Test plan (test-first)

- [ ] 1.1 Add EN rows to `tests/TESTING.md` under `companion-bridge` for the bounded-batch flush and multi-cycle backlog drain
- [ ] 1.2 Add the matching ZH rows to `docs/zh/TESTING.md` (EN↔ZH parity)

## 2. Implementation

- [ ] 2.1 `relay_client.py`: add `max_batch: int | None = None` to `flush()`; stop the drain loop once `sent >= max_batch` while preserving order, drop-oldest, and `consecutive_failures` accounting
- [ ] 2.2 `runtime.py`: add `DEFAULT_FLUSH_BATCH = 50`; have `flush_loop` call `sink.flush(max_batch=DEFAULT_FLUSH_BATCH)` (keep the `flush()` shutdown-drain call unbounded, or pass the batch — choose so a clean shutdown stays best-effort)

## 3. Tests

- [ ] 3.1 `test_companion_sender.py`: a flush with `max_batch=N` over a larger queue sends exactly N in ascending seq order and leaves the rest queued; hitting the cap resets `consecutive_failures`; no-arg flush still drains all
- [ ] 3.2 `test_companion_runtime.py`: a backlog larger than one batch drains to empty across successive `flush_loop` cycles with no loss/reorder

## 4. Gates

- [ ] 4.1 `uv run pytest`
- [ ] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [ ] 4.3 `openspec validate --specs --strict` and `openspec validate bound-companion-flush-batch --strict`
