<sub>**English** · [中文](../zh/explainers/ble-identity.md)</sub>

# How diting identifies a BLE device

Modern BLE devices rotate their advertising address (a privacy feature), so
"the same identifier appeared again" tells you almost nothing — the identifier
you saw five minutes ago belongs to a different random rotation of (possibly)
the same physical device. To say anything useful about *recurrence* — "is this
the user's habitual environment, or a genuine newcomer?" — diting needs a
**stable identity** that survives address rotation.

That identity is what the **familiarity** layer keys on. It is also what the
"no name-based classification" rule constrains: a display name is
user-controllable and trivially spoofable, so it is **never** the identity.

## The identity ladder

For each BLE device, diting picks the strongest stable, *authoritative* identity
it can, in this order:

1. **Manufacturer payload** — `ble:<manufacturer_hex>`. When a device advertises
   manufacturer-specific data, the payload itself is a per-device token (the
   same one the display "merged N" fusion uses). Non-Apple only — Apple's
   Continuity payloads are generic across devices.

2. **Service-data per-device id** — `ble:sd:<id>`. A large class of real
   devices — Mi Band / Amazfit / Huami / Huawei wearables — advertises via
   **service-data**, not manufacturer-data: no manufacturer payload, no name, a
   rotating UUID. They look anonymous, but the service-data frame can embed a
   durable id. diting parses **MiBeacon (`FE95`)**: when the frame-control
   "MAC included" bit is set, the embedded six-byte MAC is the device's real
   address, stable across rotation → `mibeacon:<mac>`. (Other schemas —
   Huawei/HONOR, SwitchBot, Govee — fall through to the next rungs until a
   parser is added.)

3. **Company-id + name** — `ble:vn:<vendor_id>/<name>`. The fallback when there
   is a SIG company-id and/or a name but no usable payload.

4. **Vendor group** — `ble:vg:<vendor>`. The last resort. When a device was
   *confidently attributed to a manufacturer* (via OUI, SIG company-id,
   member-UUID, or a vendor-owned service-data UUID) but exposes none of the
   per-device tokens above, diting folds all of that vendor's payload-less,
   nameless, rotating devices into **one ambient group**. In a dense office
   that turns a swarm of 1,400+ indistinguishable Huami sightings into a single
   *habitual* record instead of 1,400 unclassified ones.

If none of these apply — a truly silent beacon — the device has **no** familiarity
identity, and that is honest: there is nothing in its advertisement to recur on.

## Why a group key for rung 4

Rungs 1–2 give a real per-device handle. Rung 4 deliberately does **not**: these
devices rotate everything and carry no per-device token, so per-device identity
is simply unobtainable from the air. Grouping them by vendor is recurrence
bookkeeping — "Huami-type devices are ambient here" — not a per-device or trust
claim. The trade-off: a genuine influx of several *new* same-vendor devices reads
as one already-familiar group and will not trip the `new_device_cluster` insight.
For the ambient-vs-valuable goal that is the right call; devices with a real
per-device token (rungs 1–2) keep full new-arrival sensitivity.

Every rung keys on an **authoritative** signal — a payload, an embedded MAC, an
OUI/UUID/company-id-derived vendor — never the spoofable display name.

## Scope

This is the **familiarity** identity (recurrence tracking). It does not change
the live display de-duplication / cluster merger, so the JSONL event log still
records one `seen` / `left` per rotation; what changed is that those events now
carry a familiarity class, so salience can rank them and habitual groups stop
reading as `first_time`.
