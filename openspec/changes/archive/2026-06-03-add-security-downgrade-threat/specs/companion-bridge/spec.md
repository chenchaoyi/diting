# companion-bridge — delta

## ADDED Requirements

### Requirement: The local-only strip SHALL include the security cipher
The sink's local-only field strip SHALL include `security` (alongside
`familiarity` and `salience`), so the connection cipher stamped on associated
`link_state` events never crosses the companion wire while remaining available
to the desktop threat engine and the JSONL log.

#### Scenario: security is stripped before sealing
- **WHEN** an associated `link_state` carrying a `security` field is forwarded
- **THEN** the sealed envelope's plaintext omits `security`, leaving only `companion-protocol` `link_state` vocabulary fields
