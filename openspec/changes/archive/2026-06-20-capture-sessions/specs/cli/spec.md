## MODIFIED Requirements

### Requirement: Agent-facing subcommands SHALL be `status`, `scan`, `stream`, `calibrate`, `analyze`, `companion`, `capabilities`

The CLI SHALL accept exactly these non-default subcommands, plus the default
(no-subcommand) TUI action:

- `status` — print a single Connection + permission snapshot to stdout and exit
- `scan` — print a one-shot sensor snapshot (`--wifi` / `--ble` / `--lan` /
  `--mdns`; Wi-Fi + BLE by default) to stdout and exit
- `stream` — emit a foreground, bounded canonical-JSONL event stream on stdout
  (`--sensors` selects the engine's sensor set; `--duration` optional; runs
  until Ctrl+C / SIGTERM when unbounded)
- `capture` — manage detached named capture sessions (`start` / `list` /
  `status` / `stop` / `tail`; lifecycle owned by the `capture-sessions`
  capability)
- `calibrate` — record an empty-room σ baseline (default 300 s)
- `analyze [PATH]` — post-process a JSONL log file into a report
- `companion` — pairing actions (semantics owned by the `companion-bridge`
  capability)
- `capabilities` — emit a machine-readable manifest of the CLI surface

Adding or removing a canonical subcommand MUST file an ADDED / REMOVED
Requirement on this capability. The headless sensor set driven by `scan` /
`stream` is governed by the `headless-capture` capability.

#### Scenario: Each subcommand prints its primary output
- **WHEN** the user runs `diting status`
- **THEN** one Connection snapshot is printed and the process exits 0

#### Scenario: Unknown subcommand is a usage error
- **WHEN** the user runs `diting frobnicate`
- **THEN** stderr names the unknown subcommand and the process exits 2

#### Scenario: capture is a dispatchable canonical verb
- **WHEN** an agent reads `diting capabilities --json`
- **THEN** `capture` appears in the `commands` array, and `diting capture --help` prints its actions
