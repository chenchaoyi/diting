## ADDED Requirements

### Requirement: The writer SHALL serialize the seven new transition event types
`event_to_jsonl` SHALL emit each new event type with a locale-stable English `type` key:

| Event class | JSONL `type` value |
|---|---|
| `BLEDeviceSeenEvent` | `"ble_device_seen"` |
| `BLEDeviceLeftEvent` | `"ble_device_left"` |
| `BonjourServiceSeenEvent` | `"bonjour_service_seen"` |
| `BonjourServiceLeftEvent` | `"bonjour_service_left"` |
| `LANHostSeenEvent` | `"lan_host_seen"` |
| `LANHostLeftEvent` | `"lan_host_left"` |
| `LANHostDHCPRotationEvent` | `"lan_host_dhcp_rotation"` |

Field naming SHALL follow the snake_case English convention used by the existing five event types. Fields whose value is `None` SHALL be omitted from the line; tuple fields whose value is `()` SHALL emit as `[]` (informative — "empty list" is distinct from "field missing").

#### Scenario: BLE device-seen serialises with all populated fields
- **WHEN** `BLEDeviceSeenEvent(timestamp=t, identifier="abc", name="Magic Keyboard", vendor="Apple, Inc.", rssi_dbm=-55, service_categories=("HID",))` flows through `event_to_jsonl`
- **THEN** the JSONL line is `{"type": "ble_device_seen", "ts": "<iso>", "identifier": "abc", "name": "Magic Keyboard", "vendor": "Apple, Inc.", "rssi_dbm": -55, "service_categories": ["HID"]}`

#### Scenario: Bonjour-service-left preserves empty addresses tuple
- **WHEN** `BonjourServiceLeftEvent(timestamp=t, service_type="_airplay._tcp.local.", name="Blue Pod._airplay._tcp.local.", host=None, category="AirPlay", seen_for_seconds=3600.0)` flows through `event_to_jsonl`
- **THEN** the JSONL line carries `category` and `seen_for_seconds` but NOT `host`; `service_type` and `name` are present

### Requirement: `EventLogger` SHALL expose one emit method per new event type
The logger SHALL gain seven new methods, each accepting the corresponding event dataclass and writing one JSONL line with flush-on-write semantics (matching the existing five emit methods):

- `emit_ble_device_seen(event: BLEDeviceSeenEvent) -> None`
- `emit_ble_device_left(event: BLEDeviceLeftEvent) -> None`
- `emit_bonjour_service_seen(event: BonjourServiceSeenEvent) -> None`
- `emit_bonjour_service_left(event: BonjourServiceLeftEvent) -> None`
- `emit_lan_host_seen(event: LANHostSeenEvent) -> None`
- `emit_lan_host_left(event: LANHostLeftEvent) -> None`
- `emit_lan_host_dhcp_rotation(event: LANHostDHCPRotationEvent) -> None`

The no-op logger contract (writer accepts `None` for `enable_logging=False` runs) SHALL extend to all seven new methods.

#### Scenario: No-op logger swallows new event types
- **WHEN** `EventLogger(None)` has any of the seven new methods called on it
- **THEN** the call returns silently; no file is opened, no exception is raised
