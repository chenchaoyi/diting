# insights Specification

## Purpose
TBD - created by archiving change add-insight-events. Update Purpose after archive.
## Requirements
### Requirement: A live insight engine SHALL synthesize valuable-change events
The system SHALL provide an insight engine that observes the enriched event
stream (the same payloads the logger emits, carrying `familiarity` + `salience`)
and emits `insight` events when a valuable change is detected. The engine MUST be
hermetic and testable without a real environment (inject observations + clock),
MUST bound its state (rolling windows), MUST NOT raise on a malformed payload,
and MUST ignore `insight`-type payloads so it never feeds on its own output. Each
insight code SHALL have a cooldown so a sustained condition fires once per window
rather than once per observation.

#### Scenario: A cluster of unfamiliar arrivals fires an insight
- **WHEN** at least the cluster-minimum number of `first_time` arrivals are observed within the cluster window
- **THEN** the engine emits a `new_device_cluster` insight whose detail reports the count

#### Scenario: Familiar arrivals do not cluster
- **WHEN** the only arrivals observed carry `familiarity` `habitual`
- **THEN** no `new_device_cluster` insight is emitted

#### Scenario: A sustained condition fires once per cooldown
- **WHEN** a detector's trigger condition holds across many consecutive observations within one cooldown window
- **THEN** the engine emits at most one insight for that code in that window

#### Scenario: Malformed observation is ignored
- **WHEN** a payload missing expected fields is observed
- **THEN** the engine does not raise and emits nothing for it

### Requirement: The engine SHALL live-ify the live-able analyzer heuristics
The engine SHALL evaluate, on a rolling window, the live-able subset of the
offline `analyze.py` heuristics — at minimum `repeated_disassociates`,
`loss_observed`, `latency_without_loss`, and `band_steering` — emitting an
insight with the corresponding `code` and a `severity` consistent with the
analyzer's (`warn` for repeated disassociates / loss, `note` for latency
without loss, `info` for band steering). Offline-only heuristics (whole-log
timezone-mismatch, short-window, stale-latency-after-roam) are out of scope and
remain in `analyze.py`.

#### Scenario: Repeated disassociations within the window warn
- **WHEN** three or more `link_state` disassociations are observed within the rolling window
- **THEN** the engine emits a `repeated_disassociates` insight with `severity` `warn`

#### Scenario: Latency spikes without loss are a note, not a warning
- **WHEN** a `latency_spike` is observed within the window and no `loss_burst` is present
- **THEN** the engine emits a `latency_without_loss` insight with `severity` `note`

### Requirement: Insight events SHALL be desktop-local this phase
Insight events SHALL surface on the desktop — the JSONL log, the TUI Events ring,
and (for `note`/`warn` severity) a macOS notification — but SHALL NOT be
forwarded to the companion phone in this phase (they are not part of the
companion push set). Forwarding insights across the wire is a deferred,
version-coordinated `companion-protocol` change.

#### Scenario: Insight is not forwarded to the companion
- **WHEN** an `insight` event is emitted while companion forwarding is active
- **THEN** the companion sink does not forward it (its type is not push-worthy)

### Requirement: A critical severity SHALL rank above warn for threats
The insight severity scale SHALL include `critical`, above `warn`, reserved for
threat-class insights. A `critical` insight SHALL map to `high` salience, SHALL
always raise a notification when `--notify` is set, and SHALL render as a
distinct `[THREAT]` row rather than `[INSIGHT]`. It otherwise reuses the
`insight` event type + engine plumbing unchanged.

#### Scenario: Critical maps to high salience
- **WHEN** a `critical`-severity insight is emitted
- **THEN** its stamped salience is `high`

#### Scenario: Critical renders as a threat row
- **WHEN** a `critical`-severity insight is rendered in the Events panel / modal
- **THEN** the row is labelled `[THREAT]`

