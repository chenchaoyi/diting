# companion-bridge — delta

## ADDED Requirements

### Requirement: Insight + threat events SHALL be forwarded, salience-gated
The companion sink SHALL forward `insight` events (including the `critical`
threat tier) rather than treating them as desktop-local. Forwarding SHALL ride
the existing salience gate: with the default minimum (`low`), `info`-severity
insights (salience `low`) are dropped while `note` / `warn` / `critical`
(salience `notable` / `high`) forward. The per-(type, target) silence window
SHALL key an insight on its `code`, so distinct insight codes debounce
independently. The existing local-only field strip (`familiarity`, `salience`)
SHALL still apply to insight payloads before sealing.

#### Scenario: A threat is forwarded
- **WHEN** a `critical` `insight` (e.g. `evil_twin`) is offered to the sink while paired
- **THEN** it is sealed and enqueued (its salience `high` clears the gate)

#### Scenario: An info insight is not forwarded
- **WHEN** an `info` `insight` (salience `low`) is offered and the minimum salience is the default
- **THEN** the sink does not forward it

#### Scenario: Distinct insight codes are not coalesced together
- **WHEN** two insights with different `code`s are offered within one silence window
- **THEN** both forward (the window is keyed per code)
