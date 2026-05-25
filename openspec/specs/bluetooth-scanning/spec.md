# bluetooth-scanning Specification

## Purpose

Defines the contract for the BLE scanning layer: how raw advertisements
become `BLEDevice` instances, how vendors get resolved, how rotated
identifiers fold into a single visible row, and what the panel shows
when nothing is identifiable. Sits between `macos-helper` (which emits
the JSONL stream) and `ble-decoders` (which interpret payload bytes).
## Requirements
### Requirement: Each helper JSONL line SHALL produce or update exactly one `BLEDevice`
The Python poller SHALL parse one helper JSONL line per call and merge
it into a `dict[identifier, BLEDevice]` keyed by lowercase
peripheral UUID. A line that lacks an `id` SHALL be silently dropped.
A line for a known `id` SHALL update the prior `BLEDevice` with new
fields, preserving carry-forward fields like `vendor_id` and `name`
when the new line omits them.

#### Scenario: Primary advertisement followed by scan response
- **WHEN** the helper emits two lines for the same `id`, the first carrying `manufacturer_id=76` and the second omitting it
- **THEN** the resulting `BLEDevice` retains `vendor_id=76` from the primary, NOT `None` from the scan response

#### Scenario: Malformed JSON line
- **WHEN** a JSONL line fails JSON parsing
- **THEN** the line is dropped silently and processing continues with the next line

### Requirement: Vendor resolution SHALL run a deterministic chain of fallbacks
For each `BLEDevice`, the vendor SHALL be resolved in this order, with
the first hit winning:

1. `manufacturer_id` → SIG Bluetooth company-ID table (4022 entries)
2. `service_uuids` member-UUID → SIG member-UUID table (703 entries) +
   bundled 128-bit member-UUID supplement (Huami / etc.)
3. `service_data` keys → same member-UUID lookup (covers vendors who
   only emit their UUID inside service-data, not service_uuids)
4. `name` → curated regex pattern table (Magic Keyboard, AirPods,
   Mi Band, Jabra Elite, Polar, Garmin, …)
5. Carry-forward from prior `BLEDevice` for the same `id`

#### Scenario: Apple iPhone Nearby Info
- **WHEN** the advertisement carries `manufacturer_id=76`
- **THEN** vendor resolves to "Apple, Inc." via step 1, and steps 2–5 are not consulted

#### Scenario: Mi Band advertising only on FE95 service-data
- **WHEN** the advertisement omits manufacturer_id, and `service_data` has key FE95
- **THEN** vendor resolves to "Xiaomi Inc." via step 3

#### Scenario: User-renamed Magic Keyboard with no advertisement-side payload
- **WHEN** a connected peripheral has name "ccy's Magic Keyboard" and OUI `38:09:fb`
- **THEN** vendor resolves to "Apple, Inc." via OUI lookup; or via name-pattern step 4 if OUI table misses

### Requirement: Connected peripherals SHALL come through a separate code path
Connected-peripheral lines (`{"connected": true, ...}`) SHALL be
routed through `_build_connected_device`, not `_build_device`.
Connected entries SHALL omit `vendor_id` (always None —
`IOBluetoothDevice` doesn't expose manufacturer-data), SHALL use the
BT MAC's OUI for vendor lookup, and SHALL appear in the panel's
"Connected (N)" section above the "Advertising (N)" section.

#### Scenario: Magic Keyboard paired
- **WHEN** the helper emits a connected snapshot containing the Magic Keyboard's BT MAC
- **THEN** the panel's Connected section shows one row with vendor "Apple, Inc.", no RSSI, services from the OUI heuristic

### Requirement: Rotated-identifier merge SHALL fold privacy-rotated rows
The `merge_for_display` step SHALL fold rows that share
`(vendor_id, name)` within an RSSI tolerance window into one visible
row with a `(merged N)` badge, so the user sees the fuzzy-merge
happening rather than wondering where rotated UUIDs went. Modern
devices rotate their per-host UUID for privacy.

#### Scenario: Same iPhone advertising under 4 rotated UUIDs
- **WHEN** the device map contains 4 entries for the same iPhone, all with vendor_id=76, name="ccy iPhone 15 Pro Max", RSSI within ±10 dB
- **THEN** the panel renders one row with `(merged 4)` and the strongest RSSI

#### Scenario: Truly anonymous beacons
- **WHEN** the device map contains 5 rows with vendor=None, name=None, type=None
- **THEN** the merger does NOT fold them — anonymous rows are kept distinct since fold criteria would be vacuous

### Requirement: The panel SHALL distinguish "(anonymous)" from "(unknown)"
A `BLEDevice` SHALL render its vendor cell as `(anonymous)` when it
has zero usable broadcast data (no manufacturer_id, no service UUIDs,
no name, no type, no device_class), and SHALL render `(unknown)` when
it has SOME data but the vendor lookup chain abstained. The
distinction is user-actionable: `(unknown)` rows can be reported as
decoder gaps; `(anonymous)` rows are physical-data limits with no
fix.

#### Scenario: Silent beacon
- **WHEN** an advertisement carries only RSSI and `is_connectable=true`
- **THEN** vendor cell renders `(anonymous)`

#### Scenario: Vendor-private cid
- **WHEN** an advertisement carries `manufacturer_id=58658` (not in SIG table)
- **THEN** vendor cell renders `(unknown)`, and the row counts toward the inspector's "actionable unresolved" bucket

### Requirement: BLE poller SHALL maintain RSSI smoothing for stable sort order
Each `BLEDevice` SHALL carry an exponentially-smoothed RSSI
(`rssi_smooth`) used as the panel's sort key. The display
(`rssi_dbm` column) SHALL show the live latest reading; sort SHALL
NOT swap row order on a single 5-15 dB packet jitter event. EMA
weight SHALL be α=0.4 — fast enough to react to genuine motion in
~3 advertisements, damped enough to ignore packet jitter.

#### Scenario: Stationary device with packet jitter
- **WHEN** a device alternates between RSSI -65 and -78 dBm on consecutive advertisements
- **THEN** `rssi_smooth` stays in a tight band around -70 and the row does NOT jump up and down the panel

### Requirement: Schema-4 raw fields SHALL be plumbed onto `BLEDevice` for downstream decoders
Each `BLEDevice` SHALL carry, when the helper provides them:
`manufacturer_hex` (full mfg-data bytes including cid prefix),
`service_data` (tuple of `(uuid, hex)` pairs),
`tx_power_dbm`,
`solicited_service_uuids`,
`overflow_service_uuids`.
These fields are the only contract the per-protocol decoder layer
relies on. They SHALL be carried forward across scan-response packets
that omit them.

#### Scenario: Scan response without service_data
- **WHEN** a primary advertisement carries `service_data={"FEAA": "..."}` and a follow-up scan response omits service_data
- **THEN** the resulting `BLEDevice` retains the `("FEAA", "...")` tuple from the primary

### Requirement: BLE history SHALL be tracked per-device, capped, and pruned on snapshot churn
Per-device RSSI history SHALL accumulate across scan snapshots in a
separate `BLEHistory` container. Each device's buffer SHALL be capped
(default 60 samples ≈ 2 min of history at 2 s polling). Devices that
fall out of a snapshot SHALL be pruned via `expire(keep_ids)` so a
busy environment churning through random-MAC iPhones cannot leak
history forever.

#### Scenario: Long session with rotating identifiers
- **WHEN** the user runs diting in a busy office for 8 hours with iPhones cycling through 1000 distinct random MACs
- **THEN** `BLEHistory` holds at most ~300 deques (corresponding to currently-visible devices), not 1000

#### Scenario: Connected peripheral
- **WHEN** the snapshot includes a connected Magic Keyboard with `rssi_dbm=None`
- **THEN** `BLEHistory.record` skips the sample silently — no None-tagged entries enter the buffer

### Requirement: BLE Categories diagnostic SHALL exclude protocol-utility GATT services
The aggregate Categories diagnostic row in the BLE view SHALL NOT count the three generic protocol-utility GATT services as device kinds: `1800` (Generic Access), `1801` (Generic Attribute), and `180A` (Device Information). These services are advertised by virtually every BLE peripheral that supports bonding, so including them in the Categories breakdown inflates a top-of-list count that reads like a device-class label but contains no information about what kinds of devices are actually around.

The per-row "Services" column SHALL continue to render these names when a device's UUID list includes them, because in a single device's row they ARE useful detail.

The exclusion is implemented via the `category_only=True` flag on `service_category(uuid, *, category_only)` in `src/diting/ble.py`. Future protocol-utility UUIDs that pollute the Categories row in the same way SHALL be added to the same exclusion set rather than introducing a new filter layer.

#### Scenario: Device Information service excluded from Categories breakdown
- **WHEN** the BLE diagnostic strip computes its Categories row over a snapshot containing 20 devices that advertise `180A`
- **THEN** the Categories row SHALL NOT include `Device Information 20` as a category
- **AND** if those 20 devices also advertise other categorisable services (e.g. `iPhone`, `HID`, `Heart Rate`), those categories SHALL still be counted

#### Scenario: Device Information service still rendered in per-row Services column
- **WHEN** a single BLE row's services column resolves `180A` (without `category_only=True`)
- **THEN** the column SHALL display `Device Information`
- **AND** the BLE detail modal SHALL show `Device Information` in the Services section

### Requirement: `BLEPoller` SHALL emit transition events when devices enter and leave its tracked state
`BLEPoller` SHALL emit `BLEDeviceSeenEvent` when a device's `identifier` graduates from PENDING to PRESENT in its tracked state map. Graduation happens via one of two paths:

- **Bypass path** — the identifier's first observation carries a non-null `name` OR the identifier comes from the `_connected` snapshot. Graduates to PRESENT on the same tick, `BLEDeviceSeenEvent` fires with the original `first_seen` timestamp.
- **Gated path** — the identifier's first observation is anonymous (no helper-given `name`, only `vendor` + RSSI). The identifier enters PENDING with a stored `first_seen` timestamp. On each subsequent tick, the poller checks whether `(now - first_seen) >= presence_gate_s`. When that elapses AND the identifier is still in `_devices`, the identifier graduates to PRESENT and `BLEDeviceSeenEvent` fires with `timestamp = first_seen` (NOT the wall-clock graduation time).

`presence_gate_s` is configurable via `BLEPoller(presence_gate_s=...)`. The default `presence_gate_s` for any given session SHALL be sourced from the active scene: `scene_defaults(get_scene())["ble_presence_gate_s"]`. With the four canonical scenes that resolves to `home=5.0`, `office=15.0`, `public=30.0`, `audit=0.0`. The `home` value (5.0) matches the pre-scene v1.5.0 default — upgrading users who do not pass `--scene` see no behaviour change.

`--ble-presence-gate D` on the CLI SHALL override the scene-derived default — the explicit flag is narrower-scoped and always wins. A value of `0.0` (whether from `--scene audit` or from `--ble-presence-gate 0`) restores the pre-gate "every first-seen identifier fires seen on its first observation" behaviour, including for anonymous adverts; in that case PENDING is bypassed entirely.

`BLEPoller` SHALL emit `BLEDeviceLeftEvent` when a PRESENT device's `last_seen` falls more than the existing TTL behind the latest snapshot AND the device is then removed from state.

If a PENDING identifier is evicted from `_devices` (TTL elapses) before its presence-gate matures, the poller SHALL emit NO transition events for it — no seen, no left. The identifier returns to INIT silently; a future re-appearance from the same identifier opens a fresh PENDING window.

Subsequent observations of the same identifier in the same session SHALL NOT re-fire `BLEDeviceSeenEvent`.

After a `BLEDeviceLeftEvent` has fired for a given identifier within a session, the poller SHALL emit no further transition events for that identifier in the same session — neither another `BLEDeviceLeftEvent` if the identifier flaps back into `_devices` and is evicted again, nor a fresh `BLEDeviceSeenEvent` if a new advertisement re-introduces it. The identifier is terminal-departed for the rest of the session.

The `BLEPoller.events()` async iterator's union return type SHALL include `BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` alongside the existing `BLEScanUpdate`.

#### Scenario: Named first advert bypasses the presence gate
- **WHEN** an advertisement parses into a BLEDevice with `name = "Magic Keyboard"`, `vendor = "Apple, Inc."`, `identifier` not in `_state`
- **THEN** `BLEDeviceSeenEvent` is yielded on the same `_detect_transitions` tick; the identifier moves directly to PRESENT without entering PENDING

#### Scenario: Anonymous first advert below the gate is silent
- **WHEN** an anonymous advertisement (no `name`, only `vendor`) populates `_devices[ident]` at t=0 with default `presence_gate_s = 5.0`, AND the identifier ages out via TTL at t=4
- **THEN** no `BLEDeviceSeenEvent` is yielded; no `BLEDeviceLeftEvent` is yielded; the identifier leaves `_pending_seen` silently

#### Scenario: Anonymous first advert graduates after the gate elapses
- **WHEN** an anonymous advertisement populates `_devices[ident]` at t=0 with `first_seen = t=0` and `presence_gate_s = 5.0`, AND the device is still in `_devices` at t=5.1 (subsequent adverts kept `last_seen` recent)
- **THEN** `BLEDeviceSeenEvent` is yielded with `timestamp = t=0` (the original first_seen, NOT wall-clock at graduation); the identifier moves from PENDING to PRESENT

#### Scenario: `presence_gate_s = 0` restores no-debounce
- **WHEN** `BLEPoller(presence_gate_s=0.0)` is constructed AND an anonymous advertisement populates `_devices[ident]` for the first time
- **THEN** `BLEDeviceSeenEvent` is yielded on the same tick, with no PENDING state entered

#### Scenario: Scene `office` sources a 15 s gate
- **WHEN** `diting --scene office` is launched with no explicit `--ble-presence-gate`
- **THEN** `BLEPoller.presence_gate_s == 15.0` for the session

#### Scenario: `--ble-presence-gate` overrides scene
- **WHEN** `diting --scene office --ble-presence-gate 5s` is launched
- **THEN** `BLEPoller.presence_gate_s == 5.0` for the session; the scene name remains `office` for session_meta / LLM context

#### Scenario: TTL eviction fires left
- **WHEN** a tracked device's `last_seen` exceeds the BLE TTL relative to the latest snapshot's `now` AND the identifier had previously graduated to PRESENT
- **THEN** `BLEDeviceLeftEvent` is yielded with `seen_for_seconds = last_seen - first_seen`; the entry is removed from `_state`

#### Scenario: Repeated TTL eviction of the same identifier is silent
- **WHEN** an identifier has already emitted a `BLEDeviceLeftEvent` in this session AND a subsequent advertisement re-populates `_devices[ident]` AND TTL later evicts it again
- **THEN** no additional `BLEDeviceLeftEvent` is emitted; no `BLEDeviceSeenEvent` is emitted on the re-appearance either

#### Scenario: Connected peripheral does NOT fire spurious seen events
- **WHEN** a connected peripheral is already tracked AND a subsequent connected-snapshot tick re-asserts its presence
- **THEN** no additional `BLEDeviceSeenEvent` is emitted


### Requirement: The BLE row renderer SHALL substitute `(rotating ID)` for high-entropy local names while preserving the raw value in the detail modal
The BLE row renderer SHALL substitute the locale-stable placeholder `(rotating ID)` for any device whose advertised local name matches a high-entropy rotating-identifier shape, and SHALL preserve the raw value verbatim in the BLE detail modal. The substitution is render-only; the underlying `BLEDevice.name` field SHALL NOT be mutated.

Apple Continuity (Find-My / Handoff / Nearby-Info) and some IoT vendors (Huami / Amazfit / Mi-Band) publish opaque rotating-identifier strings in the BLE local-name slot — for example `NZ1NhvIw3H5T5cSy3kULrJ` (Apple Continuity) or `Z-GM0YXG6A` (Huami serial). These are not human-readable identities and reading them as device names is misleading.

The row renderer SHALL apply a `_looks_like_rotating_id(name)` predicate to the `name` field. The predicate SHALL return `True` if and only if ALL of the following hold:

- `name` is non-empty
- `name` contains no whitespace characters (`\s` per Python regex)
- `name` matches `^[A-Za-z0-9+/=_-]{16,}$` (16+ characters, base64 / hex / underscore / hyphen alphabet only)
- `name` does NOT start with any of: `iPhone`, `iPad`, `Mac`, `AirPods`, `HomePod`, `Apple TV`, `Apple Watch`, `Beats` (case-insensitive prefix match)

When the predicate returns `True`, the row's `name` column SHALL render the locale-stable string `(rotating ID)` (EN catalog) / `(临时标识)` (ZH catalog) in dim italic style — the same style class used for `(anonymous)` / `(unknown)`. The underlying `BLEDevice.name` field SHALL NOT be mutated; the substitution is purely a render-time transform.

The BLE detail modal SHALL surface the raw advertised string under a new `Raw name:` row (EN) / `原始名称:` row (ZH) in the Identity section *whenever the row's display value would differ from the raw helper value* — that is, whenever `_looks_like_rotating_id(d.name)` returns `True`. Users investigating a specific device can still see exactly what the helper reported. The row SHALL be omitted when `BLEDevice.name` is None or empty, and SHALL be omitted when the list already renders the raw value (predicate returned `False`) — the Identity section's existing `name:` row already carries it.

#### Scenario: Apple Continuity rotating identifier
- **WHEN** the helper emits a row with `vendor="Apple, Inc."`, `name="NZ1NhvIw3H5T5cSy3kULrJ"`, no `device_class`
- **THEN** the list row's name column renders `(rotating ID)` in dim italic, AND the detail modal's Identity section includes a `Raw name: NZ1NhvIw3H5T5cSy3kULrJ` row

#### Scenario: Huami serial-shaped name
- **WHEN** the helper emits a row with `vendor="Huami"`, `name="Z-GM0YXG6A"`
- **THEN** the list row's name column renders `(rotating ID)`; the detail modal still surfaces `Raw name: Z-GM0YXG6A`

#### Scenario: Real Apple device prefix is preserved
- **WHEN** the helper emits a row with `name="iPhone"` or `name="ccy iPhone 15 Pro Max"`
- **THEN** the predicate returns `False`; the list row's name column renders the original string; no `Raw name:` row is added to the detail modal (because the list value already matches)

#### Scenario: Short or whitespaced names are preserved
- **WHEN** the helper emits a row with `name="HW Watch GT"` or `name="abc"`
- **THEN** the predicate returns `False` (contains whitespace / fewer than 16 chars); the list row renders the original string

#### Scenario: Connected peripheral with a real device name
- **WHEN** the helper's `retrieveConnectedPeripherals` snapshot lists a Magic Keyboard with `name="ccy's Magic Keyboard"`
- **THEN** the predicate returns `False` (contains whitespace + apostrophe); the connected-section row renders the original string verbatim

#### Scenario: Raw-name row in ZH catalog
- **WHEN** the user runs `DITING_LANG=zh diting` and opens the detail modal on an Apple rotating-ID row
- **THEN** the detail modal's Identity section shows `原始名称: NZ1NhvIw3H5T5cSy3kULrJ` (label from the ZH catalog; value verbatim)
