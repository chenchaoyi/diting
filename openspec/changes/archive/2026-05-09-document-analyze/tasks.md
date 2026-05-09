# Tasks — document analyze

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/analyze.py` (`parse_jsonl`, `analyze`, `_run_heuristics`, `Insight` dataclass, `_format_duration`, `_scaled_loss_pct`).
- [x] 1.2 Cross-checked heuristic catalogue against `tests/test_analyze.py`.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "Analyze your session" section gains a one-liner pointing to `openspec/specs/analyze/spec.md`.
- [x] 2.2 The exit-hint Python prints after a TUI session (`tip: summarise this session with wifiscope analyze {path}`) cross-links to the spec.
