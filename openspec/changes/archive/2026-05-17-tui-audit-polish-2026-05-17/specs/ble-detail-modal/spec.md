## MODIFIED Requirements

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
