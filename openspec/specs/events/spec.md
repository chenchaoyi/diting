# events Specification

## Purpose

Defines the unified event vocabulary every diagnostic surface in
diting shares — the in-memory ring buffer the TUI's events strip
and modal browser read from, the JSONL stream `diting monitor`
writes, and the analyzer consumes. One schema, five event types, one
source of truth for what "event" means across the tool.
## Requirements
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

### Requirement: Each event SHALL be a frozen dataclass with an explicit timestamp
Every event class SHALL be defined as a `@dataclass(frozen=True, slots=True)` with at minimum a `timestamp: datetime` field (timezone-aware, local TZ at construction). Mutating an event after emission is prohibited; that is enforced by `frozen=True`. All other fields are event-type-specific.

Wi-Fi-anchored events (`RoamEvent`, `RFStirEvent`) SHALL additionally carry SSID context for the affected association:

- `RoamEvent` SHALL carry `previous_ssid: str | None = None` and `new_ssid: str | None = None`. Each is the SSID associated with the corresponding BSSID at the moment the poller observed the roam.
- `RFStirEvent` SHALL carry `ssid: str | None = None`. It is the SSID associated with the BSSID at the moment the σ threshold was crossed.

Both fields are optional with a default of `None` for backwards compatibility with code paths that construct the event without going through the poller / environment monitor; new fields land at the end of each dataclass so positional construction in legacy callers keeps working.

#### Scenario: Constructing an RFStirEvent
- **WHEN** `RFStirEvent(timestamp=..., bssid=..., location=..., magnitude_db=..., duration_s=..., confidence=..., mode=...)` is created
- **THEN** the resulting object is hashable, comparable, and immutable; `event.ssid` is `None`

#### Scenario: Constructing an RFStirEvent with SSID
- **WHEN** `RFStirEvent(..., ssid="tedo_5G")` is created
- **THEN** the resulting object exposes `event.ssid == "tedo_5G"`

#### Scenario: Constructing a RoamEvent with SSID pair
- **WHEN** `RoamEvent(..., previous_ssid="tedo_5G", new_ssid="tedo_5G")` is created
- **THEN** the resulting object exposes both fields verbatim

### Requirement: The `EventRing` SHALL be size-bounded and thread-safe-by-construction
The ring SHALL retain at most 100 events by default (configurable via
constructor arg). Older events SHALL roll off the front when the
buffer is full. The ring SHALL be appendable from any coroutine in
the asyncio loop without explicit locking — Python's GIL plus the
single-thread asyncio model is the consistency guarantee.

#### Scenario: Ring overflow
- **WHEN** the 101st event is appended to a default-sized ring
- **THEN** the oldest event is dropped silently, the new event lands at the tail, and `snapshot()` returns 100 events (newest last)

### Requirement: JSONL serialisation SHALL use locale-stable English keys
`event_to_jsonl` SHALL emit JSON with English keys (`type`, `bssid`, `ssid`, `state`, `magnitude_db`, etc.) regardless of the active UI language. User-supplied strings (SSID, AP location names from aps.yaml) SHALL pass through with `ensure_ascii=False` so a Chinese SSID like `咖啡馆` lands readable in the log instead of `哖...`.

When `RoamEvent.previous_ssid` / `new_ssid` are set, the JSONL line SHALL include them under the keys `previous_ssid` and `new_ssid` after the existing BSSID / channel keys. When `RFStirEvent.ssid` is set, the JSONL line SHALL include it under the key `ssid` after the existing `bssid` / `location` keys. When the SSID field is `None`, the key SHALL be omitted (the serialiser already skips `None` values for optional fields; this keeps old log entries diff-stable).

#### Scenario: ZH UI, Chinese SSID
- **WHEN** the user runs `diting --lang zh --log /tmp/wifi.jsonl`, gets a roam event from `咖啡馆 → Office`
- **THEN** the JSONL line is `{"type":"roam","previous_ssid":"咖啡馆","new_ssid":"Office", ...}` — keys English, values raw UTF-8

#### Scenario: RFStirEvent with SSID
- **WHEN** an `RFStirEvent` fires for an AP on `tedo_5G`
- **THEN** the JSONL line carries `"ssid":"tedo_5G"` after `"bssid"` and `"location"`

#### Scenario: RoamEvent with no known SSID (TCC redacted)
- **WHEN** a `RoamEvent` fires with both SSIDs `None` (Location Services denied mid-session)
- **THEN** the JSONL line omits both `previous_ssid` and `new_ssid` keys, matching the legacy pre-enrichment shape

### Requirement: Timestamps in the JSONL stream SHALL be local-TZ ISO-8601 with offset
The serialiser SHALL emit timestamps as ISO-8601 strings carrying
the local timezone offset (`_to_utc_iso` is named historically but
emits local offset, not UTC). Naïve datetimes SHALL be promoted to
local-aware via `datetime.astimezone()` before serialisation. The analyzer parses
this back transparently, and human readers see times that match
their wall clock without doing UTC math.

#### Scenario: Event in Beijing local time
- **WHEN** an event is emitted at 2026-05-09 14:23:11 +08:00
- **THEN** the JSONL line carries `"ts":"2026-05-09T14:23:11.123+08:00"`, NOT a UTC string

### Requirement: `NetworkChangeEvent` SHALL be a control-plane signal, not a user-visible event
`NetworkChangeEvent` SHALL exist alongside the five user-visible
event types but SHALL NOT be appended to the `EventRing`. It is an
internal signal consumed by the latency poller (probe reset on
network change). The TUI Events strip and modal SHALL NOT render it;
the JSONL log SHALL NOT carry it.

#### Scenario: User roams from home Wi-Fi to office Wi-Fi
- **WHEN** the connection changes
- **THEN** a `NetworkChangeEvent` reaches the latency poller (which resets gateway/WAN probes), AND a separate `RoamEvent` reaches the user-visible ring; the analyzer sees only the `RoamEvent`

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

### Requirement: `LANActiveProbeConsentedEvent` SHALL be a defined event type that records the user's one-shot acceptance of public-scene LAN active probing
The events module SHALL define a `LANActiveProbeConsentedEvent` `@dataclass(frozen=True, slots=True)` with at minimum:

- `timestamp: datetime` — UTC moment the user confirmed the probe
- `scene: str` — at-time scene name (always `"public"` in v1 since the override is public-only)
- `ssid: str | None` — SSID of the connected Wi-Fi at confirm time, or `None` if disassociated
- `nbns_packets: int` — count of NBNS Status Queries that will be emitted on the next sweep (typically the count of silent hosts)
- `ssdp_packets: int` — fixed at `1`
- `mdns_packets: int` — fixed at `1`

The event SHALL be ingested by the existing `EventLogger.append()` path and SHALL serialise to one JSONL line with `"type": "lan_active_probe_consented"` (kebab → snake matching the existing event type conventions). It SHALL NOT appear in the in-app events modal (LAN-host-seen / left / DHCP-rotation already cover the LAN feed); it is a JSONL-only marker for post-hoc replay.

#### Scenario: Event instance is constructible with required fields
- **WHEN** `LANActiveProbeConsentedEvent(timestamp=<now>, scene="public", ssid="HotelGuest", nbns_packets=8, ssdp_packets=1, mdns_packets=1)` is invoked
- **THEN** the dataclass instance is produced without error and round-trips through JSONL serialisation

#### Scenario: Event serialises with stable type name
- **WHEN** the event is serialised by `EventLogger`
- **THEN** the JSONL line has `"type": "lan_active_probe_consented"`

#### Scenario: Event NOT emitted for scene-default probing
- **WHEN** active scene is `home`, active probing runs as scheduled
- **THEN** no `LANActiveProbeConsentedEvent` is appended (the event is uniquely the user-override marker)

