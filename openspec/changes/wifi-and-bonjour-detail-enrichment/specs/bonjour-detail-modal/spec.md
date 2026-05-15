## MODIFIED Requirements

### Requirement: The modal SHALL render every `BonjourDevice` field, grouped into sections, plus context drawn from session state
The modal layout SHALL be a vertical sequence of sections, in this order, with sections omitted when their data is absent:

1. **Identity** — instance name (with the `._<service-type>.local.` suffix stripped, matching list rendering), service type token, service category (i18n-translated when available), vendor. When `BonjourDevice.vendor_trace` is non-`None`, the vendor row SHALL append ` · via <trace>` where `<trace>` is one of `txt-vendor`, `oui`, `hostname-pattern`, `service-type-hint`. The trace annotation SHALL match the styling of the Wi-Fi modal's `(associated)` annotation.
2. **Other services on this host** — when the latest mDNS snapshot contains other `BonjourDevice`s sharing the same `host` (or sharing the same addresses tuple when host is `None`), list those other categories with their `last_seen` age, newest first. Section SHALL be omitted when this host has only the selected service.
3. **Network** — host (with `.local` suffix shown explicitly), port, addresses (full list, IPv4 and IPv6 rendered separately, one per line)
4. **TXT records** — rendered in two parts:
   - **Decoded** — for each TXT key that has a registered decoder under `src/diting/mdns_txt_decoders.py` (or the equivalent path chosen at apply time), the decoded `(label, value)` tuple. Decoders SHALL abstain (return `None`) on malformed input. Decoded keys SHALL NOT also appear in the raw table below.
   - **Raw** — every remaining TXT key/value pair from the `txt` dict, rendered as a 2-column table. Values longer than 60 characters SHALL be folded to `<N-byte payload>` plus the first 32 hex characters of the raw value as a one-line preview.
5. **Cross-surface** — when any of the three correlation rules below match, render a one-line annotation per match:
   - **Local Mac** — when an announced IPv4 / IPv6 address matches the App's `latest_connection.local_ip` or the local Mac's known interface addresses, render `local Mac (this host is you)`.
   - **BLE peripheral** (via TXT `deviceid` MAC) — when a TXT `deviceid` value parses as a MAC and that MAC appears in the BLE poller's snapshot, render `also on BLE as <category | name | vendor> · <RSSI> dBm`.
   - **BLE peripheral** (via hostname pattern) — when the host matches an Apple-name pattern (`_NAME_PATTERN_VENDORS` in `src/diting/ble.py`) AND a nearby BLE row carries the same Apple-Proximity category hint, render `likely the same device as BLE row <short-id>`. The render SHALL include the explicit "likely" hedge because this match is probabilistic.

   Section SHALL be omitted when none of the three rules match.
6. **Activity** — first seen / last seen as "Xs ago"

#### Scenario: Open modal on an AirPlay receiver with 18 TXT keys
- **WHEN** the user inspects a `Living HomePod._raop._tcp` row
- **THEN** every TXT key (`md`, `am`, `vs`, `vn`, `tp`, `pk`, …) renders; the long `pk=` value is folded to `<256-byte payload> 8d4b… (hex)`; the `model` key surfaces as a decoded field in the Decoded sub-section; the raw table contains only keys without registered decoders

#### Scenario: Open modal on a service with no TXT
- **WHEN** the user inspects a row whose `txt` dict is empty
- **THEN** the TXT records section is absent entirely

#### Scenario: Open modal on a service with both IPv4 and IPv6 addresses
- **WHEN** the user inspects a row whose `addresses` tuple contains `192.168.1.42` and `fe80::1c4`
- **THEN** the Network section shows two address rows, IPv4 first

#### Scenario: Open modal on the local Mac's own AirPlay announcement
- **WHEN** the user inspects a row whose announced IPv4 matches `latest_connection.local_ip` (the local Mac's own address)
- **THEN** the Cross-surface section renders `local Mac (this host is you)` and the Other services on this host section lists the Mac's other announcements (e.g. `_companion-link._tcp`, `_raop._tcp`)

#### Scenario: Open modal when vendor was resolved via OUI lookup
- **WHEN** the resolution chain selected the OUI-lookup step for this device
- **THEN** the Identity section's vendor row reads `<vendor>  ·  via oui`

#### Scenario: Open modal on a non-decodable TXT
- **WHEN** the row carries a TXT key whose registered decoder raises (e.g. malformed bitmask)
- **THEN** the decoder abstains, no exception escapes, and the key renders in the raw table only
