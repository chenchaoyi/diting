## MODIFIED Requirements

### Requirement: The TUI SHALL have exactly four stacked panels in a fixed order
`DitingApp.compose()` SHALL yield, top to bottom: Header,
ConnectionPanel (`#conn`), EnvironmentPanel (`#env`), then EITHER
ScanPanel (`#scan`) OR BLEPanel (`#ble`) depending on view, then
EventsPanel (`#roam`), then GroupedFooter (`#footer`). Both Scan and
BLE panels SHALL be mounted on launch; toggling SHALL flip their
`display` attribute, never mount/unmount, so the widget tree stays
stable for tests.

#### Scenario: User toggles to BLE view
- **WHEN** the user presses `n`
- **THEN** ScanPanel.display goes False, BLEPanel.display goes True, the events strip and connection panel are unchanged

#### Scenario: User toggles back
- **WHEN** the user presses `n` again
- **THEN** ScanPanel.display goes True, BLEPanel.display goes False; no widgets are mounted or unmounted
