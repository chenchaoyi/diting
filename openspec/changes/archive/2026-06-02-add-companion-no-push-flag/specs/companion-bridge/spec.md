# companion-bridge — delta

## MODIFIED Requirements

### Requirement: Companion forwarding is opt-in and off by default
diting SHALL NOT send any event off-device until the user has explicitly
paired a companion. With no pairing configured, the event sink SHALL be inert
and no network egress SHALL occur for companion purposes. Even when paired,
forwarding SHALL be suppressible for a single run without unpairing — via the
`DITING_COMPANION=0` environment variable OR the `--no-companion` flag — so the
user can self-test without spamming the paired phone; the self-test capture
harness SHALL force this suppression.

#### Scenario: Unpaired run sends nothing
- **WHEN** diting runs without companion pairing configured
- **THEN** no event is encrypted or transmitted and no relay request is made

#### Scenario: Explicit enable required
- **WHEN** the user has not completed pairing
- **THEN** the `--companion` surface reports "not paired" and offers to start pairing rather than silently activating

#### Scenario: Paired run muted for self-test
- **WHEN** diting runs while paired but with `--no-companion` (or `DITING_COMPANION=0`)
- **THEN** the sink is not built, no event is forwarded to the relay, and the on-disk pairing is left intact
