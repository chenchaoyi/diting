# ble-detail-modal Specification

## Purpose

Defines the per-device inspect modal — the user picks a row in the
BLE list (keyboard or mouse), opens the modal, and sees every field
diting has on that device plus the decoded payload. This is the
primary "go deep on one peripheral" surface of the tool; future
features (RSSI history charts, sensor dashboards, beacon URL launch)
extend it rather than replacing it.
## Requirements
### Requirement: BLE list rows SHALL be selectable by identifier, stable across snapshots
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

### Requirement: Keyboard navigation SHALL bind `up` / `down` / `enter` / `i` and SHALL win over scroll
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

### Requirement: Mouse click on a BLE row SHALL select-and-inspect in one gesture
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

### Requirement: The modal SHALL render every `BLEDevice` field plus decoded payload
The BLE detail modal SHALL surface, in order:

1. **Identity** — name, vendor (alias + CID), type, device class, identifier (BLE address or RPA), flags (connectable / connected).
2. **Signal** — RSSI (raw + smoothed), tx power, RSSI sparkline + min..max window.
3. **Activity** — first seen, last seen, ad count + inter-ad interval, merged-RPA count.
4. **Services** — list of service UUIDs with `service_category` resolution.
5. **Decoded payload** — Apple Proximity / Continuity / Nordic-UART / Eddystone fields parsed by the decoder registry.
6. **Manufacturer data** — CID lookup + hex-formatted raw bytes.
7. **Extra UUID lists** — solicited / overflow service UUIDs.

Sections with no data SHALL render a dim-italic placeholder line as a single self-contained line, NOT through the `_label(name, None)` helper. The `_label` helper appends an em-dash for "no value" — using it for placeholder strings produces a misleading "(none …)—" suffix. Affected sections: Services, Extra UUID lists, any other "other services on this host" / "no manufacturer data" placeholder text inside a section.

#### Scenario: iPhone Nearby Info row
- **WHEN** the user opens the modal on an iPhone advertising Apple Nearby Info (manufacturer data prefix `0x4c 0x00 0x10 …`)
- **THEN** the Decoded payload section shows the nearby_info fields (action_code_hi, appleid_hash, class_byte_hex, device_class_lo, flags_lo, os_hint_hi, status_hex)

#### Scenario: Connected Magic Keyboard row
- **WHEN** the user opens the modal on a connected peripheral with no advertising payload
- **THEN** the Identity section flag list contains `connected`; the Activity section omits ad_count; Services lists the connected GATT services

#### Scenario: Services section with zero advertised services
- **WHEN** the device advertises no service UUIDs (typical for an iPhone publishing only Nearby Info)
- **THEN** the Services section header renders, followed by a single dim-italic line `(none advertised)` with the same 2-space indent as the label rows — and NO trailing em-dash, NO em-dash on its own line

#### Scenario: Extra UUID lists with no solicited or overflow UUIDs
- **WHEN** the device advertises no solicited and no overflow service UUIDs
- **THEN** the Extra UUID lists section renders a single dim-italic line `(none)` (or equivalent placeholder) — no trailing em-dash, no `_label`-with-None artefact

### Requirement: The Activity section SHALL hide ad_count for connected peripherals
The Activity section SHALL omit the `ad count` row entirely for
connected peripherals, since connected entries come from
`IOBluetoothDevice.pairedDevices()` rather than the advertisement
callback and their `ad_count` is always 0. Rendering "ad count: 0"
for a Magic Keyboard reads as a bug to the user.

#### Scenario: Modal on Magic Keyboard
- **WHEN** the user inspects a connected peripheral
- **THEN** the Activity section shows `first seen` and `last seen` only — no `ad count` row

### Requirement: The Signal section SHALL render an RSSI sparkline when ≥ 2 history samples exist
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

### Requirement: Modal close SHALL be Esc / `i` / `q`, and SHALL NOT mutate selection
The modal SHALL bind `escape`, `i`, and `q` to close. Closing SHALL
NOT clear `_ble_selected_id` — the user expects the highlighted row
to remain highlighted after they read the detail. Reopening with `i`
without other key presses SHALL show the same device.

#### Scenario: User opens modal, reads, closes, reopens
- **WHEN** the user presses `i` → reads → Esc → `i`
- **THEN** the second `i` opens the modal for the same device, no cursor walk required

### Requirement: Distance estimate SHALL be labelled as a rough free-space estimate
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

