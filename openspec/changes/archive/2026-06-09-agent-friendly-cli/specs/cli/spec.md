# cli delta — agent-friendly-cli

## ADDED Requirements

### Requirement: The CLI SHALL never surface an uncaught traceback
`main()` SHALL wrap subcommand dispatch so that no unexpected exception reaches
the interpreter's default handler. `SystemExit` SHALL propagate unchanged (so
deliberate usage / runtime exit codes are preserved) and `KeyboardInterrupt`
SHALL exit cleanly. Any other exception SHALL be reported as a single
`diting: <message>` line on stderr and SHALL exit with code 1 — never a stack
trace. Setting `DITING_DEBUG=1` SHALL re-raise so developers still get the full
traceback.

#### Scenario: An unexpected runtime error is a clean message
- **WHEN** a subcommand hits an uncaught exception (e.g. a filesystem error)
- **THEN** the process prints one `diting: …` line to stderr and exits 1, with no Python traceback

#### Scenario: Debug mode restores the traceback
- **WHEN** the same error occurs with `DITING_DEBUG=1` set
- **THEN** the full traceback is printed (for development)

#### Scenario: Intentional usage exit is unaffected
- **WHEN** a subcommand calls `sys.exit(2)` for a usage error
- **THEN** the process exits 2 (the guard does not rewrite deliberate exits)

### Requirement: `analyze --for-llm` SHALL take its output directory via `--out-dir`, not a greedy positional
`--for-llm` SHALL be a boolean flag. The bundle output directory SHALL be given
by `-o` / `--out-dir DIR` (with `--for-llm=DIR` accepted for back-compat); a
bare `--for-llm` followed by the input log SHALL NOT consume the log as the
output directory. When no output directory is given, the bundle SHALL default
to `diting-llm-<timestamp>/`. If the resolved output directory already exists
as a non-directory file, the CLI SHALL emit a usage error and exit 2 rather
than crash.

#### Scenario: The reported crash no longer happens
- **WHEN** the user runs `diting analyze --for-llm <log.jsonl>`
- **THEN** `<log.jsonl>` is treated as the input, the bundle is written to the default `diting-llm-<timestamp>/`, and the process does not crash

#### Scenario: Out-dir given explicitly
- **WHEN** the user runs `diting analyze <log.jsonl> --for-llm -o /tmp/bundle`
- **THEN** the bundle is written under `/tmp/bundle`

#### Scenario: Out-dir collides with a file
- **WHEN** the resolved output directory path already exists as a regular file
- **THEN** the CLI prints a usage error and exits 2, not a traceback

### Requirement: `once`, `analyze`, and `watch` SHALL support `--json` machine-readable output
With `--json`, `once` and `analyze` SHALL print exactly one JSON document to
stdout, and `watch` SHALL print a newline-delimited stream of one JSON object
per change event. In `--json` mode stdout SHALL carry ONLY the JSON — every
banner / hint / human prose SHALL go to stderr — and any error SHALL be emitted
as a JSON object (`{"error": <message>, "code": <int>}`) on stderr. JSON keys
and values SHALL be locale-stable English regardless of `--lang` (an agent
parses keys; localization applies only to human prose on stderr).

#### Scenario: analyze emits one parseable JSON document
- **WHEN** the user runs `diting analyze <log> --json`
- **THEN** stdout is a single JSON object carrying the report's counts, timeline, temporal / population aggregates and insights, and `stdout | jq .` parses cleanly

#### Scenario: once emits a connection snapshot
- **WHEN** the user runs `diting once --json`
- **THEN** stdout is one JSON object with the connection snapshot, permission state, and backend

#### Scenario: watch emits a JSON line-stream
- **WHEN** the user runs `diting watch --json`
- **THEN** each surfaced change event is one JSON object on its own line, tailable by an agent

#### Scenario: JSON mode keeps stdout pure
- **WHEN** any `--json` command also has chrome to show (scene banner, permission hint)
- **THEN** that chrome is written to stderr and stdout stays valid JSON

#### Scenario: Errors are JSON under --json
- **WHEN** a `--json` run fails (bad input, runtime error)
- **THEN** the failure is a JSON object on stderr with an `error` message and a numeric `code`, and the exit code follows the documented convention

### Requirement: The CLI SHALL document subcommand help and a stable exit-code convention
Each subcommand SHALL accept `--help` / `-h` and print its own usage with at
least one EXAMPLES entry and a note of its automation surface (`--json` where
applicable). The CLI SHALL follow a documented exit-code convention: `0`
success, `1` runtime error (including `once` when not associated), `2` usage
error (unknown flag / bad argument / unknown subcommand). The top-level help
SHALL state this convention.

#### Scenario: Per-subcommand help
- **WHEN** the user runs `diting analyze --help`
- **THEN** analyze-specific usage, flags, an example, and the `--json` note are printed and the process exits 0

#### Scenario: Exit codes are consistent
- **WHEN** an unknown flag is passed to a subcommand
- **THEN** the process exits 2; a successful run exits 0; an uncaught runtime error exits 1
