# cli Specification

## Purpose

Defines wifiscope's command-line surface — the subcommand vocabulary
(`once`, `watch`, `monitor`, `calibrate`, `analyze`, default-TUI),
how flags resolve (`--lang`, `--log <PATH>`, `--config`), and the
exit-hint contract that points users at their just-finished session
log. The CLI is the user's first contact with the tool; backward-
compatible flag parsing is load-bearing.

## Requirements

### ADDED Requirement: `wifiscope` with no subcommand SHALL launch the TUI
The default action SHALL be the interactive TUI. Users invoking
`wifiscope` (no subcommand) SHALL get the four-panel dashboard with
no further configuration. SHALL NOT print help text first; SHALL
NOT require any flag.

#### Scenario: First-time user
- **WHEN** they run `wifiscope`
- **THEN** the TUI starts immediately, no preamble

### ADDED Requirement: Subcommands SHALL be `once`, `watch`, `monitor`, `calibrate`, `analyze`
The CLI SHALL accept exactly these five non-default subcommands:

- `once` — print a single Connection snapshot to stdout and exit
- `watch` — streaming colourised event log on stdout, Ctrl+C to quit
- `monitor` — headless JSONL events stream for long-runs / Home Assistant
- `calibrate` — record an empty-room σ baseline (default 300 s)
- `analyze [PATH]` — post-process a JSONL log file into a report

Adding a sixth subcommand or removing one MUST file an ADDED /
REMOVED Requirement on this capability.

#### Scenario: Each subcommand prints its primary output
- **WHEN** the user runs `wifiscope once`
- **THEN** one Connection-line is printed and the process exits 0

### ADDED Requirement: `--lang en|zh` SHALL override env / locale resolution
The `--lang` flag SHALL be the highest-priority language source,
overriding `WIFISCOPE_LANG` env var and the system locale. Invalid
values SHALL exit non-zero with a clear error message; missing
value (`--lang` without an argument) SHALL also exit non-zero.

#### Scenario: ZH user wants EN UI for one run
- **WHEN** they run `wifiscope --lang en` on a `LANG=zh_CN` system
- **THEN** the UI renders English

#### Scenario: Typo
- **WHEN** they run `wifiscope --lang fr`
- **THEN** the CLI prints "unsupported language: 'fr'" and exits non-zero

### ADDED Requirement: `--log [PATH]` SHALL enable JSONL logging with sensible defaults
The TUI default action SHALL accept `--log` with optional value:

- `--log /tmp/foo.jsonl` — log to that exact path
- `--log` (no value) — log to a default path under
  `wifiscope-<YYYYMMDD-HHMMSS>.jsonl` in the current directory

The log file SHALL be created on-demand at first event; an unwritable
directory SHALL be reported via `notify` and the TUI SHALL continue
without logging rather than crash.

#### Scenario: User wants a log but doesn't care where
- **WHEN** they run `wifiscope --log`
- **THEN** the tool creates `./wifiscope-20260509-153012.jsonl` (or similar timestamp) and emits events into it

#### Scenario: Path under a read-only directory
- **WHEN** they run `wifiscope --log /etc/wifi.jsonl` (no write permission)
- **THEN** the TUI shows a notification and continues running unlogged, exit code 0

### ADDED Requirement: TUI exit SHALL print a tip pointing at the just-written log
After a TUI session that wrote to `--log`, the CLI SHALL print to
stdout (NOT stderr — must be pipeable):

```
tip: summarise this session with
       wifiscope analyze <path>
```

If `--log` was not used, the exit hint SHALL be omitted. The hint
SHALL appear AFTER any final session statistics, just before
returning from the entry point.

#### Scenario: User logged a session, quits with `q`
- **WHEN** they exit the TUI
- **THEN** the last line on stdout is the analyze tip with the file path filled in

#### Scenario: User did not pass --log
- **WHEN** they exit
- **THEN** no tip is printed; only any final-stats line

### ADDED Requirement: `wifiscope monitor` SHALL emit JSONL on stdout with no other output
The monitor subcommand SHALL produce ONLY the JSONL event stream on
stdout — no banner, no progress messages, no decorative text. All
status / error messages SHALL go to stderr. SIGTERM SHALL flush the
final event and exit cleanly.

#### Scenario: Pipe to jq
- **WHEN** user runs `wifiscope monitor | jq 'select(.type=="roam")'`
- **THEN** jq receives only valid JSON lines; nothing breaks the pipeline

#### Scenario: Pipe to head -n 10
- **WHEN** user runs `wifiscope monitor | head -n 10`
- **THEN** the monitor exits cleanly via SIGPIPE after head closes; no zombie process

### ADDED Requirement: `--config <PATH>` SHALL accept a custom inventory file location
The `--config <PATH>` flag SHALL override the default `aps.yaml`
search path (current working directory). A missing file SHALL
silently fall back to empty inventory (per `inventory` capability) —
NOT an error.

#### Scenario: Multi-site user
- **WHEN** they run `wifiscope --config ~/.wifiscope/home.yaml` and tomorrow `wifiscope --config ~/.wifiscope/office.yaml`
- **THEN** AP names load from the appropriate file each session
