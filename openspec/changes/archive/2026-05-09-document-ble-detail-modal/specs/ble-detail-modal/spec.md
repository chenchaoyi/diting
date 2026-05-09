# ble-detail-modal Specification

## Purpose

Defines the per-device inspect modal — the user picks a row in the
BLE list (keyboard or mouse), opens the modal, and sees every field
wifiscope has on that device plus the decoded payload. This is the
primary "go deep on one peripheral" surface of the tool; future
features (RSSI history charts, sensor dashboards, beacon URL launch)
extend it rather than replacing it.

## Requirements

### ADDED Requirement: BLE list rows SHALL be selectable by identifier, stable across snapshots
The App SHALL track a single `_ble_selected_id: str | None` keyed by
peripheral identifier (NOT row index). Each snapshot's render SHALL
highlight the row whose identifier matches the selection. If the
selected device drops out of the snapshot, the selection SHALL clear
to None — the cursor MUST NOT silently jump to a different physical
device.

#### Scenario: Cursor stable through re-sort
- **WHEN** the user selects an iPhone and a different device's RSSI improves enough to bump it to the top of the list
- **THEN** the highlight stays on the iPhone, even though the iPhone's row index changed

#### Scenario: Selected device leaves the snapshot
- **WHEN** the user selects a device that then stops advertising and gets pruned from the snapshot
- **THEN** the next render clears the selection (no ghost cursor on a row that doesn't exist)

### ADDED Requirement: Keyboard navigation SHALL bind `up` / `down` / `enter` / `i` and SHALL win over scroll
The App SHALL bind `up`/`down` to move selection (priority=True so
they fire before `VerticalScroll`'s built-in scroll handler) and
`enter`/`i` to open the detail modal for the current selection. All
bindings SHALL be no-ops outside the BLE view.

#### Scenario: BLE view, user presses down
- **WHEN** the user is in BLE view and presses ↓
- **THEN** selection moves to the next row, cursor highlight follows, panel does NOT scroll past the bottom

#### Scenario: Wi-Fi view, user presses down
- **WHEN** the user is in Wi-Fi view and presses ↓
- **THEN** the binding fires action_ble_select_next which is a no-op (it only acts in BLE view), and Textual's other handlers see the keypress as if our binding didn't consume it

#### Scenario: First press with no prior selection
- **WHEN** the user has not yet moved the cursor and presses `i`
- **THEN** the modal opens for the first device in the panel order (typically the first connected peripheral, fallback to the strongest advertising row)

### ADDED Requirement: Mouse click on a BLE row SHALL select-and-inspect in one gesture
A click on any data row in the BLE panel SHALL set selection to that
row and open the detail modal in the same gesture. Clicks on header
or spacer rows SHALL be no-ops. Coordinates SHALL be translated via
Textual's `event.get_content_offset(body)` so border / padding /
scroll offset are handled correctly.

#### Scenario: Click on advertising row
- **WHEN** the user clicks on the third advertising row
- **THEN** the row highlight moves there and the detail modal opens for that device

#### Scenario: Click on the section header "Connected (2)"
- **WHEN** the user clicks on the header line
- **THEN** nothing happens (no modal opens, selection unchanged)

### ADDED Requirement: The modal SHALL render every `BLEDevice` field plus decoded payload
The modal layout SHALL be a vertical sequence of sections, in this
order, with sections omitted when their data is absent:

1. **Identity** — name, vendor (with cid in dec/hex), type, device_class,
   identifier, flags (connected / connectable)
2. **Signal** — RSSI (with smoothed value when different), tx_power,
   distance estimate (when both RSSI and tx_power available),
   RSSI history sparkline (when ≥ 2 history samples)
3. **Activity** — first seen, last seen (both as "Xs ago"),
   ad_count + observed inter-ad interval, merged_count when > 1
4. **Services** — list of service UUIDs with `service_category` resolution
5. **Extra UUID lists** — solicited / overflow service UUIDs (when present)
6. **Decoded payload** — output of `decode_all(d)` grouped by
   protocol prefix (only present if any decoder fires)
7. **Manufacturer data** — cid + vendor name + decoded type/device_class
   labels + raw hex dump
8. **Service data** — per-UUID hex dump

#### Scenario: iPhone Nearby Info row
- **WHEN** the user opens the modal on a `ccy iPhone 15 Pro Max` row
- **THEN** all sections render except "Service data" (Apple Nearby Info doesn't use service-data); Decoded payload shows `nearby_info.*` keys

#### Scenario: Connected Magic Keyboard row
- **WHEN** the user opens the modal on a connected peripheral
- **THEN** Signal section shows `—` for RSSI / tx_power (connected peripherals don't expose either), Activity section omits `ad count` (always 0 for connected), Manufacturer / Service data sections are absent

### ADDED Requirement: The Activity section SHALL hide ad_count for connected peripherals
The Activity section SHALL omit the `ad count` row entirely for
connected peripherals, since connected entries come from
`IOBluetoothDevice.pairedDevices()` rather than the advertisement
callback and their `ad_count` is always 0. Rendering "ad count: 0"
for a Magic Keyboard reads as a bug to the user.

#### Scenario: Modal on Magic Keyboard
- **WHEN** the user inspects a connected peripheral
- **THEN** the Activity section shows `first seen` and `last seen` only — no `ad count` row

### ADDED Requirement: The Signal section SHALL render an RSSI sparkline when ≥ 2 history samples exist
The Signal section SHALL render a single-line block-character
sparkline (`▁▂▃▄▅▆▇█`) plus a summary `<sparkline>  hi..lo dBm
(N samples over Ms)` whenever the App's `BLEHistory` has at least
2 samples for the selected device. With 0 or 1 samples the row
SHALL be omitted — a single dot is not a "history" worth drawing.

#### Scenario: Modal opens on a device with 24 samples spanning 48 s
- **WHEN** `BLEHistory.get(ident)` returns 24 entries
- **THEN** the Signal section shows `rssi history    ▃▄▅▆▇█▆▅..  -68..-41 dBm  (24 samples over 48s)`

#### Scenario: Modal opens on a brand-new device with one sample
- **WHEN** the device just appeared and only 1 sample has been recorded
- **THEN** the rssi-history row is absent

### ADDED Requirement: Modal close SHALL be Esc / `i` / `q`, and SHALL NOT mutate selection
The modal SHALL bind `escape`, `i`, and `q` to close. Closing SHALL
NOT clear `_ble_selected_id` — the user expects the highlighted row
to remain highlighted after they read the detail. Reopening with `i`
without other key presses SHALL show the same device.

#### Scenario: User opens modal, reads, closes, reopens
- **WHEN** the user presses `i` → reads → Esc → `i`
- **THEN** the second `i` opens the modal for the same device, no cursor walk required

### ADDED Requirement: Distance estimate SHALL be labelled as a rough free-space estimate
The Signal section's distance row SHALL be derived from
`10 ** ((tx_power - rssi) / 20.0)` and SHALL be labelled "rough
free-space estimate" so users do not interpret the number as an
indoor-corrected metre reading. SHALL NOT show a distance when
`tx_power_dbm` or `rssi_dbm` is absent.

#### Scenario: iPhone broadcasting tx_power=12, RSSI=-41
- **WHEN** the modal renders the Signal section
- **THEN** distance shows `~0.4 m  (rough free-space estimate)`

#### Scenario: Connected peripheral
- **WHEN** the device has `rssi_dbm=None`
- **THEN** distance row is absent
