# insights — delta

## ADDED Requirements

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
