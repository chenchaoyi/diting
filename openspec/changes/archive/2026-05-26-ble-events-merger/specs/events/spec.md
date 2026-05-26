## ADDED Requirements

### Requirement: BLE transition events SHALL represent physical-device clusters, not raw advertised identifiers
`BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` carried by the unified event ring SHALL each represent a single physical-device cluster's session, not a single privacy-rotated identifier's lifetime. The payload schema is unchanged from prior versions — every field (`timestamp`, `identifier`, `name`, `vendor`, `rssi_dbm` / `last_rssi_dbm`, `service_categories`, `seen_for_seconds`) keeps its existing type and meaning. The semantic shift is that the `identifier` field SHALL carry the cluster's **representative identifier** (the first identifier of the cluster), and the event SHALL fire at most once per cluster lifetime regardless of how many privacy-rotated identifiers the underlying physical device cycled through.

External consumers of the JSONL event log (`diting analyze`, third-party scripts) see fewer events per session in BLE-noisy environments. Each event still carries a real per-host UUID in the `identifier` field, and each `BLEDeviceSeenEvent` still has a matching `BLEDeviceLeftEvent` when the physical device leaves range.

#### Scenario: JSONL consumer sees one seen per physical device
- **WHEN** an external tool runs `jq 'select(.type=="ble_device_seen")' < session.jsonl` against a session where one iPhone rotated through 6 identifiers
- **THEN** the filter yields 1 line, not 6; the `identifier` field is the first identifier that graduated for that cluster; the `vendor` / `name` / `service_categories` fields match what the cluster's representative carries

#### Scenario: JSONL consumer correlates seen and left
- **WHEN** the external tool correlates `ble_device_seen` and `ble_device_left` events by their `identifier` field
- **THEN** every `seen` has exactly one matching `left` with the same identifier (the cluster's representative); the `seen_for_seconds` on the `left` event measures the FULL cluster session, not the last identifier's life

#### Scenario: JSONL line count is bounded by physical-device count, not identifier-rotation count
- **WHEN** a stationary user runs a one-hour session in an office with ~20 physical BLE devices that each rotate identifiers every ~10 minutes
- **THEN** the JSONL log contains on the order of 20 `ble_device_seen` lines (one per device that arrived during the session), not ~120 (20 devices × 6 rotation cycles)

#### Scenario: Per-identifier firehose available via env override
- **WHEN** a user runs diting with `DITING_BLE_EVENT_MERGER=0`
- **THEN** the JSONL log fires one `ble_device_seen` per identifier graduation and one `ble_device_left` per TTL eviction, exactly matching pre-v1.8.0 semantics; external consumers expecting per-identifier granularity continue to work
