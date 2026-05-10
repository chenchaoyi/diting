## MODIFIED Requirements

### Requirement: BLE history SHALL be tracked per-device, capped, and pruned on snapshot churn
Per-device RSSI history SHALL accumulate across scan snapshots in a
separate `BLEHistory` container. Each device's buffer SHALL be capped
(default 60 samples ≈ 2 min of history at 2 s polling). Devices that
fall out of a snapshot SHALL be pruned via `expire(keep_ids)` so a
busy environment churning through random-MAC iPhones cannot leak
history forever.

#### Scenario: Long session with rotating identifiers
- **WHEN** the user runs diting in a busy office for 8 hours with iPhones cycling through 1000 distinct random MACs
- **THEN** `BLEHistory` holds at most ~300 deques (corresponding to currently-visible devices), not 1000

#### Scenario: Connected peripheral
- **WHEN** the snapshot includes a connected Magic Keyboard with `rssi_dbm=None`
- **THEN** `BLEHistory.record` skips the sample silently — no None-tagged entries enter the buffer
