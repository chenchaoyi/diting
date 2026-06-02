# ble-decoders — delta

## ADDED Requirements

### Requirement: A generic recogniser SHALL surface manufacturer data for vendors without a dedicated decoder
The decoder package SHALL ship a `manufacturer` decoder that runs for any
device carrying a company-id NOT owned by one of the dedicated decoders
(Apple / Microsoft / Xiaomi-Huami / Ruuvi). It SHALL emit `mfg.cid` (the
company-id), `mfg.vendor` (the resolved vendor name, when known),
`mfg.body_hex` (the bytes after the company-id prefix), and `mfg.body_len`.
It SHALL abstain on a missing, invalid, or company-id-only (no body)
manufacturer payload, and SHALL NOT assign a `device_type` or `device_class`
from the company-id — a chip- or module-vendor id does not identify a product,
so that would be a fabricated semantic claim.

#### Scenario: Long-tail vendor advert is surfaced, not blank
- **WHEN** a device advertises manufacturer data under a company-id with no dedicated decoder (e.g. Polar / Telink / Honor)
- **THEN** `decode_all` returns `mfg.cid` + `mfg.body_hex` (+ `mfg.vendor` when resolved), and emits no `device_type` / `device_class`

#### Scenario: Dedicated-decoder vendors are not double-emitted
- **WHEN** the company-id belongs to a dedicated decoder (Apple / Microsoft / Xiaomi-Huami / Ruuvi)
- **THEN** the generic recogniser abstains, leaving only that decoder's protocol-namespaced fields
