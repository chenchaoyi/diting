# agent-friendly-cli — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) for the guard, arg fix, --json shapes, errors-as-json, exit codes, per-subcommand help
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Failing tests in `tests/test_cli.py` (+ `test_analyze.py` for serializer)

## 2. P0 — never traceback + arg fix

- [x] 2.1 Top-level guard in `main()` (SystemExit re-raise, KeyboardInterrupt
      clean, else `diting: <msg>` + exit 1; `DITING_DEBUG=1` re-raises)
- [x] 2.2 `--for-llm` → boolean + `-o`/`--out-dir`; keep `--for-llm=DIR`;
      out-dir-is-a-file → usage error

## 3. P1 — --json

- [x] 3.1 `analyze.report_to_dict(report)` + `models.connection_to_dict(conn)`
- [x] 3.2 `--json` branch in `_run_once` (one doc) and `_run_analyze` (one doc)
- [x] 3.3 `--json` line-stream in `_run_watch` (one object per event); chrome → stderr
- [x] 3.4 `_fail(msg, code, *, as_json)` helper; guard honors json mode

## 4. P2 — help + exit codes

- [x] 4.1 Per-subcommand `--help` with EXAMPLES + automation note (EN + ZH)
- [x] 4.2 Top-level help states the exit-code convention; audit runners to match

## 5. Verify

- [x] 5.1 `uv run pytest`
- [x] 5.2 reproduce the reported command (no crash) + `diting once/analyze --json | jq`
- [x] 5.3 `tui_snapshot --mode regression`
- [x] 5.4 `openspec validate --specs --strict` + the change
