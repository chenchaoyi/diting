## Why

An agent can run `diting stream` for a bounded window or background it with the
harness, but there's no first-class way to launch a long watch, walk away, and
come back to it from a different shell — no list of what's running, no clean
stop, no tail. The `CaptureEngine` (shipped in `headless-capture-engine`) gives
us a faithful headless capture; this change wraps it in diting-managed named
**capture sessions** so a long watch becomes `capture start` → leave →
`capture status` / `tail` → `analyze`, portable across harnesses and shells.

## What Changes

- Add a `capture` subcommand with actions:
  - `capture start --name N [--sensors …] [--out PATH] [--duration D]` — spawn a
    detached `diting stream` for the named session, record it, and return
    immediately (prints the session + its capture path).
  - `capture list [--json]` — every known session with status (running /
    exited / crashed), pid, sensors, capture path, age.
  - `capture status [--name N] [--json]` — one session's record + live status.
  - `capture stop [--name N | --all]` — SIGTERM the session(s) for a clean
    flush-and-exit; mark stopped.
  - `capture tail [--name N] [-n K] [-f]` — print the last K JSONL lines of the
    capture (and follow with `-f`).
- Sessions are tracked under a stable state dir (default `~/.diting/sessions/`,
  overridable via `DITING_STATE_DIR`) so `capture list` works from any CWD. Each
  session is one JSON record (name, pid, sensors, capture path, started-at,
  duration, status). The capture JSONL defaults to `<state>/captures/<name>.jsonl`
  and the stream's stderr to `<state>/sessions/<name>.stderr.log`.
- Liveness + crash detection: a record marked `running` whose pid is no longer
  alive is reported `exited` (clean) or `crashed` — derived live, never trusted
  blindly from the record.
- **`diting stream` SHALL handle SIGTERM** as a graceful shutdown (cancel the
  engine → flush + close the logger → exit 0), so `capture stop` produces a
  complete capture rather than a truncated one. This finishes the SIGTERM
  contract the `cli` spec already states for `stream`.
- Add `src/diting/__main__.py` so `python -m diting …` works; `capture start`
  spawns the child via `python -m diting stream …` (same interpreter / venv,
  PATH-independent).
- `capabilities` + `--help` gain the `capture` verb.

Out of scope: converging the TUI onto the engine (still deferred); a daemon /
supervisor that restarts crashed sessions (sessions are fire-and-forget); remote
sessions.

## Capabilities

### New Capabilities
- `capture-sessions`: the managed-session lifecycle — the state dir + record
  format, start (detached spawn) / list / status / stop / tail semantics, live
  status derivation (running / exited / crashed), and the SIGTERM-clean-stop
  guarantee.

### Modified Capabilities
- `cli`: add `capture` to the canonical subcommand vocabulary; the
  `capabilities` manifest + `--help` reflect it.

## Impact

- New `src/diting/sessions.py` — `SessionStore` (state-dir resolution, record
  CRUD, liveness/status derivation, spawn/stop) — pure + testable apart from the
  actual spawn.
- New `src/diting/__main__.py` — `python -m diting` entry calling `cli.main()`.
- `src/diting/cli.py` — `_run_capture` dispatcher + the five actions; `capture`
  in the `_COMMANDS` table + canonical verb set; a SIGTERM handler installed in
  `_run_stream` before `engine.run()`.
- `tests/` — new `tests/test_sessions.py` (record CRUD, status derivation,
  start/stop with a fake/short-lived process, tail) + `test_cli.py` additions
  (`capture` routing, manifest entry). Update `tests/TESTING.md` (EN + ZH) first.
- `docs/agents.md` + `docs/zh/agents.md` — document the session lifecycle;
  README command tables refreshed.
- No helper schema bump; no JSONL event-schema change. Builds entirely on the
  existing `CaptureEngine` + `EventLogger`.
