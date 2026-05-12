## ADDED Requirements

### Requirement: While the modal is open, `up` / `down` SHALL track selection live
The TUI SHALL advance the underlying BLE selection when the user
presses `up` / `down` while `BLEDetailScreen` is on the screen
stack, AND the modal body MUST re-render to track the new device,
including refreshing the RSSI-history sparkline from
`BLEHistory.get(<new identifier>)`. The user SHALL be able to walk
the BLE list without closing and reopening the modal each time.

#### Scenario: User opens modal on first device, presses ↓
- **WHEN** the modal is open on a connected Magic Keyboard and the user presses ↓
- **THEN** the underlying selection advances to the next BLE row AND the modal body re-renders with that device's identity / signal / activity / decoded payload

#### Scenario: RSSI sparkline refreshes per device
- **WHEN** the user walks from a device with no history (1 sample) to one with 24 samples spanning 48 s
- **THEN** the Signal section's sparkline row appears (omitted for 1-sample, rendered for 24) — the modal does not show stale history from the previous device
