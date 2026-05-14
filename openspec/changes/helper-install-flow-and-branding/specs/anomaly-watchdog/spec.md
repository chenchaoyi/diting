## MODIFIED Requirements

### Requirement: `--notify` SHALL raise a macOS Notification Centre alert for every anomaly event type, dispatched via the diting helper bundle
With `--notify` set on either `diting monitor` or the default TUI subcommand `diting`, the running process SHALL raise a macOS Notification Centre alert for each of the three anomaly event types — `rf_stir`, `latency_spike`, `loss_burst` — subject to the per-event severity gate and the silence-window debounce defined in subsequent Requirements. The JSONL event stream (emitted by `monitor` to stdout / `--out`, or by the TUI when `--log` is set) SHALL NOT be filtered by the watchdog; only the OS-notification side-effect is debounced. Both entry points SHALL use the same shared watchdog module so behaviour is identical from the user's perspective.

The notification SHALL be dispatched via the `diting-tianer notify` subcommand of the installed helper bundle (not via `osascript`). This ensures the notification carries the diting logo (the bundle's icon) and a stable bundle identity in Notification Centre. If the helper binary cannot be resolved (e.g. the helper bundle is missing or the bundled scan path is broken), the watchdog SHALL silently skip the notification — no fallback to `osascript`, no error propagated into the TUI.

#### Scenario: monitor — latency spike triggers a notification
- **WHEN** the user runs `diting monitor --notify` and a `latency_spike` event fires (gateway probe RTT crosses both the multiplier and absolute thresholds)
- **THEN** the watchdog invokes `<helper-bin> notify --title diting --body "<message>"` with the notification template body (e.g. `Latency spike on gateway:192.168.1.1: 240.5 ms`)
- **AND** macOS Notification Centre shows the alert with the diting-logo icon
- **AND** the same event is emitted as one JSONL line on stdout / `--out` regardless of whether `--notify` is set

#### Scenario: monitor — loss burst triggers a notification
- **WHEN** the user runs `diting monitor --notify` and a `loss_burst` event fires (3 of 5 recent probes lost)
- **THEN** the watchdog invokes the helper `notify` subcommand with a body composed by the notification template (e.g. `Loss burst on WAN:1.1.1.1: 60.0%`)

#### Scenario: TUI — same event types notify with same semantics
- **WHEN** the user runs `diting --notify` (default TUI subcommand) and any of the three anomaly event types fires
- **THEN** the watchdog invokes the helper `notify` subcommand with the same body the headless monitor would have produced, gated by the same severity rules and silence window
- **AND** the TUI's EventsPanel + EventRing keep rendering the event live, independent of the notification

#### Scenario: `--notify` not set means no OS notification
- **WHEN** the user runs `diting monitor` (no `--notify`) OR `diting` (no flag)
- **THEN** NO helper `notify` invocation occurs for any event type
- **AND** the JSONL / TUI event streams are unchanged

#### Scenario: Helper binary unavailable
- **WHEN** `--notify` is set and an event fires, but `macos_helper.resolve_helper_binary()` returns `None`
- **THEN** the watchdog logs nothing and emits nothing — the notification is silently skipped
- **AND** the JSONL event stream is unaffected
