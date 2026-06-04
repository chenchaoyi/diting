# Tighten new_device_cluster with a proximity gate

## Why

A real 18-hour office capture fired `new_device_cluster` 31 times — and **every
single one reported count 3 or 4** (the exact threshold). It was not detecting
"a group arrived"; it was catching the steady all-day trickle of `first_time`
BLE identities (far-field office churn) crossing the bar. 31 `note` insights of
"3 unfamiliar devices appeared together" is the low-signal noise the salience
layer exists to avoid.

## What Changes

A BLE arrival counts toward `new_device_cluster` only when it is physically
**near** — RSSI ≥ a near threshold (`-70 dBm`). A meaningful cluster is "several
unfamiliar devices appeared *close to you*" (you walked into a populated room, a
group sat down), not the far-field swarm of a dense floor. A BLE row with no
RSSI can't establish proximity and is excluded. Non-BLE arrivals (a new LAN host
/ Bonjour service) have no proximity dimension and still count.

This composes with the just-merged service-data / vendor-group familiarity
(#160): most ambient devices now classify as `habitual` (not `first_time`), so
they already stopped feeding the cluster count; the proximity gate handles the
genuinely-`first_time` far-field remainder.

## Impact

- Affected specs: `insights` (the `new_device_cluster` scenario gains the
  proximity qualifier).
- Affected code: `src/diting/insights.py` — `_CLUSTER_NEAR_RSSI_DBM` constant +
  an `_arrival_is_near` gate in `observe`. No new fields; `rssi_dbm` is already
  on the `ble_device_seen` payload.
- **Scope limit:** threshold value only; the cluster minimum (3) and window
  (120 s) are unchanged. Proximity applies to BLE; LAN/Bonjour first-time
  arrivals are rare + inherently notable, so they still count.
