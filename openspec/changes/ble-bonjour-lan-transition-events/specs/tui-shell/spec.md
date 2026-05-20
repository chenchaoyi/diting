## MODIFIED Requirements

### Requirement: Modal screens SHALL push onto a stack and Esc / their own letter SHALL close
Each modal SHALL be opened via `app.push_screen(...)` and SHALL close on Esc, `q`, or the same key that opened it. The five bundled modals — HelpScreen (`?`), BasicsScreen (`b`), EventsScreen (`m`), BLEDetailScreen (`i`), LANDetailScreen (`i`) — all follow this convention. Modals SHALL render center-middle with a heavy-bordered box and a footer hint listing the close keys.

The `h` key SHALL NOT be bound to any action; the slot is reserved for a future per-view binding without colliding with the global help shortcut.

The `i` keystroke is **view-contextual**: on Wi-Fi it opens `WifiDetailScreen`, on BLE it opens `BLEDetailScreen`, on Bonjour it opens `BonjourDetailScreen`, on LAN it opens `LANDetailScreen`. Each detail modal closes via `Esc` / `i` / `q`.

EventsScreen SHALL render four sections — Identity / Network / Bonjour services / Activity — for the LANDetailScreen lookup convention; the existing LANDetailScreen contract is preserved verbatim.

**Filter cycle extension** — EventsScreen SHALL accept eight filter buckets instead of five:

| Key | Bucket | Event types |
|---|---|---|
| `0` | `all` | every event in the ring |
| `1` | `roam` | `roam` |
| `2` | `rf_stir` | `rf_stir` |
| `3` | `latency` | `latency_spike` AND `loss_burst` (existing folded bucket) |
| `4` | `link_state` | `link_state` |
| `5` | `ble` | `ble_device_seen` AND `ble_device_left` (NEW) |
| `6` | `bonjour` | `bonjour_service_seen` AND `bonjour_service_left` (NEW) |
| `7` | `lan` | `lan_host_seen`, `lan_host_left`, `lan_host_dhcp_rotation` (NEW) |

The HelpScreen documentation for EventsScreen SHALL list all eight buckets.

#### Scenario: User filters Events modal to BLE only
- **WHEN** the user opens EventsScreen via `m` and presses `5`
- **THEN** the rendered list shows only `ble_device_seen` and `ble_device_left` entries from the ring; the filter indicator updates to `ble`

#### Scenario: User cycles past the legacy filter buckets
- **WHEN** the user presses `7` from any earlier filter bucket
- **THEN** the filter advances to `lan` and the list re-renders to only LAN-side transition events

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

- `[BLE] device joined: <vendor> · <name>` (or `(unknown)` / `(anonymous)` when blank)
- `[BLE] device left: <vendor> · <name> · <duration>`
- `[BJ] service joined: <category> · <host>` (or `(unknown)` when category blank)
- `[BJ] service left: <category> · <host> · <duration>`
- `[LAN] host joined: <vendor> · <name-or-ip>` (`name` = bonjour_name OR hostname OR IP)
- `[LAN] host left: <vendor> · <name-or-ip> · <duration>`
- `[LAN] <vendor> · <name-or-ip> moved <previous_ip> → <new_ip>`

Each rendered line SHALL be at most one terminal row even on narrow widths; rendering SHALL use `fit_cells` for the long-name segment.

#### Scenario: BLE joined line
- **WHEN** a `BLEDeviceSeenEvent` with `name="Magic Keyboard"`, `vendor="Apple, Inc."` flows through `append_event`
- **THEN** the EventsPanel surfaces a line `[BLE] device joined: Apple, Inc. · Magic Keyboard`

#### Scenario: LAN DHCP rotation line
- **WHEN** a `LANHostDHCPRotationEvent` with `mac="de:ad:be:ef:00:01"`, `vendor="Apple, Inc."`, `bonjour_name="ccy-MBP24-M4-Office"`, `previous_ip="192.168.1.42"`, `new_ip="192.168.1.77"` flows through `append_event`
- **THEN** the line is `[LAN] Apple, Inc. · ccy-MBP24-M4-Office moved 192.168.1.42 → 192.168.1.77`
