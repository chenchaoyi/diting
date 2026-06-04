# Extend the BLE familiarity identity to service-data + vendor-group

## Why

A real 18-hour office capture showed **76% of `ble_device_seen` events get no
familiarity class at all** — 2,394 of 3,127, concentrated in the most common
real devices (Anhui Huami 1,479, Huawei 612, Xiaomi, Honor). Root cause: the
familiarity key for BLE only considers `manufacturer_hex` / `vendor_id` /
`name`, but a huge device class — Mi Band / Amazfit / Huami / Huawei wearables —
advertises via **service-data** (e.g. MiBeacon `FE95`), carrying NO manufacturer
payload, NO name, and a rotating UUID. They are confidently attributed to a
vendor (via the service-data UUID / member-UUID), yet `familiarity_key` returns
`None`, so the entire familiarity → salience → cluster layer is blind to them.
This also feeds the `new_device_cluster` over-firing (they never settle into
`habitual`).

## What Changes

Extend the BLE familiarity-key ladder with two new rungs (highest identity
first), keeping the existing two unchanged:

1. `ble:<manufacturer_hex>` — manufacturer payload (unchanged).
2. **(B, new)** `ble:sd:<service_data_id>` — a per-device id decoded from a
   known service-data schema. First schema: **MiBeacon `FE95`** — when the
   frame-control `MAC included` bit is set, the embedded six-byte MAC is the
   device's real address, stable across UUID rotation. Implemented as
   `ble.service_data_identity()`; carried on the BLE seen/left events as an
   in-memory `service_data_id` (not serialised), like `manufacturer_hex`.
3. `ble:vn:<vendor_id>/<name>` — the (company-id, name) fallback (unchanged).
4. **(A, new)** `ble:vg:<vendor>` — a coarse vendor GROUP, the last resort when
   a device was authoritatively attributed to a manufacturer (OUI / SIG
   company-id / member-UUID / service-data UUID) but offers none of the
   per-device tokens above. Folds that vendor's payload-less, rotating devices
   into one ambient group instead of leaving them unclassified. It is recurrence
   grouping, never a per-device or trust claim.

## Impact

- Affected specs: `familiarity-store` (the BLE key ladder gains the service-data
  + vendor-group rungs).
- Affected code: `ble.py` (`service_data_identity()` MiBeacon parser + populate
  `service_data_id` at the four seen/left construction sites); `events.py`
  (in-memory `service_data_id` on the BLE seen/left events); `event_log.py`
  (pass `service_data_id` + `vendor` into `familiarity_key`); `familiarity.py`
  (the two new key rungs). New explainer `docs/explainers/ble-identity.md`
  (EN+ZH) documenting the ladder.
- **Scope limit:** (B) covers the MiBeacon `FE95` schema only (the dominant
  Xiaomi/Huami ecosystem); other service-data schemas fall to (A) vendor-group
  until a parser is added. This extends the FAMILIARITY key only — it does not
  change the display payload-fusion / cluster merger (the JSONL still records
  one seen/left per rotation), so the log churn itself is unchanged; what
  changes is that those events now carry a familiarity class (→ salience can
  rank them, → habitual groups stop reading first_time).
- No name-based classification: every new rung keys on authoritative signal
  (service-data MAC, OUI/UUID/company-id-derived vendor), never a display name.
  The vendor-group rung is coarse recurrence grouping, not identity/trust.
