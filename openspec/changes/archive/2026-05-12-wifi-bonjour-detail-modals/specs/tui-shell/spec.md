## ADDED Requirements

### Requirement: Each list-style view panel SHALL share the same row-select + inspect gesture contract
The TUI SHALL guarantee that every list-style panel in the third panel slot (Wi-Fi scan list, BLE devices, Bonjour services, and any future analogue) exposes the same input contract to the user. The following bindings MUST behave identically across every such view:

- `up` / `down` move selection within the active view, registered
  priority=True so they fire before `VerticalScroll`'s scroll
  handler.
- `i` and `enter` open a panel-specific detail modal for the
  current selection.
- Mouse click on a data row sets selection to that row AND opens
  the detail modal in the same gesture; clicks on header /
  placeholder / spacer rows are no-ops.
- Modal close binds `escape`, `i`, and `q`; closing does NOT
  mutate the panel's selection state.
- The action methods backing `up` / `down` / `i` / `enter` SHALL
  no-op when the active view does not match the action's panel.
  This keeps the same physical key safe across views (e.g. ↓ in
  Wi-Fi view does not also act on BLE selection state).
- Selection state SHALL be keyed by a stable identifier (BSSID,
  BLE peripheral identifier, Bonjour service-instance FQDN), NOT
  by row index. Selected targets that drop out of the next snapshot
  SHALL clear the selection.

The specific section layout, field set, and behavioural edge cases
for each modal are defined in that panel's capability spec
(`wifi-detail-modal`, `ble-detail-modal`, `bonjour-detail-modal`).
This requirement only pins the cross-cutting input contract.

#### Scenario: User switches views, gesture works identically in each
- **WHEN** the user presses `n` to cycle Wi-Fi → BLE → Bonjour and presses `↓` `↓` `i` in each
- **THEN** in each view the cursor moves down twice and the same row's detail modal opens

#### Scenario: Mouse click in any list view
- **WHEN** the user clicks a data row in any of the three list views
- **THEN** that row gets selected AND its detail modal opens, with no separate keypress needed

#### Scenario: Adding a fourth list panel
- **WHEN** a future change introduces another selectable list panel
- **THEN** that panel inherits the same contract; deviating from the contract requires explicitly modifying this Requirement
