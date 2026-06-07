# familiarity-store Specification

## Purpose
TBD - created by archiving change add-familiarity-baseline. Update Purpose after archive.
## Requirements
### Requirement: The familiarity store SHALL key entities by stable, authoritative identity
The store SHALL key each entity by a stable, non-spoofable identity, never a
user-controllable name. BLE uses a ladder, strongest per-device identity first:
the manufacturer payload (`manufacturer_hex`, non-Apple); else a per-device id
decoded from a known service-data schema (e.g. the MAC embedded in a MiBeacon
`FE95` frame); else `(vendor_id, name)`; else — as a last resort when the device
was authoritatively attributed to a manufacturer (via OUI / SIG company-id /
member-UUID / service-data UUID) but carries none of those per-device tokens — a
coarse vendor GROUP key. It SHALL NEVER use the rotating UUID, and the
vendor-group key is recurrence grouping, not a per-device or trust claim. Wi-Fi
APs are keyed by BSSID; LAN hosts by MAC; Bonjour by announced service identity.
Records SHALL carry first-seen-ever, last-seen, total sightings, the set of
distinct days seen, and a typical dwell estimate.

#### Scenario: BLE keyed by payload, not rotating UUID
- **WHEN** the same physical BLE device is observed under two rotated UUIDs with the same manufacturer payload
- **THEN** both update one familiarity record (keyed by the payload), not two

#### Scenario: Service-data device keyed by its embedded per-device id
- **WHEN** a payload-less, name-less device advertising a recognised service-data schema (e.g. MiBeacon `FE95` with the MAC-included bit set) is observed under two rotated UUIDs
- **THEN** both update one familiarity record keyed by the service-data per-device id (the embedded MAC), not two, and not `None`

#### Scenario: Authoritatively-attributed device without a per-device token folds into a vendor group
- **WHEN** a device carries no manufacturer payload, no per-device service-data id, and no name, but was confidently attributed to a vendor
- **THEN** it updates a coarse vendor-group familiarity record (first sighting `first_time`, later ones `habitual`) rather than being left unclassified

#### Scenario: Name is never the key
- **WHEN** a Bonjour service or BLE device carries a display name
- **THEN** the familiarity key is the service identity / payload / service-data id / address / vendor group — the spoofable name is not used as the key

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

The store SHALL tolerate any mix of offset-naive and offset-aware timestamps
across observe, classify, prune, and flush without raising, normalizing naive
values as local time at its boundary (on observe and on read-back), so that
already-persisted naive records heal on load without a migration. Both the
periodic and the shutdown flush SHALL be fail-soft — a store error degrades
the baseline, never the monitor.

#### Scenario: Corrupt record is skipped
- **WHEN** the store file contains a malformed record among valid ones
- **THEN** the load returns the valid records and skips the corrupt one without throwing

#### Scenario: Aged-out and capped
- **WHEN** entities have not been seen beyond the retention threshold, or the count exceeds the cap
- **THEN** the persisted store drops the stalest entities to stay within bounds

#### Scenario: Mixed naive and aware sightings survive a flush
- **WHEN** one entity is observed with an offset-naive timestamp and another with an offset-aware timestamp, and the store is then flushed
- **THEN** the flush completes without raising and both records persist with offset-aware local timestamps

#### Scenario: Persisted naive record heals on load
- **WHEN** the store file contains a record whose `last_seen` is an offset-naive ISO string
- **THEN** loading, classifying against, and pruning that record treat the timestamp as local time without raising

