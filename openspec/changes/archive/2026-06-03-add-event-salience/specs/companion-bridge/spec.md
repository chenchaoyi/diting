# companion-bridge — delta

## MODIFIED Requirements

### Requirement: Push-worthiness reuses the watchdog gate
The sink SHALL decide which events are worth forwarding by first applying a
salience gate, then reusing the `_watchdog.py` severity thresholds and silence
window. The salience gate SHALL drop any event whose stamped `salience` tier is
below a configurable minimum (default `low`, so only `noise`-tier events such as
habitual arrivals and departures are suppressed); when an event carries no
`salience` field the gate is a no-op pass-through, so unpaired / pre-store push
behaviour is unchanged. After the salience gate, the existing rf_stir-confidence
threshold and the per-(type, target) silence window apply as before, so
low-signal, high-volume events (e.g. routine `ble_device_seen`) still coalesce.

#### Scenario: Habitual arrival is suppressed by salience
- **WHEN** a `ble_device_seen` stamped `salience` `noise` (a habitual device) is offered
- **THEN** it is not forwarded to the companion

#### Scenario: Missing salience does not suppress
- **WHEN** an otherwise push-worthy event carries no `salience` field
- **THEN** the salience gate passes it through to the existing watchdog gates unchanged

#### Scenario: Silenced category is suppressed
- **WHEN** an event arrives within the watchdog silence window for its category
- **THEN** it is coalesced or suppressed rather than producing a separate push

### Requirement: Forwarded events are sealed under the paired key
Before transmission, the sink SHALL serialise the event to its `event-log`
JSONL object and seal it with secretbox under the paired channel key, producing
a `companion-protocol` envelope with the next monotonic sequence number. The
plaintext SHALL never leave the process unencrypted. The sink SHALL strip
desktop-local-only fields — those not part of the `companion-protocol` event
vocabulary, currently `familiarity` and `salience` — from the payload before
sealing, so the wire stays within the validated protocol schema and a strict
consumer does not reject the event. (Carrying these across the wire is a
deferred, version-coordinated change.)

#### Scenario: Egress is always ciphertext
- **WHEN** a push-worthy event is forwarded
- **THEN** the bytes sent to the relay are a sealed envelope, never the JSONL plaintext

#### Scenario: Local-only fields do not cross the wire
- **WHEN** a seen event carrying `familiarity` and `salience` fields is forwarded
- **THEN** the sealed envelope's plaintext omits both, leaving only `companion-protocol` vocabulary fields so the mobile consumer accepts it
