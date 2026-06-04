# insights — delta

## MODIFIED Requirements

### Requirement: A live insight engine SHALL synthesize valuable-change events
The system SHALL provide an insight engine that observes the enriched event
stream (the same payloads the logger emits, carrying `familiarity` + `salience`)
and emits `insight` events when a valuable change is detected. The engine MUST be
hermetic and testable without a real environment (inject observations + clock),
MUST bound its state (rolling windows), MUST NOT raise on a malformed payload,
and MUST ignore `insight`-type payloads so it never feeds on its own output. Each
insight code SHALL have a cooldown so a sustained condition fires once per window
rather than once per observation. The `new_device_cluster` detector SHALL count
a BLE arrival only when it is physically near (RSSI at or above a near
threshold) — a cluster signals a close influx, not far-field ambient churn — and
SHALL exclude a BLE arrival with no RSSI; non-BLE arrivals (LAN host / Bonjour
service) have no proximity dimension and always count.

#### Scenario: A cluster of nearby unfamiliar arrivals fires an insight
- **WHEN** at least the cluster-minimum number of `first_time` arrivals are observed within the cluster window, the BLE ones near (RSSI ≥ the near threshold)
- **THEN** the engine emits a `new_device_cluster` insight whose detail reports the count

#### Scenario: Far-field BLE arrivals do not cluster
- **WHEN** the only `first_time` arrivals are BLE devices with weak RSSI (below the near threshold) or no RSSI
- **THEN** no `new_device_cluster` insight is emitted

#### Scenario: Familiar arrivals do not cluster
- **WHEN** the only arrivals observed carry `familiarity` `habitual`
- **THEN** no `new_device_cluster` insight is emitted

#### Scenario: A sustained condition fires once per cooldown
- **WHEN** a detector's trigger condition holds across many consecutive observations within one cooldown window
- **THEN** the engine emits at most one insight for that code in that window

#### Scenario: Malformed observation is ignored
- **WHEN** a payload missing expected fields is observed
- **THEN** the engine does not raise and emits nothing for it
