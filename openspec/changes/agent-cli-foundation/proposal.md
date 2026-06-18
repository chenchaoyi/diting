## Why

diting's CLI grew organically around a human at a TUI: subcommands are
inconsistent (`once`/`watch`/`monitor` each parse their own flags and emit
different shapes), there is no machine-discoverable surface, and `--json` is
bolted onto three commands but absent from the rest. An agent driving diting as
a tool has to reverse-engineer the vocabulary from help text and can't rely on a
stable contract. This change establishes that contract — a uniform, JSON-first,
self-describing CLI — as the foundation the headless capture engine and managed
watch sessions (separate follow-up changes) build on.

## What Changes

- **BREAKING** Redesign the agent-facing verb set to a predictable scheme:
  - `status` (one-shot connection + permission snapshot) — was `once`
  - `scan` (one-shot sensor snapshot; `--wifi` / `--ble`, default both) — new
  - `stream` (foreground bounded canonical-JSONL event stream, `--duration`) —
    subsumes the headless-stream role of `monitor` and the live role of `watch`
  - `analyze`, `calibrate`, `companion` — unchanged vocabulary
  - `capabilities` (machine-readable command/flag/exit-code/output surface) — new
  - bare `diting` still launches the human TUI
- Keep `once`, `watch`, `monitor` as **deprecation aliases** that forward to the
  new verb, print a one-line deprecation notice to stderr, and continue working
  for at least one release so existing scripts/muscle-memory don't break.
- Extend the uniform `--json` contract (stdout = JSON only, chrome + errors to
  stderr as `{"error","code"}`, locale-stable English keys) to **every** read
  command: `status`, `scan`, `stream`, `analyze`, `capabilities`.
- Standardize the exit-code convention (`0` ok, `1` runtime, `2` usage) and a
  uniform `--duration` / `--since` flag grammar across commands that accept them.
- Add `capabilities --json`: emit a stable manifest of every command, its flags
  (name/type/default), its output mode, and the exit-code convention, so an
  agent can self-discover the surface without scraping help text.
- Add an agent-facing guide (`docs/agents.md` + `docs/zh/agents.md`) describing
  the tool surface, JSON contracts, and recommended invocation patterns.

Out of scope (follow-up changes): bringing BLE/LAN/mDNS/RF into the headless
capture path (`headless-capture-engine`), and diting-managed background watch
sessions (`capture-sessions`). `scan`/`stream` here cover only the sensors that
are already headless-capable today (Wi-Fi, BLE).

## Capabilities

### New Capabilities
<!-- none — the discovery command is CLI behaviour, kept inside the cli capability -->

### Modified Capabilities
- `cli`: replace the five-subcommand vocabulary requirement with the redesigned
  agent-facing verb set + deprecation aliases; add the `capabilities` command;
  broaden the `--json` machine-output requirement from `once`/`watch`/`analyze`
  to all read commands; formalize the `--duration`/`--since` flag grammar and
  the exit-code convention as first-class requirements.

## Impact

- `src/diting/cli.py` — dispatcher, the per-subcommand handlers (`_run_once` →
  `status`, `_run_watch`/`_run_monitor` role → `stream`, new `_run_scan`,
  `_run_capabilities`), help builders, and the alias-forwarding shims.
- `tests/` — new CLI contract tests (verb routing, alias deprecation notices,
  `--json` purity on stdout, `capabilities` manifest shape, exit codes). Update
  `tests/TESTING.md` (EN + ZH) first per test-first discipline.
- `docs/agents.md` + `docs/zh/agents.md` — new agent guide (EN ↔ ZH parity).
- `README.md` + `docs/zh/README.md` — refresh the command table for the new
  verbs (user-facing surface change).
- No engine/poller/decoder changes; no helper schema bump. The `analyze`,
  `event_log`, and poller layers are untouched.
