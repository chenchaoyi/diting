# agent-friendly-cli

## Why

diting should be usable by coding agents (Claude Code et al.) as a dependable
signal-collection tool, not just a human TUI. Today the CLI is prose-first and
brittle:

- `diting analyze --lang zh --for-llm <log.jsonl>` crashes with a raw
  `FileExistsError` traceback (frozen binary: `[PYI-…] Failed to execute
  script`). `--for-llm` is an optional-value flag that greedily eats the next
  arg as its out-dir, so the input log becomes the out-dir and `mkdir(<log>)`
  fails. Worse, `main()` has **no top-level error handling** — any uncaught
  exception surfaces as a stack trace, which an agent should never see.
- `once` / `analyze` / `watch` print human prose only — an agent must scrape
  text instead of parsing structured output.
- Usage is one terse `--help` with no per-subcommand help, examples, or
  documented exit codes.

## What Changes

- **Never traceback.** `main()` wraps dispatch: `SystemExit` re-raises
  (intentional exit codes), `KeyboardInterrupt` exits cleanly, any other
  exception prints a single `diting: <message>` to stderr and exits 1.
  `DITING_DEBUG=1` shows the full traceback for developers.
- **De-footgun `--for-llm`.** It becomes a pure boolean; the bundle directory
  moves to `-o` / `--out-dir DIR` (with `--for-llm=DIR` kept for back-compat).
  A bare `--for-llm <input>` no longer swallows the log; an out-dir that exists
  as a file is a clean usage error, not a crash.
- **`--json` machine-readable output** on `once`, `analyze`, and `watch`:
  `once` / `analyze` emit one JSON document; `watch --json` emits a
  newline-delimited line-stream (one object per change event). In `--json`
  mode JSON is the only thing on stdout (chrome → stderr) and errors are JSON
  too (`{"error": …, "code": N}`).
- **Discoverability + a stable contract.** Restructured top-level help and a
  short per-subcommand `--help` with EXAMPLES and an automation note; a
  documented, consistent exit-code convention (0 ok · 1 runtime · 2 usage).

## Capabilities

### Modified Capabilities

- `cli`: new requirements for the top-level no-traceback guard, `--json`
  structured output (once / analyze / watch) with errors-as-JSON, the
  `--for-llm` / `--out-dir` arg fix, per-subcommand help, and documented exit
  codes.

## Out of scope

- A `diting capabilities --json` self-describing manifest (future).
- A full argparse rewrite — the specific footguns are fixed in the existing
  hand-rolled parser; a rewrite is deferred.
- Changing the `monitor` JSONL stream (already machine-readable) or the TUI.

## Impact

- `src/diting/cli.py` — `main()` guard; `--for-llm`/`-o` parsing; `--json`
  branches in `_run_once` / `_run_analyze` / `_run_watch`; `_usage()` +
  per-subcommand help; exit-code audit.
- `src/diting/analyze.py` — `report_to_dict(report)` serializer.
- `src/diting/models.py` — `connection_to_dict` helper.
- `src/diting/i18n.py` — EN + ZH for new help / error strings (JSON payload
  keys stay locale-stable English, like the JSONL wire format).
- `tests/test_cli.py`, `tests/test_analyze.py`, `tests/TESTING.md`,
  `docs/zh/TESTING.md`.
