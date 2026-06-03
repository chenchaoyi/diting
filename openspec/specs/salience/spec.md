# salience Specification

## Purpose
TBD - created by archiving change add-event-salience. Update Purpose after archive.
## Requirements
### Requirement: A pure salience scorer SHALL rank an event by attention-worthiness
The system SHALL provide a pure, stateless `salience(payload)` function that
MUST return one of the ordered tiers `noise` < `low` < `notable` < `high`, or
`None` for event types it does not score (e.g. `session_meta`). It reads only
the wire payload — `type`, the Phase-1 `familiarity` class, and authoritative
signal fields (`rssi_dbm`, `loss_pct`, `confidence`, `state`, `kind`) — and
MUST NOT read user-controllable display names (Bonjour name, hostname). It MUST
NOT raise on a malformed or partial payload; an unrecognised shape abstains
(returns `None`).

#### Scenario: Habitual arrival is noise
- **WHEN** a `ble_device_seen` carries `familiarity` `habitual`
- **THEN** its salience is `noise`

#### Scenario: First-time arrival is notable
- **WHEN** a `lan_host_seen` carries `familiarity` `first_time`
- **THEN** its salience is `notable`

#### Scenario: Close first-time BLE device is high
- **WHEN** a `ble_device_seen` carries `familiarity` `first_time` and `rssi_dbm` >= -60
- **THEN** its salience is `high`

#### Scenario: Anomalies are salient regardless of familiarity
- **WHEN** a `loss_burst` event is scored
- **THEN** its salience is `high`, with no familiarity input required

#### Scenario: Absent familiarity never invents noise
- **WHEN** an arrival event carries no `familiarity` field
- **THEN** its salience is at least `low` (never `noise`), preserving pre-store behaviour

#### Scenario: Unscored type abstains
- **WHEN** a `session_meta` payload is scored
- **THEN** the function returns `None`

### Requirement: Salience SHALL be stamped onto emitted events
The `EventLogger` SHALL stamp the computed salience tier onto every emitted
payload as an optional `salience` field, centrally, downstream of the
`familiarity` stamp. When the scorer abstains (`None`) the field MUST be omitted
entirely (consistent with the None-fields-omitted rule), keeping the JSONL key
set stable for consumers that ignore it.

#### Scenario: Scored event carries salience in JSONL
- **WHEN** a `loss_burst` is emitted to a file sink
- **THEN** the JSONL line carries `"salience":"high"`

#### Scenario: Unscored event omits the field
- **WHEN** a `session_meta` line is emitted
- **THEN** it carries no `salience` key

