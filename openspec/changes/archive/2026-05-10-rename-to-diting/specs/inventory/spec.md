## MODIFIED Requirements

### Requirement: aps.yaml SHALL be optional; the tool SHALL run without it
`load_inventory(path=None)` SHALL return a valid empty
`NetworkInventory` when the file is missing. The tool SHALL fall
back to cluster-label-only attribution. SHALL NOT crash, SHALL NOT
prompt the user.

#### Scenario: First-time user, no aps.yaml
- **WHEN** the user runs diting without ever creating `aps.yaml`
- **THEN** the panel renders cluster labels (`?ab`, `?cd`, ...) for every BSSID and the tool functions normally

### Requirement: Inventory SHALL ALSO carry the Wi-Fi-OUI-vendor map
`load_wifi_ouis` SHALL load `src/diting/data/wifi_ouis.json` (the
curated subset of the IEEE OUI registry plus common Apple BT MAC
ranges) and `lookup_ap_vendor(bssid)` SHALL return the vendor name
for a BSSID's OUI prefix. This is what feeds the Connection panel's
"AP vendor" surface and the BLE detail-modal connected-peripheral
vendor resolution.

#### Scenario: Apple Magic Keyboard
- **WHEN** the BSSID/MAC starts with `38:09:fb`
- **THEN** `lookup_ap_vendor` returns `"Apple"`

#### Scenario: Unknown OUI
- **WHEN** the BSSID/MAC starts with an OUI not in the curated subset
- **THEN** `lookup_ap_vendor` returns None — caller is responsible for the unknown placeholder

### Requirement: Cluster labels SHALL be stable across sessions for the same physical AP
`cluster_label(bssid)` SHALL hash only the last three octets so the
same physical AP produces the same cluster label across reboots,
across rotating per-radio BSSIDs that share the management-MAC
prefix, and across re-runs of the tool. SHALL NOT include
session-specific salt.

#### Scenario: Same AP, two sessions
- **WHEN** the user runs diting today and again tomorrow against the same AP at `aa:bb:cc:de:ad:be`
- **THEN** the cluster label is identical in both sessions (`?be`)
