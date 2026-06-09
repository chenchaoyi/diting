# agent-friendly-cli — design

## Context

`cli.py` hand-rolls arg parsing; each subcommand runner parses its own args and
`sys.exit(2)` on usage errors. `main()` dispatches with no try/except. The
scene banner already goes to stderr (silenceable via `DITING_SCENE_QUIET`), so
stdout is nearly clean already. `Report` (analyze) and `Connection` (models)
are dataclasses. `monitor` already streams JSONL.

## Goals / Non-Goals

**Goals:** never surface a traceback; emit clean parseable JSON on demand from
the collect commands; fix the reported arg footgun; make usage + exit codes
self-explanatory.

**Non-Goals:** argparse rewrite; a capabilities manifest; touching monitor/TUI.

## Decisions

- **One top-level guard, not per-runner.** `main()` wraps the whole dispatch in
  a try/except: re-raise `SystemExit` (so deliberate `exit(2)` usage errors and
  `exit(0)`/`exit(1)` keep their codes), swallow `KeyboardInterrupt` cleanly,
  and turn any other `Exception` into `diting: <message>` on stderr + exit 1.
  A module-level `_DEBUG = bool(os.environ.get("DITING_DEBUG"))` re-raises so
  developers still get the trace. This is the smallest change that fixes the
  whole crash class (including the reported one) rather than patching one site.
- **`--for-llm` boolean + `--out-dir`.** The optional-value form is the bug.
  New: `--for-llm` (bool) + `-o DIR` / `--out-dir DIR`. Back-compat: still
  accept `--for-llm=DIR`. The bare `--for-llm <path>` stops consuming the next
  token. Out-dir validation: exists-as-file → usage error (exit 2); else mkdir
  parents. Defaulting (no out-dir) keeps `diting-llm-<ts>/`.
- **`--json` is an output-format switch, parsed globally per runner.** When
  set: build the data structure, `json.dumps` it to stdout, and route ALL
  chrome (banners, hints, the bundle-written summary) to stderr. `once`/
  `analyze` print one document; `watch` prints one compact object per event,
  newline-delimited (the JSONL convention an agent can tail). The watch JSON
  shaper mirrors the existing `_render` decision logic but returns a dict.
- **JSON payload keys are locale-stable English**, exactly like the JSONL wire
  format — `--lang zh --json` localizes nothing inside the JSON (an agent
  parses keys, a human reads prose). Only human help/error *prose* is localized.
- **Errors-as-JSON under `--json`.** A small `_fail(msg, code, *, as_json)`
  helper: prose to stderr normally, `{"error": msg, "code": code}` to stderr
  under `--json`. The top-level guard also honors an "is this a --json run"
  flag so an unexpected exception still emits a JSON error when the user asked
  for JSON.
- **Serializers live next to their data.** `analyze.report_to_dict(report)`
  (reuses the dataclasses; covers counts, timeline, temporal/population/
  coincidence aggregates, insights). `models.connection_to_dict(conn)`. Keeps
  cli.py thin and the shapes unit-testable without the CLI.
- **Exit codes documented + audited.** 0 ok · 1 runtime error (incl.
  not-associated `once`) · 2 usage error. The per-subcommand help and the
  spec name them so an agent can branch on them.

## Risks / Trade-offs

- [Top-level guard hides a real bug behind a one-liner] → `DITING_DEBUG=1`
  restores the trace; tests assert both the clean message and the debug
  re-raise. Net safer than today's raw crash.
- [`--for-llm` behavior change breaks a script] → `--for-llm=DIR` still works;
  only the fragile bare-positional form changes (which was the crash). Noted in
  help.
- [JSON shape churn] → keys are additive and locale-stable; tests pin the shape;
  documented as the agent contract.
- [Localization confusion] → explicit rule: JSON values/keys are English;
  `--json` + `--lang` only affects any human prose that still goes to stderr.

## Decision: CLI usage / help is English-only

The `--help` / usage text (`_usage` + the new per-subcommand helps) is
English-only — developer- and agent-facing (CLI help and `--json` are
conventionally English), and the prior bilingual `_usage` had **already
silently drifted to English-only** (its ZH catalog entry listed a stale
subcommand set and lacked three global flags, so `--lang zh --help` never
matched and fell back to English). Rather than maintain a 50-line bilingual
help block that has proven an unmaintained trap, the help builders drop `t()`
and the dead ZH entry is removed. Runtime prose and **error messages stay
bilingual** (the three new analyze error strings get ZH).
