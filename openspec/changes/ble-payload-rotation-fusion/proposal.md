# Fuse BLE rotations by manufacturer-payload equality

## Why

An 18-hour event log was 99% BLE seen/left churn: 2714 distinct identifiers,
each seen once and gone ~30s later. Analysis showed these are a small fixed
set (~16) of privacy-rotating wearables (Huami/Amazfit, Huawei) — each MAC
rotation produces a fresh per-host UUID, a fresh single-member cluster, and so
a fresh seen+left pair. The existing rotation merge keys on
`(vendor_id, name, RSSI±10dB, services)`; for anonymous same-vendor devices the
only discriminator is RSSI, and a rotation that drifts the signal past the
window starts a new cluster — under-merging into a flood.

A real-capture analysis found the missing signal: the **manufacturer-data
payload is a stable per-device token** that survives MAC rotation — the same
full payload appears under many rotating UUIDs for one device, and (for every
non-Apple vendor measured) a given payload maps to exactly one device. Apple is
the sole exception: its Continuity status frames are generic (one payload
broadcast by dozens of distinct devices).

## What Changes

- The transition-event cluster merger gains a strong, RSSI-independent fusion
  path: an advert whose non-trivial manufacturer payload exactly equals a
  cluster's anchor payload joins that cluster (= the same physical device
  rotated), regardless of signal.
- Excludes Apple (generic shared payloads), skips header-only/near-empty
  payloads, and caps the concurrently-active members per payload as an
  over-merge backstop for any other generic broadcaster.
- Effect: a rotating wearable fires one seen and a sparse left instead of a
  seen/left pair per rotation — the log/report/companion-push noise collapses
  (~73:1 per device for Huami) with no risk of merging distinct devices.

## Impact

- Affected specs: `bluetooth-scanning` (rotation-merge gains the payload-equality path).
- Affected code: `src/diting/ble.py` (`_payload_fuses`, `_BLECluster.anchor_mfg_hex`, `_assign_to_cluster`).
- No wire/schema change; display merge and older (no-payload) schemas unaffected.
