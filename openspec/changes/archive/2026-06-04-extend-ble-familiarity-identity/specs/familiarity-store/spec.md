# familiarity-store — delta

## MODIFIED Requirements

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
