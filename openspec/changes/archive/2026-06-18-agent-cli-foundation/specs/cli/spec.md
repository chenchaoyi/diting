## ADDED Requirements

### Requirement: Agent-facing subcommands SHALL be `status`, `scan`, `stream`, `calibrate`, `analyze`, `companion`, `capabilities`

The CLI SHALL accept exactly these non-default subcommands, plus the default
(no-subcommand) TUI action:

- `status` — print a single Connection + permission snapshot to stdout and exit
- `scan` — print a one-shot sensor snapshot (`--wifi` / `--ble`; default both)
  to stdout and exit
- `stream` — emit a foreground, bounded canonical-JSONL event stream on stdout
  (`--duration` optional; runs until Ctrl+C / SIGTERM when unbounded)
- `calibrate` — record an empty-room σ baseline (default 300 s)
- `analyze [PATH]` — post-process a JSONL log file into a report
- `companion` — pairing actions (semantics owned by the `companion-bridge`
  capability)
- `capabilities` — emit a machine-readable manifest of the CLI surface

Adding or removing a canonical subcommand MUST file an ADDED / REMOVED
Requirement on this capability. `scan` and `stream` cover only the
already-headless-capable sensors (Wi-Fi, BLE) at this capability version; the
`headless-capture-engine` capability widens the sensor set later.

#### Scenario: Each subcommand prints its primary output
- **WHEN** the user runs `diting status`
- **THEN** one Connection snapshot is printed and the process exits 0

#### Scenario: Unknown subcommand is a usage error
- **WHEN** the user runs `diting frobnicate`
- **THEN** stderr names the unknown subcommand and the process exits 2

### Requirement: The deprecated verbs `once`, `watch`, `monitor` SHALL forward to their canonical replacements

The CLI SHALL keep `once`, `watch`, and `monitor` registered as deprecation
aliases for at least one release:

- `once` → `status`
- `watch` → `stream`
- `monitor` → `stream`

Invoking an alias SHALL run the canonical handler unchanged AND print exactly one
deprecation line to **stderr** of the form `diting: 'once' is deprecated; use
'status'`. The notice SHALL go to stderr even under `--json` so that stdout stays
pure JSON. The `capabilities` manifest SHALL list each alias and its canonical
target under a `deprecated_aliases` map.

#### Scenario: Old verb still works with a notice
- **WHEN** the user runs `diting once --json`
- **THEN** stdout carries the same JSON object as `diting status --json`
- **AND** stderr carries one `diting: 'once' is deprecated; use 'status'` line
- **AND** the process exits 0

#### Scenario: Alias notice never pollutes JSON stdout
- **WHEN** the user runs `diting monitor --json | jq .`
- **THEN** jq parses every stdout line; the deprecation notice appears only on stderr

### Requirement: `status` SHALL print a single Connection + permission snapshot

`status` (the renamed `once`) SHALL print one Connection snapshot and exit. With
`--json` it SHALL print exactly one JSON object carrying the connection snapshot,
permission state, and backend name. When the host is not associated to any
network, `status` SHALL still print a well-formed (dis-associated) snapshot and
exit with code 1 per the exit-code convention.

#### Scenario: Associated host
- **WHEN** the user runs `diting status --json` while connected
- **THEN** stdout is one JSON object with the connection, permission state, and backend; exit 0

#### Scenario: Not associated
- **WHEN** the user runs `diting status` while not on any Wi-Fi
- **THEN** a dis-associated snapshot is printed and the process exits 1

### Requirement: `scan` SHALL print a one-shot sensor snapshot

`scan` SHALL collect a single snapshot from the selected sensors and exit. Flags
`--wifi` and `--ble` select sensors; with neither, both run. `--duration D`
bounds the BLE collection window (default a few seconds). With `--json`, stdout
SHALL be one JSON object keyed by sensor (`wifi`, `ble`), each value a list of
results; without `--json`, a human table per sensor. Wi-Fi results come from the
helper scan; BLE results are decoded via the registered decoders. A sensor that
is unavailable (e.g. helper missing, permission denied) SHALL surface a
structured error for that sensor without aborting the others.

#### Scenario: Combined Wi-Fi + BLE snapshot
- **WHEN** the user runs `diting scan --json`
- **THEN** stdout is one JSON object with a `wifi` array and a `ble` array; exit 0

#### Scenario: Single sensor
- **WHEN** the user runs `diting scan --wifi --json`
- **THEN** stdout carries only the `wifi` array

#### Scenario: One sensor unavailable
- **WHEN** the user runs `diting scan --json` with Bluetooth permission denied
- **THEN** the `wifi` array is present and the `ble` value is a structured `{"error",...}`; exit follows the convention (0 if any sensor succeeded)

### Requirement: `stream` SHALL emit canonical JSONL on stdout with no other output

`stream` (subsuming the headless role of `monitor`) SHALL produce ONLY the
canonical event-log JSONL stream on stdout — the same schema `analyze` consumes —
with no banner, progress, or decorative text. All status / error messages SHALL
go to stderr. `--duration D` SHALL bound the run; when omitted, the stream runs
until Ctrl+C or SIGTERM. SIGTERM SHALL flush the final event and exit cleanly.

#### Scenario: Pipe to jq
- **WHEN** the user runs `diting stream | jq 'select(.type=="roam")'`
- **THEN** jq receives only valid JSON lines; nothing breaks the pipeline

#### Scenario: Bounded run
- **WHEN** the user runs `diting stream --duration 10s`
- **THEN** the stream emits canonical JSONL for ~10 s, flushes, and exits 0

#### Scenario: Pipe to head closes cleanly
- **WHEN** the user runs `diting stream | head -n 10`
- **THEN** the stream exits cleanly via SIGPIPE after head closes; no zombie process

### Requirement: `capabilities` SHALL emit a machine-readable manifest of the CLI surface

`diting capabilities` SHALL emit a self-describing manifest built from the same
declarative command table that drives parsing and `--help`, so the manifest can
never drift from actual behaviour. With `--json` it SHALL print one JSON object
with a top-level integer `schema_version` (starting at `1`), a `commands` array
(each entry: `name`, `summary`, `flags` as `{name,type,default,repeatable}`,
`output` one of `json-object|json-lines|text|tui`, and `exit_codes`), a
`deprecated_aliases` map, and the global exit-code convention. Without `--json`
it SHALL pretty-print the same information. Every dispatchable canonical verb
SHALL appear in `commands`, and every entry in `commands` SHALL be dispatchable.

#### Scenario: Agent discovers the surface
- **WHEN** an agent runs `diting capabilities --json`
- **THEN** stdout is one JSON object with `schema_version`, a `commands` array covering every canonical verb, and a `deprecated_aliases` map; `jq .` parses cleanly

#### Scenario: Manifest matches dispatch
- **WHEN** the manifest is compared against the dispatcher's known subcommands
- **THEN** the set of canonical `commands[].name` equals the set of dispatchable canonical verbs (no orphans either way)

### Requirement: `--duration` and `--since` SHALL share a uniform grammar across commands

Commands that bound a time window SHALL accept a uniform grammar: `--duration D`
on `scan`/`stream` and `--since D` on `analyze`, where `D` is `<int>` seconds or
`<int>` suffixed with `s`/`m`/`h` (e.g. `30s`, `5m`, `2h`). An unparseable value
SHALL be a usage error (exit 2) with a one-line stderr message naming the flag.
`--since` SHALL reuse the existing `analyze` duration grammar so the two are
identical.

#### Scenario: Suffix forms
- **WHEN** the user runs `diting stream --duration 5m`
- **THEN** the stream is bounded to 300 s

#### Scenario: Bad duration
- **WHEN** the user runs `diting scan --duration soon`
- **THEN** stderr names the bad `--duration` value and the process exits 2

## MODIFIED Requirements

### Requirement: The CLI SHALL document subcommand help and a stable exit-code convention

Each subcommand SHALL accept `--help` / `-h` and print its own usage with at
least one EXAMPLES entry and a note of its automation surface (`--json` where
applicable). The per-subcommand help text SHALL be generated from the same
declarative command table that backs `capabilities`, so help and manifest cannot
drift. The CLI SHALL follow a documented exit-code convention: `0` success, `1`
runtime error (including `status` when not associated), `2` usage error (unknown
flag / bad argument / unknown subcommand). The top-level `diting --help` SHALL
state this convention and point at `diting capabilities` for the machine-readable
surface.

#### Scenario: Per-subcommand help
- **WHEN** the user runs `diting analyze --help`
- **THEN** analyze-specific usage, flags, an example, and the `--json` note are printed and the process exits 0

#### Scenario: Exit codes are consistent
- **WHEN** an unknown flag is passed to a subcommand
- **THEN** the process exits 2; a successful run exits 0; an uncaught runtime error exits 1

#### Scenario: Top-level help points at capabilities
- **WHEN** the user runs `diting --help`
- **THEN** the output states the exit-code convention and references `diting capabilities` for the machine-readable command surface

## REMOVED Requirements

### Requirement: Subcommands SHALL be `once`, `watch`, `monitor`, `calibrate`, `analyze`
**Reason**: Redesigned into the agent-facing verb set (`status`, `scan`,
`stream`, `calibrate`, `analyze`, `companion`, `capabilities`). Superseded by
"Agent-facing subcommands SHALL be `status`, `scan`, `stream`, `calibrate`,
`analyze`, `companion`, `capabilities`".
**Migration**: `once` → `status`, `watch` → `stream`, `monitor` → `stream`. The
old verbs remain as forwarding deprecation aliases for at least one release (see
"The deprecated verbs `once`, `watch`, `monitor` SHALL forward to their canonical
replacements").

### Requirement: `diting monitor` SHALL emit JSONL on stdout with no other output
**Reason**: The headless-stream role moved from `monitor` to `stream`.
**Migration**: Use `diting stream` (same pure-JSONL-on-stdout contract);
`diting monitor` continues to work as an alias. Superseded by "`stream` SHALL
emit canonical JSONL on stdout with no other output".

### Requirement: `once`, `analyze`, and `watch` SHALL support `--json` machine-readable output
**Reason**: The `--json` contract is broadened from three commands to every read
command and unified under one implementation.
**Migration**: Superseded by "All read commands SHALL support `--json`"; behaviour
for the renamed verbs (`status`, `stream`) and `analyze` is preserved.

## ADDED Requirements

### Requirement: All read commands SHALL support `--json`

`status`, `scan`, `stream`, `analyze`, and `capabilities` SHALL each accept
`--json`. Under `--json`, `status`/`scan`/`analyze`/`capabilities` SHALL print
exactly one JSON document to stdout and `stream` SHALL print newline-delimited
JSON (one object per event). stdout SHALL carry ONLY the JSON — every banner,
hint, deprecation notice, and human prose SHALL go to stderr — and any error
SHALL be emitted as a JSON object (`{"error": <message>, "code": <int>}`) on
stderr with the matching exit code. JSON keys and values SHALL be locale-stable
English regardless of `--lang`. All five commands SHALL share one JSON-output
implementation so purity and error semantics are identical across them.

#### Scenario: analyze emits one parseable JSON document
- **WHEN** the user runs `diting analyze <log> --json`
- **THEN** stdout is a single JSON object carrying the report's counts, timeline, aggregates, and insights, and `stdout | jq .` parses cleanly

#### Scenario: status emits a connection snapshot
- **WHEN** the user runs `diting status --json`
- **THEN** stdout is one JSON object with the connection snapshot, permission state, and backend

#### Scenario: stream emits a JSON line-stream
- **WHEN** the user runs `diting stream --json`
- **THEN** each event is one JSON object on its own line, tailable by an agent

#### Scenario: JSON mode keeps stdout pure
- **WHEN** any `--json` command also has chrome to show (scene banner, permission hint, deprecation notice)
- **THEN** that chrome is written to stderr and stdout stays valid JSON

#### Scenario: Errors are JSON under --json
- **WHEN** a `--json` run fails (bad input, runtime error)
- **THEN** the failure is a JSON object on stderr with an `error` message and a numeric `code`, and the exit code follows the documented convention

### Requirement: `--notify` SHALL be valid on both the default TUI subcommand and `stream`

The `--notify` flag SHALL be parseable on both `diting` (default TUI subcommand)
and `diting stream`. The flag is a boolean toggle (no argument). When set, the
running process SHALL raise macOS Notification Centre alerts for the anomaly
event types per the `anomaly-watchdog` capability spec. When unset, no
`osascript` invocations SHALL occur and the rest of each subcommand's behaviour
SHALL remain unchanged. Because `monitor` forwards to `stream`, `diting monitor
--notify` SHALL continue to work via the alias.

Watchdog SEMANTICS — severity gate, silence window, env-var configuration,
notification body composition — live in the `anomaly-watchdog` capability, not in
`cli`. This Requirement is only about the flag being recognised at the two entry
points.

#### Scenario: TUI user enables notifications
- **WHEN** the user runs `diting --notify` (default subcommand)
- **THEN** the TUI launches as normal and additionally raises OS notifications when anomaly events fire (subject to the watchdog severity gate + silence window)

#### Scenario: headless watchdog
- **WHEN** the user runs `diting stream --notify`
- **THEN** the headless stream emits JSONL events AND raises OS notifications (same semantics as the TUI path)

#### Scenario: alias keeps working
- **WHEN** the user runs `diting monitor --notify`
- **THEN** the alias forwards to `stream`, the deprecation notice prints to stderr, and notifications fire as for `diting stream --notify`

#### Scenario: headless without `--notify`
- **WHEN** the user runs `diting stream` (no `--notify`)
- **THEN** the headless stream emits JSONL events with NO `osascript` invocations
