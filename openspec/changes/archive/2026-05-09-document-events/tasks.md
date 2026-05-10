# Tasks — document events

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/events.py` (`EventRing`, `event_to_jsonl`, `_to_utc_iso`, the five `@dataclass` event types, `NetworkChangeEvent` as control-plane signal).
- [x] 1.2 Cross-checked against `tests/test_event_log.py` and the analyzer's `_extract_event` shape in `src/wifiscope/analyze.py`.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "Events" section gains a one-liner pointing to `openspec/specs/events/spec.md`.
- [x] 2.2 The "five event types" docstring at the top of `events.py` cross-links to the canonical spec.
