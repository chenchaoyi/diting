# companion-protocol — delta

## ADDED Requirements

### Requirement: The insight event type SHALL be part of the wire vocabulary at v2
The `companion-protocol` event vocabulary SHALL include the `insight` event:
required `code` (string) and `severity` (enum `info` / `note` / `warn` /
`critical`), plus an optional `detail` object. `detail` SHALL be a nested JSON
object whose inner keys are not strictly validated (they vary by `code`), while
the envelope's top-level keys remain strict. Introducing this type bumps
`PROTOCOL_VERSION` to `2`; a build that understands v2 SHALL list both `1` and
`2` as supported. The vendored `event.schema.json` + golden fixtures regenerate
to include the type.

#### Scenario: An insight event validates
- **WHEN** an `insight` payload with `code`, `severity`, and a nested `detail` object is validated against the v2 schema
- **THEN** it is accepted, and unknown inner `detail` keys do not fail validation

#### Scenario: A strict v1 consumer rejects the unknown type
- **WHEN** a consumer that supports only v1 attempts to decode an `insight` event object
- **THEN** it does not render it as a known type (the type is gated behind v2)

### Requirement: Envelopes SHALL be stamped at the contained event's minimum version
Each envelope's protocol version SHALL be the minimum version that can decode
its event — every event type defined at v1 stays stamped `v1`, and only the
v2-introduced `insight` type is stamped `v2`. A consumer that supports only v1
SHALL therefore continue to accept every existing event (still `v1` envelopes)
and abstain only on the `v2` insight envelopes, rather than being blinded to all
traffic. A v2 consumer decodes both.

#### Scenario: Existing events stay v1 for old consumers
- **WHEN** a v2 producer seals a `ble_device_seen` and a v1-only consumer pulls it
- **THEN** the envelope is stamped `v1` and the consumer decodes it normally

#### Scenario: Insight envelopes are v2 and old consumers skip only those
- **WHEN** a v2 producer seals an `insight` and a v1-only consumer pulls it
- **THEN** the envelope is stamped `v2`, the consumer abstains on it without crashing or dropping its cursor, and continues processing the v1 envelopes around it
