# Tasks — document event-log

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/event_log.py` (`EventLogger`, `_iso`, the seven `emit_*` methods, atexit/weakref handling).
- [x] 1.2 Cross-checked against `tests/test_event_log.py` and the analyzer's parse path.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "JSONL log format" section gains a one-liner pointing to `openspec/specs/event-log/spec.md`.
- [x] 2.2 The `_iso` helper is comment-rich already; no additional doc work needed.
