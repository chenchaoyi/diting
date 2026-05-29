## MODIFIED Requirements

### Requirement: BLE transition events SHALL carry rotation-folded identity context
`BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` SHALL each be a `@dataclass(frozen=True, slots=True)` carrying the BLE poller's identifying context for the device:

- `timestamp: datetime` (timezone-aware, local TZ at construction)
- `identifier: str` (the BLEPoller's stable, rotation-folded id)
- `name: str | None`
- `vendor: str | None`
- `device_type: str | None` (the Apple Continuity advertisement type the BLE list shows — *Find My target*, *MS device beacon*, *Apple Proximity*, etc. — sourced from the cluster representative's `BLEDevice.type`)
- `device_class: str | None` (the Apple Nearby-Info device class — *iPhone*, *Mac*, *Apple Watch* — sourced from the cluster representative's `BLEDevice.device_class`)
- `service_categories: tuple[str, ...]` (resolved BT-SIG category labels)

`BLEDeviceSeenEvent` SHALL additionally carry `rssi_dbm: int | None` (RSSI at first observation) and `at_launch: bool` (True when the seen fired inside the poller's startup warmup window — see the BLE-poller emission requirement). `at_launch` SHALL default to `False`.

`BLEDeviceLeftEvent` SHALL additionally carry `last_rssi_dbm: int | None` and `seen_for_seconds: float` (the duration `last_seen - first_seen` from the poller's state map). `BLEDeviceLeftEvent` SHALL NOT carry `at_launch` (a left is never part of the at-launch census).

`device_type` and `device_class` SHALL default to `None` so older call sites and deserialised legacy events remain valid.

#### Scenario: Magic Keyboard first seen
- **WHEN** a Magic Keyboard advertisement parses into a new BLEDevice with `name="Magic Keyboard"`, `vendor="Apple, Inc."`, `service_categories=("HID",)`, RSSI -55 dBm
- **THEN** `BLEDeviceSeenEvent` is emitted with the same fields plus `timestamp=now`, `device_type=None`, `device_class=None`

#### Scenario: Anonymous-named iPhone carries its decoded class
- **WHEN** a Continuity advertisement parses into a new BLEDevice with `name=None`, `vendor="Apple, Inc."`, `type=None`, `device_class="iPhone"`
- **THEN** `BLEDeviceSeenEvent` is emitted with `name=None`, `vendor="Apple, Inc."`, `device_class="iPhone"` — the event carries the same class the BLE list renders, so the device is not reduced to `(anonymous)` downstream

#### Scenario: BLE device drops out
- **WHEN** a tracked BLE device's `last_seen` falls more than the BLE TTL behind the latest snapshot
- **THEN** `BLEDeviceLeftEvent` is emitted with `seen_for_seconds=last_seen - first_seen`, carrying the cluster representative's `device_type` / `device_class`; the device is removed from the poller's state map

## ADDED Requirements

### Requirement: BLE transition-event JSONL SHALL serialise device type, class, and at-launch as optional keys
`emit_ble_device_seen` and `emit_ble_device_left` SHALL serialise `device_type` and `device_class` as optional JSONL keys, included only when the value is not `None`. Because the JSONL line envelope already uses the key `type` for the event *kind* (`"ble_device_seen"` / `"ble_device_left"`), the device's Continuity type SHALL serialise under the key **`device_type`**, NEVER `type`. `emit_ble_device_seen` SHALL additionally serialise `at_launch` as an optional boolean key, included only when `True`. These keys SHALL appear after the existing `name` / `vendor` / `rssi_dbm` keys. Omission of `None`/`False` values keeps legacy log lines diff-stable and matches the existing None-omission convention.

#### Scenario: Seen with decoded class at launch
- **WHEN** a `BLEDeviceSeenEvent` with `vendor="Apple, Inc."`, `name=None`, `device_class="iPhone"`, `at_launch=True` is serialised
- **THEN** the JSONL line is `{"type":"ble_device_seen", ... ,"vendor":"Apple, Inc.","device_class":"iPhone","at_launch":true}` — the device kind under `type`, the device class under `device_class`, no `name` key

#### Scenario: Seen with no class, mid-session
- **WHEN** a `BLEDeviceSeenEvent` with `device_type=None`, `device_class=None`, `at_launch=False` is serialised
- **THEN** the JSONL line omits `device_type`, `device_class`, and `at_launch` entirely — byte-identical to the pre-change shape for this input

#### Scenario: Left with a Continuity type
- **WHEN** a `BLEDeviceLeftEvent` with `device_type="Find My target"`, `device_class=None` is serialised
- **THEN** the JSONL line carries `"device_type":"Find My target"`, omits `device_class`, and carries no `at_launch` key
