## ADDED Requirements

### Requirement: `--notify` SHALL be valid on both the default TUI subcommand and `monitor`
The `--notify` flag SHALL be parseable on both `diting` (default TUI subcommand) and `diting monitor`. The flag is a boolean toggle (no argument). When set, the running process SHALL raise macOS Notification Centre alerts for the three anomaly event types per the `anomaly-watchdog` capability spec. When unset, no `osascript` invocations SHALL occur and the rest of each subcommand's behaviour SHALL remain unchanged from v0.8.0.

Watchdog SEMANTICS — severity gate, silence window, env-var configuration, notification body composition — live in the `anomaly-watchdog` capability, not in `cli`. This Requirement is only about the flag being recognised at the two entry points.

#### Scenario: TUI user enables notifications
- **WHEN** the user runs `diting --notify` (default subcommand)
- **THEN** the TUI launches as normal and additionally raises OS notifications when anomaly events fire (subject to the watchdog severity gate + silence window)

#### Scenario: TUI user does not enable notifications
- **WHEN** the user runs `diting` with no flag (default subcommand)
- **THEN** the TUI launches as normal and NO `osascript` invocations occur regardless of which events fire

#### Scenario: headless watchdog
- **WHEN** the user runs `diting monitor --notify`
- **THEN** the headless monitor emits JSONL events AND raises OS notifications (same semantics as the TUI path)

#### Scenario: headless without `--notify`
- **WHEN** the user runs `diting monitor` (no `--notify`)
- **THEN** the headless monitor emits JSONL events with NO `osascript` invocations
