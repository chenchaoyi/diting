# bluetooth-scanning Specification

## Purpose

Defines the contract for the BLE scanning layer: how raw advertisements
become `BLEDevice` instances, how vendors get resolved, how rotated
identifiers fold into a single visible row, and what the panel shows
when nothing is identifiable. Sits between `macos-helper` (which emits
the JSONL stream) and `ble-decoders` (which interpret payload bytes).

## Requirements

### Requirement: Each helper JSONL line SHALL produce or update exactly one `BLEDevice`
The Python poller SHALL parse one helper JSONL line per call and merge
it into a `dict[identifier, BLEDevice]` keyed by lowercase
peripheral UUID. A line that lacks an `id` SHALL be silently dropped.
A line for a known `id` SHALL update the prior `BLEDevice` with new
fields, preserving carry-forward fields like `vendor_id` and `name`
when the new line omits them.

#### Scenario: Primary advertisement followed by scan response
- **WHEN** the helper emits two lines for the same `id`, the first carrying `manufacturer_id=76` and the second omitting it
- **THEN** the resulting `BLEDevice` retains `vendor_id=76` from the primary, NOT `None` from the scan response

#### Scenario: Malformed JSON line
- **WHEN** a JSONL line fails JSON parsing
- **THEN** the line is dropped silently and processing continues with the next line

### Requirement: Vendor resolution SHALL run a deterministic chain of fallbacks
For each `BLEDevice`, the vendor SHALL be resolved in this order, with
the first hit winning:

1. `manufacturer_id` → SIG Bluetooth company-ID table (4022 entries)
2. `service_uuids` member-UUID → SIG member-UUID table (703 entries) +
   bundled 128-bit member-UUID supplement (Huami / etc.)
3. `service_data` keys → same member-UUID lookup (covers vendors who
   only emit their UUID inside service-data, not service_uuids)
4. `name` → curated regex pattern table (Magic Keyboard, AirPods,
   Mi Band, Jabra Elite, Polar, Garmin, …)
5. Carry-forward from prior `BLEDevice` for the same `id`

#### Scenario: Apple iPhone Nearby Info
- **WHEN** the advertisement carries `manufacturer_id=76`
- **THEN** vendor resolves to "Apple, Inc." via step 1, and steps 2–5 are not consulted

#### Scenario: Mi Band advertising only on FE95 service-data
- **WHEN** the advertisement omits manufacturer_id, and `service_data` has key FE95
- **THEN** vendor resolves to "Xiaomi Inc." via step 3

#### Scenario: User-renamed Magic Keyboard with no advertisement-side payload
- **WHEN** a connected peripheral has name "ccy's Magic Keyboard" and OUI `38:09:fb`
- **THEN** vendor resolves to "Apple, Inc." via OUI lookup; or via name-pattern step 4 if OUI table misses

### Requirement: Connected peripherals SHALL come through a separate code path
Connected-peripheral lines (`{"connected": true, ...}`) SHALL be
routed through `_build_connected_device`, not `_build_device`.
Connected entries SHALL omit `vendor_id` (always None —
`IOBluetoothDevice` doesn't expose manufacturer-data), SHALL use the
BT MAC's OUI for vendor lookup, and SHALL appear in the panel's
"Connected (N)" section above the "Advertising (N)" section.

#### Scenario: Magic Keyboard paired
- **WHEN** the helper emits a connected snapshot containing the Magic Keyboard's BT MAC
- **THEN** the panel's Connected section shows one row with vendor "Apple, Inc.", no RSSI, services from the OUI heuristic

### Requirement: Rotated-identifier merge SHALL fold privacy-rotated rows
The `merge_for_display` step SHALL fold rows that share
`(vendor_id, name)` within an RSSI tolerance window into one visible
row with a `(merged N)` badge, so the user sees the fuzzy-merge
happening rather than wondering where rotated UUIDs went. Modern
devices rotate their per-host UUID for privacy.

#### Scenario: Same iPhone advertising under 4 rotated UUIDs
- **WHEN** the device map contains 4 entries for the same iPhone, all with vendor_id=76, name="ccy iPhone 15 Pro Max", RSSI within ±10 dB
- **THEN** the panel renders one row with `(merged 4)` and the strongest RSSI

#### Scenario: Truly anonymous beacons
- **WHEN** the device map contains 5 rows with vendor=None, name=None, type=None
- **THEN** the merger does NOT fold them — anonymous rows are kept distinct since fold criteria would be vacuous

### Requirement: The panel SHALL distinguish "(anonymous)" from "(unknown)"
A `BLEDevice` SHALL render its vendor cell as `(anonymous)` when it
has zero usable broadcast data (no manufacturer_id, no service UUIDs,
no name, no type, no device_class), and SHALL render `(unknown)` when
it has SOME data but the vendor lookup chain abstained. The
distinction is user-actionable: `(unknown)` rows can be reported as
decoder gaps; `(anonymous)` rows are physical-data limits with no
fix.

#### Scenario: Silent beacon
- **WHEN** an advertisement carries only RSSI and `is_connectable=true`
- **THEN** vendor cell renders `(anonymous)`

#### Scenario: Vendor-private cid
- **WHEN** an advertisement carries `manufacturer_id=58658` (not in SIG table)
- **THEN** vendor cell renders `(unknown)`, and the row counts toward the inspector's "actionable unresolved" bucket

### Requirement: BLE poller SHALL maintain RSSI smoothing for stable sort order
Each `BLEDevice` SHALL carry an exponentially-smoothed RSSI
(`rssi_smooth`) used as the panel's sort key. The display
(`rssi_dbm` column) SHALL show the live latest reading; sort SHALL
NOT swap row order on a single 5-15 dB packet jitter event. EMA
weight SHALL be α=0.4 — fast enough to react to genuine motion in
~3 advertisements, damped enough to ignore packet jitter.

#### Scenario: Stationary device with packet jitter
- **WHEN** a device alternates between RSSI -65 and -78 dBm on consecutive advertisements
- **THEN** `rssi_smooth` stays in a tight band around -70 and the row does NOT jump up and down the panel

### Requirement: Schema-4 raw fields SHALL be plumbed onto `BLEDevice` for downstream decoders
Each `BLEDevice` SHALL carry, when the helper provides them:
`manufacturer_hex` (full mfg-data bytes including cid prefix),
`service_data` (tuple of `(uuid, hex)` pairs),
`tx_power_dbm`,
`solicited_service_uuids`,
`overflow_service_uuids`.
These fields are the only contract the per-protocol decoder layer
relies on. They SHALL be carried forward across scan-response packets
that omit them.

#### Scenario: Scan response without service_data
- **WHEN** a primary advertisement carries `service_data={"FEAA": "..."}` and a follow-up scan response omits service_data
- **THEN** the resulting `BLEDevice` retains the `("FEAA", "...")` tuple from the primary

### Requirement: BLE history SHALL be tracked per-device, capped, and pruned on snapshot churn
Per-device RSSI history SHALL accumulate across scan snapshots in a
separate `BLEHistory` container. Each device's buffer SHALL be capped
(default 60 samples ≈ 2 min of history at 2 s polling). Devices that
fall out of a snapshot SHALL be pruned via `expire(keep_ids)` so a
busy environment churning through random-MAC iPhones cannot leak
history forever.

#### Scenario: Long session with rotating identifiers
- **WHEN** the user runs wifiscope in a busy office for 8 hours with iPhones cycling through 1000 distinct random MACs
- **THEN** `BLEHistory` holds at most ~300 deques (corresponding to currently-visible devices), not 1000

#### Scenario: Connected peripheral
- **WHEN** the snapshot includes a connected Magic Keyboard with `rssi_dbm=None`
- **THEN** `BLEHistory.record` skips the sample silently — no None-tagged entries enter the buffer
