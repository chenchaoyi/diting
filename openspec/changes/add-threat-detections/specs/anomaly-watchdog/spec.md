# anomaly-watchdog — delta

## MODIFIED Requirements

### Requirement: `--notify` SHALL raise a notification for note/warn insight events
With `--notify` set, the watchdog SHALL raise a macOS Notification Centre alert
for `insight` events whose `severity` is `note`, `warn`, or `critical`, using
the synthesized human one-liner as the body, subject to the same per-(type,
target) silence window as the anomaly types — keyed by the insight `code` so
distinct insights debounce independently. `info`-severity insights SHALL NOT
notify (they remain log + TUI only). `critical` insights are the threat tier and
always notify. As with the anomaly types, a missing helper binary SHALL be a
silent skip, and the JSONL / TUI event streams SHALL NOT be filtered by the
watchdog.

#### Scenario: A warn insight notifies
- **WHEN** `--notify` is set and a `warn`-severity insight (e.g. `repeated_disassociates`) fires
- **THEN** the watchdog invokes the helper `notify` subcommand with the insight's one-line summary as the body

#### Scenario: A critical threat notifies
- **WHEN** `--notify` is set and a `critical`-severity threat (e.g. `evil_twin`) fires
- **THEN** the watchdog invokes the helper `notify` subcommand with the threat's one-line summary as the body

#### Scenario: An info insight does not notify
- **WHEN** `--notify` is set and an `info`-severity insight (e.g. `band_steering`) fires
- **THEN** no helper `notify` invocation occurs for it
- **AND** the insight is still written to the JSONL log and the TUI Events ring

#### Scenario: Distinct insight codes debounce independently
- **WHEN** two insights with different `code`s fire within one silence window
- **THEN** both notify (the silence window is keyed per insight code)
