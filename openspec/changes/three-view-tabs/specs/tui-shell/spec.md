## MODIFIED Requirements

### Requirement: The TUI SHALL have exactly four stacked panels in a fixed order
`DitingApp.compose()` SHALL yield, top to bottom: Header,
ConnectionPanel (`#conn`), EnvironmentPanel (`#env`), then ONE OF
ScanPanel (`#scan`), BLEPanel (`#ble`), or BonjourPanel (`#mdns`)
depending on view, then EventsPanel (`#roam`), then GroupedFooter
(`#footer`). All three view-toggle panels SHALL be mounted on launch
when their respective subsystems are available; toggling SHALL flip
their `display` attribute, never mount/unmount, so the widget tree
stays stable for tests.

The `n` key binding cycles the view across `wifi` → `ble` → `mdns`
→ `wifi`, in that order.

The active third-slot panel's `border_title` SHALL render an
always-visible three-segment tab indicator listing every view name
in cycle order: `Wi-Fi · BLE · Bonjour`. The active view's label
SHALL be styled bold-cyan and the two inactive labels SHALL be
dimmed, so the user can see from any single screen that three
views exist and which one is active. The panel-specific status
detail (count, sort hint, last-scan timestamp) SHALL move to the
panel's `border_subtitle` (bottom of frame) so no information is
lost.

The footer label for `n` SHALL continue to read the literal name of
the NEXT view in the cycle (e.g., `→ BLE` while in Wi-Fi, `→ Bonjour`
while in BLE, `→ Wi-Fi` while in mDNS) so the user knows where the
next press lands.

#### Scenario: User toggles from Wi-Fi to BLE
- **WHEN** the user is in `wifi` view and presses `n`
- **THEN** ScanPanel.display goes False, BLEPanel.display goes True, BonjourPanel.display stays False; the events strip and connection panel are unchanged

#### Scenario: User toggles from BLE to mDNS
- **WHEN** the user is in `ble` view and presses `n`
- **THEN** BLEPanel.display goes False, BonjourPanel.display goes True, ScanPanel.display stays False

#### Scenario: User toggles from mDNS back to Wi-Fi (cycle wraps)
- **WHEN** the user is in `mdns` view and presses `n`
- **THEN** BonjourPanel.display goes False, ScanPanel.display goes True, BLEPanel.display stays False

#### Scenario: All three panels mounted at launch
- **WHEN** the App composes its widget tree
- **THEN** ScanPanel, BLEPanel, and BonjourPanel are all present in the tree (no widgets are mounted or unmounted during view toggles)

#### Scenario: Tab indicator visible in every view
- **WHEN** the user is in any of `wifi` / `ble` / `mdns` view
- **THEN** the active third-slot panel's `border_title` contains all three view labels (`Wi-Fi`, `BLE`, `Bonjour`) separated by `·`
- **AND** the label matching the active mode is styled distinctly (bold-cyan) while the other two are dimmed

#### Scenario: Panel detail moves to the border subtitle
- **WHEN** the user is in `wifi` view
- **THEN** the panel's `border_subtitle` carries the Wi-Fi-specific detail (`Nearby BSSIDs (N) · sort: AP` or equivalent) and the `border_title` carries the tab indicator
- **AND** the equivalent split applies in BLE view (`border_subtitle` shows `Nearby BLE devices (N)`) and mDNS view (`Nearby Bonjour (N)`)
