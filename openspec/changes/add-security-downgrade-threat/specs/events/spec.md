# events — delta

## ADDED Requirements

### Requirement: Associated link_state SHALL carry a desktop-local security cipher
An `associated` `link_state` event SHALL carry the connection cipher as an
optional desktop-local `security` field (from `conn.security`), present in the
JSONL log but NOT part of the `link_state` companion-protocol wire vocabulary —
it is stripped before sealing (it is a local-only field). It feeds the
`security_downgrade` threat detector. When the cipher is unknown the field is
omitted.

#### Scenario: Associated link_state logs the cipher
- **WHEN** the connection updates to associated with a known security cipher
- **THEN** the JSONL `link_state` line carries a `security` field

#### Scenario: Security never crosses the wire
- **WHEN** an associated `link_state` carrying `security` is forwarded to the companion
- **THEN** the sealed envelope's plaintext omits `security` (it is a local-only field), leaving only the `link_state` wire vocabulary
