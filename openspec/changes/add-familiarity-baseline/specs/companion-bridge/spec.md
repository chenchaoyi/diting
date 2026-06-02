# companion-bridge — delta

## MODIFIED Requirements

### Requirement: Forwarded events are sealed under the paired key
Before transmission, the sink SHALL serialise the event to its `event-log`
JSONL object and seal it with secretbox under the paired channel key, producing
a `companion-protocol` envelope with the next monotonic sequence number. The
plaintext SHALL never leave the process unencrypted. The sink SHALL strip
desktop-local-only fields — those not part of the `companion-protocol` event
vocabulary, currently `familiarity` — from the payload before sealing, so the
wire stays within the validated protocol schema and a strict consumer does not
reject the event. (Carrying `familiarity` across the wire is a deferred,
version-coordinated change.)

#### Scenario: Egress is always ciphertext
- **WHEN** a push-worthy event is forwarded
- **THEN** the bytes sent to the relay are a sealed envelope, never the JSONL plaintext

#### Scenario: Local-only fields do not cross the wire
- **WHEN** a seen event carrying a `familiarity` field is forwarded
- **THEN** the sealed envelope's plaintext omits `familiarity`, leaving only `companion-protocol` vocabulary fields so the mobile consumer accepts it
