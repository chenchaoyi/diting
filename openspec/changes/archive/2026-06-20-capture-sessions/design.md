## Context

`CaptureEngine` (in `headless-capture-engine`) drives a full-sensor headless
capture and emits canonical JSONL; `diting stream` is a thin foreground wrapper
around it. diting has no background-process management — state files
(`diting-companion.json`, `diting-familiarity.json`) sit in the CWD by
convention. There is no SIGTERM handler on `stream` today, so a kill truncates
the capture mid-flush.

## Goals / Non-Goals

**Goals:**
- `capture start/list/status/stop/tail` — launch a detached named watch, find it
  from any shell, stop it cleanly, tail its output.
- Live status derivation (running / exited / crashed) from pid liveness.
- A clean SIGTERM stop so a stopped capture is complete, not truncated.

**Non-Goals:**
- A supervising daemon, auto-restart, or scheduling (sessions are
  fire-and-forget; the harness/cron owns recurrence).
- Converging the TUI onto the engine.
- Remote / cross-host sessions.

## Decisions

### D1 — Stable state dir, not CWD
Sessions live under a fixed root so `capture list` works regardless of CWD:
`DITING_STATE_DIR` (default `~/.diting`). Layout:
`~/.diting/sessions/<name>.json` (record), `~/.diting/captures/<name>.jsonl`
(capture, unless `--out` overrides), `~/.diting/sessions/<name>.stderr.log`
(the child's stderr). This deviates from the CWD convention deliberately —
session discovery from anywhere is the whole point. The capture file holds real
BSSIDs/MACs; living under `~/.diting` (outside any repo) keeps it uncommitted.

  Alternative considered: CWD-relative like the other state files. Rejected —
  `capture list` from a different directory wouldn't find the session.

### D2 — Detached child via `python -m diting stream`
`capture start` spawns `[sys.executable, "-m", "diting", "stream", "--sensors",
…, "--out", <capture>]` with `start_new_session=True` (own process group so the
parent's exit / Ctrl+C doesn't take it down), stdin=DEVNULL, stdout=DEVNULL
(JSONL goes to `--out`), stderr=<name>.stderr.log. The record stores the child
pid. A new `src/diting/__main__.py` (calls `cli.main()`) makes `-m diting` work
without depending on the `diting` script being on PATH.

  Alternative considered: fork + run the engine in-process. Rejected — a real
  child `diting stream` is simpler to reason about, isolates crashes, and reuses
  the exact foreground path.

### D3 — Status is derived, never trusted
A record stores `status: "running"` + `pid`. `list`/`status` recompute: if the
pid is alive (`os.kill(pid, 0)`), it's `running`; if dead and the record was
`running`, it's `exited` (the process ended on its own — e.g. `--duration`
elapsed) — surfaced as `exited`/`crashed` without distinguishing exit codes
(the child is detached; we don't reap it). `stop` records `stopped`. This means
a crashed capture is visible in `list`, not a phantom `running`.

### D4 — Clean SIGTERM stop
`_run_stream` installs `loop.add_signal_handler(SIGTERM, cancel)` before
`engine.run()`; the cancel unwinds into the engine's existing teardown (flush
familiarity, close logger), then the process exits 0. `capture stop` sends
SIGTERM to the pid and marks the record `stopped`. This satisfies the `stream`
SIGTERM requirement already in the `cli` spec and makes stopped captures
complete.

### D5 — `tail` reuses the capture file
`capture tail` reads the session's capture path: `-n K` prints the last K lines;
`-f` follows (poll-append) until interrupted. No new format — it's the same
JSONL `analyze` consumes, so `capture tail -n 50 | jq` works.

### D6 — Name rules + collisions
`--name` is required for `start`, `[a-zA-Z0-9._-]+`. Starting a name whose
session is still `running` is a usage error (exit 2) — stop it first; starting a
name whose prior session has `exited`/`stopped` overwrites the record (and the
capture file, unless `--out` is given).

## Risks / Trade-offs

- [Orphaned children if the record is deleted] → `stop --all` and `list` operate
  on records; a child whose record was hand-deleted is not tracked. Mitigation:
  document that `~/.diting/sessions/` is the registry; `stop` by pid is possible
  via the record only.
- [Detached child not reaped → zombie] → With `start_new_session=True` and the
  parent exiting immediately, the child is reparented to init/launchd, which
  reaps it; we never `wait()` it. No zombies on macOS/Linux.
- [SIGTERM handler regresses foreground stream] → The handler only adds a clean
  cancel path; Ctrl+C (SIGINT) behaviour is unchanged. Covered by a test that a
  SIGTERM'd stream still closes its logger.
- [State dir under `$HOME` surprises CI] → `DITING_STATE_DIR` override; tests
  point it at a tmp dir. Default creation is lazy (first `start`).

## Migration Plan

1. Land `SessionStore` + `__main__.py` + the SIGTERM handler (additive).
2. Add the `capture` verb; existing verbs untouched.
3. Docs/README teach `capture`.

## Open Questions

- None blocking. A future change could add `capture analyze <name>` sugar
  (= `analyze <session capture path>`); deferred — `analyze $(capture status
  --json | jq -r .capture_path)` already works.
