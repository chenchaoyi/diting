# inventory Specification

## Purpose

Defines how wifiscope turns a flat list of BSSIDs into named physical
APs. Most controllers expose only a per-AP "management MAC" (one per
device), but each radio / VAP advertises a different BSSID — derived
from the management MAC by varying the last octet. This module's job
is the derivation, plus loading the user-supplied `aps.yaml` that
maps management MACs to friendly location names.

## Requirements

### Requirement: AP attribution SHALL try four resolution paths in order
For each scanned BSSID, `NetworkInventory.resolve(bssid)` SHALL try
in order:

1. **`radio_overrides`** — explicit BSSID → name from `aps.yaml`.
   Hand-edited overrides always win.
2. **First-five-octet rule** — if a BSSID and a known AP's
   management MAC share their first five octets (last byte differs),
   they are the same physical AP. Returns the AP's name.
3. **Mid-four-octet rule** — fallback for vendors whose radios
   differ by two trailing bytes (some H3C, some Aruba). Match on
   octets 1-4.
4. **Cluster label** — no AP-name match; return a "?" prefix label
   based on the last three octets of the BSSID, so the same physical
   AP at least clusters together in the panel even unnamed.

#### Scenario: Hand-edited override
- **WHEN** `aps.yaml` has `radio_overrides: {"aa:bb:cc:11:22:34": "Kitchen"}` and a scan returns that exact BSSID
- **THEN** resolve returns `"Kitchen"` even if no AP matches octets 1-5

#### Scenario: Standard same-prefix derivation
- **WHEN** `aps.yaml` has `aps: [{name: "1F-bedroom", mgmt: "aa:bb:cc:11:22:53"}]` and scan returns `aa:bb:cc:11:22:5e`
- **THEN** resolve returns `"1F-bedroom"` via the first-five-octet rule

#### Scenario: Unknown AP
- **WHEN** the scan returns `f0:99:b6:de:ad:be` and no AP / override matches
- **THEN** resolve returns a label like `?be`, the panel groups all BSSIDs from that physical AP under that label

### Requirement: aps.yaml SHALL be optional; the tool SHALL run without it
`load_inventory(path=None)` SHALL return a valid empty
`NetworkInventory` when the file is missing. The tool SHALL fall
back to cluster-label-only attribution. SHALL NOT crash, SHALL NOT
prompt the user.

#### Scenario: First-time user, no aps.yaml
- **WHEN** the user runs wifiscope without ever creating `aps.yaml`
- **THEN** the panel renders cluster labels (`?ab`, `?cd`, ...) for every BSSID and the tool functions normally

### Requirement: Inventory SHALL ALSO carry the Wi-Fi-OUI-vendor map
`load_wifi_ouis` SHALL load `src/wifiscope/data/wifi_ouis.json` (the
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
- **WHEN** the user runs wifiscope today and again tomorrow against the same AP at `aa:bb:cc:de:ad:be`
- **THEN** the cluster label is identical in both sessions (`?be`)

### Requirement: BSSID format normalisation SHALL be lowercase colon-separated
`format_bssid` SHALL produce lowercase colon-separated MAC strings
(`aa:bb:cc:dd:ee:ff`). Inventory lookups SHALL be case-insensitive
on the input. The TUI's display strings, the JSONL log, and the
analyzer SHALL all use this canonical form.

#### Scenario: Mixed-case input
- **WHEN** `aps.yaml` has `mgmt: "AA:BB:CC:11:22:53"` and scan returns `aa:bb:cc:11:22:5E`
- **THEN** the lookup matches (case folded on both sides) and the panel renders `aa:bb:cc:11:22:5e`
