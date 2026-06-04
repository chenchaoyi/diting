# Design — BLE familiarity identity ladder

## The ladder (strongest per-device identity first)

`familiarity_key("ble", …)` gains two params (`service_data_id`, `vendor`) and
two rungs:

| # | key | source | per-device? |
|---|-----|--------|-------------|
| 1 | `ble:<manufacturer_hex>` | manufacturer payload (non-Apple) | yes |
| 2 | `ble:sd:<service_data_id>` | service-data schema (MiBeacon MAC) | yes |
| 3 | `ble:vn:<vendor_id>/<name>` | company-id + name | mostly |
| 4 | `ble:vg:<vendor>` | authoritative vendor attribution | no (group) |
| — | `None` | nothing identifying | — |

Order matters: a device with a manufacturer payload keeps its existing key
(rung 1), so no existing familiarity records shift. The new rungs only catch
devices that previously fell through to `None`.

## (B) MiBeacon service-data MAC

MiBeacon (service UUID `FE95`, used by Xiaomi + Huami) frames carry a
frame-control word; bit 4 (`0x0010`, "MAC included") means the six bytes after
the `frame-control(2) + product-id(2) + frame-counter(1)` header are the
device's real MAC, little-endian on the wire. That MAC is stable across BLE
address rotation — the only durable per-device handle these devices expose.

`ble.service_data_identity(service_data) -> str | None` scans the
`(uuid, hex)` pairs for `FE95`, checks the MAC-included bit, and returns
`mibeacon:<mac>` (namespaced so future schemas can't collide). It abstains
(`None`) on wrong schema / short frame / MAC-not-included / malformed hex —
never raises. The result rides the BLE seen/left events as an in-memory
`service_data_id` (not serialised to JSONL/wire), mirroring how
`manufacturer_hex`/`vendor_id` are carried for the key.

Populated at all four construction sites (fresh-cluster seen, connected seen,
cluster-left, fallback-left) from the device's `service_data`, so a left event
folds its dwell under the same key its seen used.

## (A) vendor-group last resort

When rungs 1–3 yield nothing but the decode confidently attributed a `vendor`
(from OUI / SIG company-id / member-UUID / service-data UUID), key on
`ble:vg:<vendor>`. This folds e.g. an office's swarm of payload-less, nameless,
rotating Huami bands into ONE familiarity record — first sighting `first_time`,
every later one `habitual` — instead of leaving 1,400+ events unclassified.

Trade-off (accepted): vendor-group cannot distinguish individual same-vendor
devices, so a genuine influx of N new same-vendor devices reads as one habitual
group and will not trip `new_device_cluster`. For the ambient-vs-valuable goal
this is the right abstraction (these devices are ambient office furniture, and
per-device identity for them is unobtainable from the ad data anyway). Devices
with a real per-device token (rungs 1–2) keep full cluster sensitivity.

`vendor` derived via `lookup_name_vendor` (a name prefix) is the one
non-authoritative source feeding rung 4; it is a coarse recurrence bucket, not
a trust/type decision, so it does not violate the no-name-classification rule —
and the dominant target population (MiBeacon/Huami/Huawei) resolves its vendor
from the service-data UUID, not the name.

## Not in scope

- Display payload-fusion / the cluster merger: unchanged. The JSONL still logs
  one seen/left per rotation; this change only stamps a familiarity class on
  them. Folding the *display* across service-data rotations is a separate
  follow-up (extend `_assign_to_cluster` to fuse on `service_data_id`).
- Service-data schemas beyond MiBeacon `FE95` (Huawei/HONOR, SwitchBot, Govee,
  …) — they fall to vendor-group until a parser is added.
