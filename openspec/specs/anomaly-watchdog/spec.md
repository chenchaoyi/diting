# anomaly-watchdog Specification

## Purpose
TBD - created by archiving change anomaly-watchdog. Update Purpose after archive.
## Requirements
### Requirement: `--notify` SHALL raise a macOS Notification Centre alert for every anomaly event type
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

### Requirement: `rf_stir` notifications SHALL gate on a configurable confidence threshold
The `rf_stir` notification SHALL fire only when the event's `confidence` field meets or exceeds the threshold configured by the `DITING_NOTIFY_STIR_CONFIDENCE` environment variable, which SHALL accept exactly three values: `high` (default — only high-confidence stirs notify), `medium` (medium- and high-confidence notify), `all` (every stir notifies regardless of confidence). Invalid values SHALL print a one-line warning to stderr and fall back to `high`.

`latency_spike` and `loss_burst` events do not carry a `confidence` field and are NOT subject to this gate.

#### Scenario: default high-confidence gate
- **WHEN** `DITING_NOTIFY_STIR_CONFIDENCE` is unset and a `medium`-confidence `rf_stir` event fires
- **THEN** NO notification is raised (gated out)
- **AND** the JSONL event line is still emitted

#### Scenario: loosened gate
- **WHEN** `DITING_NOTIFY_STIR_CONFIDENCE=medium` and a `medium`-confidence `rf_stir` event fires
- **THEN** a notification IS raised

#### Scenario: invalid value falls back
- **WHEN** `DITING_NOTIFY_STIR_CONFIDENCE=mid` (typo)
- **THEN** stderr prints a one-line warning naming the offending value and the fallback default (`high`)
- **AND** the watchdog continues with the default behaviour (high-confidence-only)

### Requirement: Notifications SHALL be debounced by a per-(event-type, target) silence window
After a notification fires for a given `(event_type, target)` pair, no further notification for the SAME pair SHALL fire until the silence-window duration has elapsed. The silence window is configurable via the `DITING_NOTIFY_SILENCE_S` environment variable (integer seconds, clamped to `3 ≤ N ≤ 3600`); the default is `60` seconds. Invalid values SHALL print a one-line warning to stderr and fall back to the default. The silence window SHALL NOT affect the JSONL event stream — only the notification side-effect is debounced. The silence window state SHALL NOT persist across process restarts.

#### Scenario: rapid duplicate stir notifications are suppressed
- **WHEN** two `rf_stir` events with `location=AS11-2_4` fire 20 seconds apart and the silence window default (60 s) applies
- **THEN** the FIRST event raises a notification
- **AND** the SECOND event does NOT raise a notification (within the silence window)
- **AND** both events are still emitted to the JSONL stream

#### Scenario: silence window clears
- **WHEN** the second `rf_stir` event at `location=AS11-2_4` fires 61 seconds after the first
- **THEN** the second event DOES raise a notification (silence window elapsed)

#### Scenario: parallel anomaly classes have independent silence clocks
- **WHEN** an `rf_stir` at `AS11-2_4` fires and 10 seconds later a `latency_spike` at `gateway:192.168.1.1` fires
- **THEN** BOTH events raise notifications — the silence clock on `(rf_stir, AS11-2_4)` does NOT silence `(latency_spike, gateway:192.168.1.1)`

#### Scenario: out-of-range silence value falls back
- **WHEN** `DITING_NOTIFY_SILENCE_S=1` (below the 3-second floor)
- **THEN** stderr prints a one-line warning and the watchdog uses the default `60`

#### Scenario: silence state resets on process restart
- **WHEN** the user kills and restarts `diting monitor --notify` while a silence window is active for `(rf_stir, AS11-2_4)`
- **THEN** the very next `rf_stir` for `AS11-2_4` raises a notification (in-memory state was lost on restart, which is intentional — first notification per active anomaly class after restart is desirable)

