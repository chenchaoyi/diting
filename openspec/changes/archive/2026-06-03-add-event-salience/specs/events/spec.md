# events — delta

## ADDED Requirements

### Requirement: Events SHALL support an optional salience tier
Emitted events SHALL support an optional `salience` field — one of `noise` /
`low` / `notable` / `high` — describing how attention-worthy the event is,
derived by the `salience` scorer from the event's type, its `familiarity` class,
and signal strength. The field is OPTIONAL: when the scorer abstains for a type
the event SHALL omit it entirely (not `null`), so the JSONL key set stays stable
for consumers that ignore it. Salience is desktop-local in this phase and SHALL
NOT cross the companion wire.

#### Scenario: A scored event carries its tier
- **WHEN** a `ble_device_seen` for a `first_time` device is emitted to a file sink
- **THEN** the JSONL line carries a `salience` field

#### Scenario: An unscored event omits the field
- **WHEN** a `session_meta` line is emitted
- **THEN** it carries no `salience` key
