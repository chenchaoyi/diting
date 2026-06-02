# events — delta

## ADDED Requirements

### Requirement: Seen-side transition events SHALL support an optional familiarity class
Seen-side transition events SHALL support an optional `familiarity` field — one
of `first_time` / `occasional` / `habitual` / `returning` — on `ble_device_seen`,
`bonjour_service_seen`, `lan_host_seen`, and `roam`, describing how familiar the
entity is, derived from the `familiarity-store`. The field is OPTIONAL: when no
familiarity store is wired the events SHALL omit it entirely
(consistent with the None-fields-omitted rule), so the JSONL key set stays
stable for consumers that ignore it. The class for a seen event SHALL reflect
the entity's familiarity BEFORE the current sighting is recorded, so a
never-before-seen entity reads `first_time`.

#### Scenario: First-ever sighting is first_time
- **WHEN** an entity with no prior familiarity record emits a `seen` event with a store wired
- **THEN** the event's `familiarity` is `first_time`

#### Scenario: Field omitted without a store
- **WHEN** no familiarity store is configured
- **THEN** seen events serialise with no `familiarity` key at all (not `null`)

#### Scenario: Roam carries AP familiarity
- **WHEN** a `roam` to a BSSID occurs with a store wired
- **THEN** the event's `familiarity` reflects how familiar that AP (`ap:<bssid>`) is
