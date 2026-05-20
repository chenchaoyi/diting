## MODIFIED Requirements

### Requirement: Twelve event types SHALL share one schema and one ring
The system SHALL emit exactly twelve event types — the original five Wi-Fi / link-health types (`roam`, `rf_stir`, `latency_spike`, `loss_burst`, `link_state`) PLUS seven transition event types covering BLE, Bonjour, and LAN discovery:

- `ble_device_seen`, `ble_device_left`
- `bonjour_service_seen`, `bonjour_service_left`
- `lan_host_seen`, `lan_host_left`, `lan_host_dhcp_rotation`

All twelve SHALL be carried in a single `EventRing` keyed by emission timestamp. All twelve SHALL be serialisable through the same `event_to_jsonl` writer; the analyzer SHALL read all twelve through one `_extract_event` function. Adding a thirteenth event type MUST file an ADDED Requirement on this capability.

#### Scenario: TUI event strip
- **WHEN** the user looks at the bottom Events strip
- **THEN** they see the most-recent N events drawn from the ring, regardless of which producer (Wi-Fi poller, latency watcher, environment monitor, BLE poller, Bonjour poller, LAN poller) emitted them

#### Scenario: Headless `diting monitor`
- **WHEN** the user runs `diting monitor > events.jsonl`
- **THEN** every event flowing through the same ring also lands as one JSONL line on stdout, byte-identical to what the TUI's `--log` would write

#### Scenario: New event types degrade gracefully against old analyzer
- **WHEN** a JSONL log written by a new build (carrying the seven new event types) is fed to an older `diting analyze` build
- **THEN** the older analyzer SHALL skip unknown `type` values without crashing (existing tolerance contract; the new types just don't surface in the older analyzer's report)

## ADDED Requirements

### Requirement: BLE transition events SHALL carry rotation-folded identity context
`BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` SHALL each be a `@dataclass(frozen=True, slots=True)` carrying the BLE poller's identifying context for the device:

- `timestamp: datetime` (timezone-aware, local TZ at construction)
- `identifier: str` (the BLEPoller's stable, rotation-folded id)
- `name: str | None`
- `vendor: str | None`
- `service_categories: tuple[str, ...]` (resolved BT-SIG category labels)

`BLEDeviceSeenEvent` SHALL additionally carry `rssi_dbm: int | None` (RSSI at first observation).

`BLEDeviceLeftEvent` SHALL additionally carry `last_rssi_dbm: int | None` and `seen_for_seconds: float` (the duration `last_seen - first_seen` from the poller's state map).

#### Scenario: Magic Keyboard first seen
- **WHEN** a Magic Keyboard advertisement parses into a new BLEDevice with `name="Magic Keyboard"`, `vendor="Apple, Inc."`, `service_categories=("HID",)`, RSSI -55 dBm
- **THEN** `BLEDeviceSeenEvent` is emitted with the same fields plus `timestamp=now`

#### Scenario: BLE device drops out
- **WHEN** a tracked BLE device's `last_seen` falls more than the BLE TTL behind the latest snapshot
- **THEN** `BLEDeviceLeftEvent` is emitted with `seen_for_seconds=last_seen - first_seen`; the device is removed from the poller's state map

### Requirement: Bonjour transition events SHALL carry service-instance + host context
`BonjourServiceSeenEvent` and `BonjourServiceLeftEvent` SHALL each be a `@dataclass(frozen=True, slots=True)`:

- `timestamp: datetime`
- `service_type: str` (e.g. `"_airplay._tcp.local."`)
- `name: str` (the service-instance name part)
- `host: str | None` (`.local.` host the service announces from)
- `category: str | None` (resolved friendly category)
- `vendor: str | None`

`BonjourServiceLeftEvent` SHALL additionally carry `seen_for_seconds: float`.

`BonjourServiceSeenEvent` SHALL additionally carry `addresses: tuple[str, ...]` (the IPs zeroconf resolved at the time of `add_service`).

#### Scenario: HomePod AirPlay receiver appears
- **WHEN** a HomePod first announces an `_airplay._tcp.local.` service
- **THEN** `BonjourServiceSeenEvent` is emitted with the service type, name, host, category, vendor, and addresses

#### Scenario: Printer drops off the network
- **WHEN** zeroconf fires `remove_service` for a tracked Bonjour entry, OR the TTL backstop evicts an entry whose `last_seen` exceeded `_BROWSE_TTL_S`
- **THEN** `BonjourServiceLeftEvent` is emitted with the duration the entry survived

### Requirement: LAN transition events SHALL carry MAC-keyed host context
`LANHostSeenEvent`, `LANHostLeftEvent`, and `LANHostDHCPRotationEvent` SHALL each be a `@dataclass(frozen=True, slots=True)`.

`LANHostSeenEvent` fields:

- `timestamp: datetime`
- `mac: str` (lowercase, colon-separated)
- `ip: str` (IPv4 dotted)
- `vendor: str | None`
- `hostname: str | None`
- `bonjour_name: str | None`
- `is_randomised_mac: bool`

`LANHostLeftEvent` fields: the above plus `seen_for_seconds: float` and `last_reachable_ago_seconds: float | None` (None when the host never responded to ICMP this session).

`LANHostDHCPRotationEvent` fields: `timestamp`, `mac`, `previous_ip`, `new_ip`, `vendor`, `hostname`, `bonjour_name`.

#### Scenario: New host joins the LAN
- **WHEN** a previously-unseen MAC (not the user's own interface MAC, not the gateway) appears in the ARP cache after a sweep
- **THEN** `LANHostSeenEvent` is emitted with the host's identity context

#### Scenario: Self and gateway do NOT generate seen events
- **WHEN** `LANInventoryPoller` runs its first sweep and populates self + gateway entries in state
- **THEN** no `LANHostSeenEvent` is emitted for those two entries; only "external" hosts trigger the event (otherwise every diting launch would emit two noise events)

#### Scenario: Host's IP changes (DHCP rotation)
- **WHEN** an existing tracked MAC is observed at a different IP
- **THEN** `LANHostDHCPRotationEvent` is emitted with `previous_ip` and `new_ip` BEFORE the state entry's `ip` field is updated to the new value

#### Scenario: Long-silent host departs
- **WHEN** a tracked MAC's `last_reachable_at` is older than `_HOST_LEFT_TIMEOUT_S` (default 300 s) AND the MAC is absent from the latest ARP triples
- **THEN** `LANHostLeftEvent` is emitted once with the duration the host was tracked; the entry is then removed from `_state` so a future re-appearance fires a fresh `LANHostSeenEvent`

### Requirement: All seven new event types SHALL omit None fields from their JSONL serialisation
The `event_to_jsonl` writer SHALL emit each new event type with a locale-stable English `type` key and SHALL omit any field whose value is None (matching the existing five event types' convention). Fields whose value is the empty tuple `()` SHALL emit as `[]` (not omitted) so consumers can distinguish "no services advertised" from "field not present".

#### Scenario: BLE seen event with no name
- **WHEN** `BLEDeviceSeenEvent(timestamp=now, identifier="abc", name=None, vendor=None, rssi_dbm=-72, service_categories=())` is serialised
- **THEN** the JSONL line is `{"type": "ble_device_seen", "ts": "...", "identifier": "abc", "rssi_dbm": -72, "service_categories": []}` — no `name` / `vendor` keys, but `service_categories` is present as an empty array
