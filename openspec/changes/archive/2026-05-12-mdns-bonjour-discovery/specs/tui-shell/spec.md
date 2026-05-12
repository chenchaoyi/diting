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
→ `wifi`, in that order. The footer label for `n` SHALL be
`next view` / `下个视图` to reflect the cyclic nature; the literal
`→ BLE` from the prior 2-way design is removed.

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

### Requirement: Diagnostics panel content SHALL follow the active view
`_refresh_environment_panel()` SHALL render Wi-Fi-side diagnostic
content (visible BSSIDs, things-to-notice, link, environment) when
the view is `wifi`, BLE-side content (visible BLE / vendors /
categories / closest / connected) when the view is `ble`, and
mDNS-side content (visible Bonjour / top services / top vendors)
when the view is `mdns`. The panel SHALL refresh both on view-toggle
AND on each event for the active view.

#### Scenario: BLE view, BLE event arrives
- **WHEN** the user is in BLE view and a fresh BLE snapshot lands
- **THEN** the diagnostics panel re-renders with the new BLE-side stats

#### Scenario: mDNS view, Bonjour snapshot lands
- **WHEN** the user is in mDNS view and a fresh `BonjourScanUpdate` snapshot lands
- **THEN** the diagnostics panel re-renders with the new mDNS-side stats (visible Bonjour count, top services, top vendors)

#### Scenario: Wi-Fi view ignores mDNS updates
- **WHEN** the user is in Wi-Fi view and a fresh `BonjourScanUpdate` snapshot lands
- **THEN** the diagnostics panel does NOT re-render (the snapshot is held for when the user toggles back)
