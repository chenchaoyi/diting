## MODIFIED Requirements

### Requirement: EventsPanel SHALL format the twelve event types with type-prefix tags
`EventsPanel.append_event` SHALL render each event with a leading bracket-tag identifying its type, followed by a short type-specific summary. The full tag set is:

| Tag | Event type(s) |
|---|---|
| `[ROAM]` | `roam` |
| `[STIR]` | `rf_stir` |
| `[LATENCY]` | `latency_spike` |
| `[LOSS]` | `loss_burst` |
| `[LINK]` | `link_state` |
| `[BLE]` | `ble_device_seen` / `ble_device_left` (NEW) |
| `[BJ]` | `bonjour_service_seen` / `bonjour_service_left` (NEW) |
| `[LAN]` | `lan_host_seen` / `lan_host_left` / `lan_host_dhcp_rotation` (NEW) |

The seven new event types' rendered formats:

- `[BLE] device seen: <vendor> · <name>` (or `(unknown)` / `(anonymous)` when blank)
- `[BLE] device left: <vendor> · <name> · <duration>`
- `[BJ] service seen: <category> · <host>` (or `(unknown)` when category blank)
- `[BJ] service left: <category> · <host> · <duration>`
- `[LAN] host seen: <vendor> · <name-or-ip>` (`name` = bonjour_name OR hostname OR IP)
- `[LAN] host left: <vendor> · <name-or-ip> · <duration>`
- `[LAN] <vendor> · <name-or-ip> moved <previous_ip> → <new_ip>`

The verb "seen" — not "joined" — matches the canonical event type names (`ble_device_seen`, `bonjour_service_seen`, `lan_host_seen`) and the ZH translation (`出现` ≈ "appeared / seen"). These events fire on passive first observation (strangers' phones walking past, mDNS announces on the link, ARP cache entries appearing), NOT on a deliberate user-initiated association.

Each rendered line SHALL be at most one terminal row even on narrow widths; rendering SHALL use `fit_cells` for the long-name segment.

#### Scenario: BLE seen line
- **WHEN** a `BLEDeviceSeenEvent` with `name="Magic Keyboard"`, `vendor="Apple, Inc."` flows through `append_event`
- **THEN** the EventsPanel surfaces a line `[BLE] device seen: Apple, Inc. · Magic Keyboard`

#### Scenario: LAN DHCP rotation line
- **WHEN** a `LANHostDHCPRotationEvent` with `mac="de:ad:be:ef:00:01"`, `vendor="Apple, Inc."`, `bonjour_name="ccy-MBP24-M4-Office"`, `previous_ip="192.168.1.42"`, `new_ip="192.168.1.77"` flows through `append_event`
- **THEN** the line is `[LAN] Apple, Inc. · ccy-MBP24-M4-Office moved 192.168.1.42 → 192.168.1.77`
