# familiarity-store — delta

## ADDED Requirements

### Requirement: The familiarity store SHALL key entities by stable, authoritative identity
The store SHALL key each entity by a stable, non-spoofable identity, never a
user-controllable name: BLE by its payload-fusion token (`manufacturer_hex` for
non-Apple, falling back to `(vendor_id, name)` only when no usable payload
exists) and NEVER the rotating UUID; Wi-Fi APs by BSSID; LAN hosts by MAC;
Bonjour by announced service identity. Records SHALL carry first-seen-ever,
last-seen, total sightings, the set of distinct days seen, and a typical dwell
estimate.

#### Scenario: BLE keyed by payload, not rotating UUID
- **WHEN** the same physical BLE device is observed under two rotated UUIDs with the same manufacturer payload
- **THEN** both update one familiarity record (keyed by the payload), not two

#### Scenario: Name is never the key
- **WHEN** a Bonjour service or BLE device carries a display name
- **THEN** the familiarity key is the service identity / payload / address — the spoofable name is not used as the key

### Requirement: The store SHALL derive a familiarity class from observation history
On a sighting the store SHALL classify the entity as `first_time` (no prior
record), `habitual` (seen across at least a threshold of distinct days),
`returning` (was habitual and absent beyond a gap threshold, now seen again),
or `occasional` (seen before but not yet habitual), classifying against the
state BEFORE the current sighting is folded in. Thresholds SHALL be fixed,
documented defaults.

#### Scenario: Habitual after repeated days
- **WHEN** an entity has been seen on at least the habitual day-count threshold of distinct days
- **THEN** its class is `habitual`

#### Scenario: Returning after a long absence
- **WHEN** a previously-habitual entity is seen again after more than the returning-gap threshold of absence
- **THEN** its class is `returning`

### Requirement: The store SHALL persist, stay bounded, and read fail-soft
The store SHALL persist across sessions to a git-ignored local file (default
path with an env override), updated in memory and flushed periodically and on
clean shutdown. Reading SHALL be fail-soft — a corrupt file or record is skipped,
never raising. The store SHALL be bounded: capped at a maximum entity count and
aging out entities unseen beyond a retention threshold, so it cannot grow
without limit. It SHALL be constructible with an injected path for hermetic
testing without a real environment.

#### Scenario: Corrupt record is skipped
- **WHEN** the store file contains a malformed record among valid ones
- **THEN** the load returns the valid records and skips the corrupt one without throwing

#### Scenario: Aged-out and capped
- **WHEN** entities have not been seen beyond the retention threshold, or the count exceeds the cap
- **THEN** the persisted store drops the stalest entities to stay within bounds
