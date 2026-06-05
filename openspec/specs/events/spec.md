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
The ring SHALL retain at most 1000 events by default (configurable via
constructor arg). Older events SHALL roll off the front when the
buffer is full. The ring SHALL be appendable from any coroutine in
the asyncio loop without explicit locking — Python's GIL plus the
single-thread asyncio model is the consistency guarantee.

#### Scenario: Ring overflow
- **WHEN** the 1001st event is appended to a default-sized ring
- **THEN** the oldest event is dropped silently, the new event lands at the tail, and `snapshot()` returns 1000 events (newest last)

#### Scenario: Custom capacity still honored
- **WHEN** a ring is constructed with `capacity=5` and 6 events are appended
- **THEN** `snapshot()` returns the 5 newest events

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

### Requirement: Seen-side transition events SHALL support an optional familiarity class
Seen-side transition events SHALL support an optional `familiarity` field — one
of `first_time` / `occasional` / `habitual` / `returning` — on `ble_device_seen`,
`bonjour_service_seen`, `lan_host_seen`, and `roam`, describing how familiar the
entity is, derived from the `familiarity-store`. The field is OPTIONAL: when no
familiarity store is wired the events SHALL omit it entirely
(consistent with the None-fields-omitted rule), so the JSONL key set stays
stable for consumers that ignore it. The class for a seen event SHALL reflect
the entity's familiarity BEFORE the current sighting is recorded, so a
never-before-seen entity reads `first_time`.

#### Scenario: First-ever sighting is first_time
- **WHEN** an entity with no prior familiarity record emits a `seen` event with a store wired
- **THEN** the event's `familiarity` is `first_time`

#### Scenario: Field omitted without a store
- **WHEN** no familiarity store is configured
- **THEN** seen events serialise with no `familiarity` key at all (not `null`)

#### Scenario: Roam carries AP familiarity
- **WHEN** a `roam` to a BSSID occurs with a store wired
- **THEN** the event's `familiarity` reflects how familiar that AP (`ap:<bssid>`) is

### Requirement: Events SHALL support an optional salience tier
Emitted events SHALL support an optional `salience` field — one of `noise` /
`low` / `notable` / `high` — describing how attention-worthy the event is,
derived by the `salience` scorer from the event's type, its `familiarity` class,
and signal strength. The field is OPTIONAL: when the scorer abstains for a type
the event SHALL omit it entirely (not `null`), so the JSONL key set stays stable
for consumers that ignore it. Salience is desktop-local in this phase and SHALL
NOT cross the companion wire.

#### Scenario: A scored event carries its tier
- **WHEN** a `ble_device_seen` for a `first_time` device is emitted to a file sink
- **THEN** the JSONL line carries a `salience` field

#### Scenario: An unscored event omits the field
- **WHEN** a `session_meta` line is emitted
- **THEN** it carries no `salience` key

### Requirement: An insight event type SHALL carry a code, severity, and detail
The event vocabulary SHALL include an `insight` event — a synthesized
valuable-change observation — carrying a stable English `code`, a `severity`
(`info` / `note` / `warn` / `critical`, where `critical` is the threat tier),
and an optional structured `detail`. The `code` is locale-stable (the analysis
key); the human one-liner is derived from `code` + `detail` at render / notify
time via `t()`, so the JSONL carries no localised text. `detail` SHALL be
serialised as a single nested object (e.g. `"detail":{"count":4}`), NOT
flattened onto the event — so the JSONL line mirrors the `companion-protocol`
wire shape exactly. `InsightEvent` is a frozen dataclass with a `timestamp`,
like every other event, and rides the same EventRing + JSONL writer.

#### Scenario: Insight serialises with a stable code
- **WHEN** an `insight` event is emitted to a file sink
- **THEN** the JSONL line carries `"type":"insight"`, the English `code`, and the `severity`

#### Scenario: Detail is a nested object when supplied
- **WHEN** an insight is emitted with a non-empty `detail`
- **THEN** the JSONL line carries `detail` as a nested object; when `detail` is absent the line omits the key

### Requirement: Associated link_state SHALL carry a desktop-local security cipher
An `associated` `link_state` event SHALL carry the connection cipher as an
optional desktop-local `security` field (from `conn.security`), present in the
JSONL log but NOT part of the `link_state` companion-protocol wire vocabulary —
it is stripped before sealing (it is a local-only field). It feeds the
`security_downgrade` threat detector. When the cipher is unknown the field is
omitted.

#### Scenario: Associated link_state logs the cipher
- **WHEN** the connection updates to associated with a known security cipher
- **THEN** the JSONL `link_state` line carries a `security` field

#### Scenario: Security never crosses the wire
- **WHEN** an associated `link_state` carrying `security` is forwarded to the companion
- **THEN** the sealed envelope's plaintext omits `security` (it is a local-only field), leaving only the `link_state` wire vocabulary

