# ble-decoders Specification

## Purpose

Defines the contract for the per-protocol decoder framework that turns
`BLEDevice.manufacturer_hex` / `service_data` raw bytes into structured,
human-readable fields. The detail modal consumes the decoded output;
future per-protocol UI views (sensor dashboards, beacon URL launchers)
will consume the same surface. Decoders are extension points, not
consumers — adding a new vendor-specific decoder MUST NOT touch the
modal.

## Requirements

### Requirement: Decoders SHALL be registered functions taking a `BLEDevice` and returning a dict
Each decoder SHALL be a callable with the signature
`decode(d: BLEDevice) -> dict[str, Any] | None` and SHALL register
itself via the `@register` decorator at import time. The registry
is a flat module-global list; order of registration determines order
of execution but the framework SHALL NOT depend on order for
correctness — multiple decoders on the same device produce a
key-merged dict.

#### Scenario: Adding a new decoder
- **WHEN** a contributor creates `src/wifiscope/decoders/foo.py` with `@register def decode(d): ...`
- **THEN** importing the package picks up `foo.py` and `decode_all` includes its output

### Requirement: Decoders SHALL never raise on malformed input
A decoder receiving a `BLEDevice` with truncated or junk bytes SHALL
return `None` (or an empty dict), NEVER raise. The framework's
`decode_all` catches exceptions defensively as a backstop, but
decoders SHALL be written defensively — exception-as-flow is a bug,
not a feature.

#### Scenario: Truncated iBeacon payload
- **WHEN** `manufacturer_hex` length is 8 bytes (less than the iBeacon-required 25)
- **THEN** `ibeacon.decode` returns `None`, no exception propagates

#### Scenario: Decoder bug raises
- **WHEN** a buggy decoder raises ValueError on an edge case
- **THEN** `decode_all` swallows the exception and continues with the remaining decoders; the rest of the modal renders normally

### Requirement: Output keys SHALL be protocol-namespaced
Every key in a decoder's output dict SHALL be prefixed with the
protocol name and a dot: `ibeacon.uuid`, `eddystone.url`,
`nearby_info.status_hex`, `swift_pair.model`, `ruuvi.temperature_c`,
etc. The detail modal groups output by prefix when rendering.

#### Scenario: Two decoders fire on the same device
- **WHEN** an Apple advertisement chains Handoff + Nearby Info subtypes
- **THEN** the merged dict has both `handoff.activity_id=...` and `nearby_info.status_hex=...`, and the modal renders them under separate sub-headings

### Requirement: Bundled decoders SHALL cover the public-spec protocols seen in real environments
The decoder package SHALL ship at least:

- `ibeacon` — Apple iBeacon (manufacturer-data type 0x02 0x15) →
  UUID, major, minor, tx_power
- `eddystone` — Google Eddystone (FEAA service-data) → frame
  (UID/URL/TLM/EID), URL expansion, namespace+instance, battery /
  temp / ad_count / uptime
- `apple_continuity` — Apple Continuity subtypes (Nearby Info 0x10,
  Find My 0x12, Handoff 0x0C) → status / class / appleid_hash /
  clipboard / activity_id; SHALL chain-walk multiple subtypes in
  one packet
- `microsoft_cdp` — Microsoft CDP (subtype 0x01 device beacon) +
  Swift Pair (0x03/0x05/0x06/0x08) → device_type / version / flags /
  salt / device_hash; Swift Pair extracts the UTF-8 model name
- `ruuvi` — RuuviTag Format 5 (cid 0x0499 + format byte 0x05) →
  temperature, humidity, pressure, accel, battery, tx_power,
  movement, seq, MAC

These five MUST stay registered and discoverable; removing one MUST
go through a REMOVED Requirement on this capability.

#### Scenario: iBeacon broadcast
- **WHEN** an iBeacon advertises UUID 550e8400-..., major 1, minor 42, tx_power -59
- **THEN** decode_all returns `{ibeacon.uuid: "550e8400-...", ibeacon.major: 1, ibeacon.minor: 42, ibeacon.tx_power: -59}`

#### Scenario: Xiaomi MiBeacon temperature broadcast
- **WHEN** a Mi Smart Sensor broadcasts `service_data={"FE95": "..."}`
- **THEN** the bundled decoders abstain (Xiaomi MiBeacon decoding is not in scope; this is an explicit gap, not a regression). Vendor still resolves to Xiaomi via the lookup chain.

### Requirement: Decoders SHALL NOT claim semantics for bits where public docs disagree
Decoders SHALL surface raw status / flag bytes verbatim with mechanical
labels (`status_hex`, `flags`, etc.) and SHALL NOT claim "bit X = locked"
or similar version-fragile interpretations. Apple Continuity and
Microsoft CDP have several status bytes where community
reverse-engineering writeups disagree on bit semantics, and Apple / MS
change them between iOS / Windows major versions.

#### Scenario: Apple Nearby Info status byte
- **WHEN** an iPhone advertises status byte `0x36`
- **THEN** the decoder emits `nearby_info.status_hex="0x36"`, `nearby_info.action_code_hi=3`, `nearby_info.flags_lo=6` — but does NOT emit `nearby_info.locked=False` or similar interpretation

### Requirement: Decoders SHALL run only when the relevant identifying bytes match
A decoder SHALL gate on the appropriate identifier(s) before
processing: vendor cid for manufacturer-data decoders, service UUID
for service-data decoders, frame-type byte for Eddystone-style
multi-frame protocols. SHALL NOT shotgun-decode every device.

#### Scenario: iBeacon decoder on non-Apple cid
- **WHEN** a Microsoft cid (6) advertisement happens to have bytes shaped like `0215...`
- **THEN** the iBeacon decoder skips (cid != 0x004C), so the modal does not surface a fake iBeacon UUID

#### Scenario: Eddystone decoder on non-FEAA service-data
- **WHEN** a device emits `service_data={"FE95": "..."}` (Xiaomi)
- **THEN** the Eddystone decoder skips (UUID != FEAA)
