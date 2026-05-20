## Why

diting's current event vocabulary is Wi-Fi-anchored: five types
(`roam`, `rf_stir`, `latency_spike`, `loss_burst`, `link_state`)
plus connection-updates. That mirrors the v1.0 era where the tool
was a Wi-Fi monitor with BLE-as-a-bonus. v1.2/v1.3 added rich BLE,
Bonjour, and LAN-inventory panels — but those subsystems only
update *snapshot state*; they don't emit events.

The cost: the user can see "right now" in each panel but cannot
ask "when did that printer first appear" or "did AirPods leave at
18:00 yesterday" against the `--log` JSONL. Cross-session timeline
analysis (Track A2, in a separate change) is gated on this richer
event stream existing in the first place.

This proposal adds **seven transition event types** spanning BLE,
Bonjour, and LAN — one per meaningful state transition each
subsystem already detects. All seven follow the existing event-
schema convention so the EventRing, JSONL writer, EventsScreen
modal, and analyzer pipeline absorb them without architectural
change.

## What Changes

### `events` — new event types

- **ADDED:** `BLEDeviceSeenEvent` — emitted when a BLE device
  appears in `BLEPoller`'s state for the first time. Fields:
  `timestamp`, `identifier` (the poller's stable id, usually
  rotation-folded MAC or UUID), `name: str | None`, `vendor: str |
  None`, `rssi_dbm: int | None`, `service_categories: tuple[str,
  ...]` (BT-SIG categories already resolved by the poller).
- **ADDED:** `BLEDeviceLeftEvent` — emitted when a tracked BLE
  device's TTL expires (no advertisement / connected sentinel for
  N seconds). Fields: `timestamp`, `identifier`, `name`, `vendor`,
  `last_rssi_dbm`, `seen_for_seconds` (duration `last_seen -
  first_seen`).
- **ADDED:** `BonjourServiceSeenEvent` — emitted when a new
  `(service_type, name)` pair enters `BonjourPoller._state`.
  Fields: `timestamp`, `service_type`, `name`, `host: str | None`,
  `category: str | None`, `vendor: str | None`,
  `addresses: tuple[str, ...]`.
- **ADDED:** `BonjourServiceLeftEvent` — emitted when zeroconf
  fires `remove_service` OR the TTL backstop evicts a tracked
  service. Fields: `timestamp`, `service_type`, `name`, `host`,
  `category`, `seen_for_seconds`.
- **ADDED:** `LANHostSeenEvent` — emitted when a new MAC enters
  `LANInventoryPoller._state` (excluding self and gateway, which
  enter on first sweep and would generate a noise event on every
  diting launch). Fields: `timestamp`, `mac`, `ip`, `vendor: str |
  None`, `hostname: str | None`, `bonjour_name: str | None`,
  `is_randomised_mac: bool`.
- **ADDED:** `LANHostLeftEvent` — emitted when a tracked MAC's
  `last_reachable_at` falls more than N minutes (default 5) behind
  the latest sweep. Fields: `timestamp`, `mac`, `ip`, `vendor`,
  `hostname`, `bonjour_name`, `seen_for_seconds`,
  `last_reachable_ago_seconds`.
- **ADDED:** `LANHostDHCPRotationEvent` — emitted when a tracked
  MAC is observed at a new IP (same MAC, different IP). Fields:
  `timestamp`, `mac`, `previous_ip`, `new_ip`, `vendor`,
  `hostname`, `bonjour_name`.

All seven are `@dataclass(frozen=True, slots=True)` and ride the
same `EventRing` + `event_to_jsonl` writer as the existing five.
The "five event types" canonical requirement is updated to
"twelve event types".

### `event-log` — JSONL schemas for the new events

- **ADDED:** `event_to_jsonl` SHALL emit each new event type with a
  locale-stable English `type` key:
  - `"ble_device_seen"` / `"ble_device_left"`
  - `"bonjour_service_seen"` / `"bonjour_service_left"`
  - `"lan_host_seen"` / `"lan_host_left"` / `"lan_host_dhcp_rotation"`
- **ADDED:** Fields SHALL follow the snake_case English convention
  the existing five use; `None` fields SHALL be omitted from the
  JSONL line (existing convention).
- **ADDED:** New emit methods on `EventLogger`: `emit_ble_seen`,
  `emit_ble_left`, `emit_bonjour_seen`, `emit_bonjour_left`,
  `emit_lan_seen`, `emit_lan_left`, `emit_lan_dhcp_rotation`. Each
  flushes after write, same crash-safety contract as today.

### `bluetooth-scanning` — emission contract

- **ADDED:** `BLEPoller` SHALL emit `BLEDeviceSeenEvent` the first
  time a device's `identifier` enters its tracked state map (post
  rotation-folding). No debounce — every first-seen MAC fires one
  event.
- **ADDED:** `BLEPoller` SHALL emit `BLEDeviceLeftEvent` when a
  tracked device's `last_seen` falls more than the existing TTL
  (advertising: ~60 s default; connected: prune-on-sentinel)
  behind the current snapshot.

### `mdns-scanning` — emission contract

- **ADDED:** `BonjourPoller` SHALL emit `BonjourServiceSeenEvent`
  in the same path that pushes a new `(type, name)` into `_state`
  (the `add_service` callback path AND the `update_service` path
  when the entry didn't previously exist).
- **ADDED:** `BonjourPoller` SHALL emit `BonjourServiceLeftEvent`
  in the same path that removes an entry from `_state` (both the
  `remove_service` callback path AND the TTL backstop path).

### `lan-inventory` — emission contract

- **ADDED:** `LANInventoryPoller` SHALL emit `LANHostSeenEvent`
  when a new MAC (not self, not gateway) enters `_state` via the
  ARP-merge path. Self and gateway are explicitly excluded — they
  would generate a noise event on every diting launch.
- **ADDED:** `LANInventoryPoller` SHALL emit `LANHostLeftEvent`
  when a tracked MAC's `last_reachable_at` is older than the
  configurable `_HOST_LEFT_TIMEOUT_S` (default 300 seconds) AND
  the MAC is no longer in the latest ARP triples. The event is
  emitted once per departure; the entry is then dropped from
  `_state`.
- **ADDED:** `LANInventoryPoller` SHALL emit
  `LANHostDHCPRotationEvent` when an existing tracked MAC is
  observed at a new IP (the existing DHCP-rotation merge path).
  Fires before the merge updates the entry's `ip` field.

### `tui-shell` — EventsScreen filter cycle extension

- **MODIFIED:** EventsScreen's filter cycle SHALL accept eight
  buckets instead of five: `all`, `roam`, `rf_stir`, `latency`
  (latency + loss), `link_state`, `ble`, `bonjour`, `lan`. Keys
  `0` through `7` correspond to the eight buckets in order.
- **MODIFIED:** EventsPanel's `append_event` SHALL format the
  seven new event types with their own type-prefix tags:
  `[BLE]` / `[BJ]` / `[LAN]` (followed by a short human label —
  e.g. `[BLE] device joined: Apple, Inc. · Magic Keyboard`).

## Out of Scope

The following are NOT in this change — file follow-up proposals
when surfaced:

- **Debouncing** (require N seconds of stable presence before
  emitting `seen`). User explicitly chose "record everything" so
  one-pass ghost MACs DO emit events. If JSONL volume becomes a
  problem on dense networks, a `DITING_EVENT_DEBOUNCE_S` env-var
  can opt into a debounce window in a future change.
- **Cross-session aggregation** (Track A2 — hour-of-day heatmap,
  per-network breakdown, daily trend). Separate proposal.
- **LLM-bridge export** (Track B). Separate proposal.
- **Anonymization at JSONL write time.** SSIDs / MACs / IPs go to
  disk verbatim today; an opt-in anonymizer for `--for-llm`
  arrives with Track B.

## Migration / Defaults

This is additive. Existing JSONL logs remain readable; new event
types appear only in logs written by the new build. The analyzer
(`diting analyze`) treats unknown event types as benign passthrough
already, so reading a new-format log with an old build degrades
gracefully (the new event types just won't surface in the report,
but won't crash). The reverse — reading an old-format log with a
new build — is fully supported.

JSONL files grow more verbose, particularly on dense networks
(office floors, hotel lobbies, conferences). Users running
`diting --log /path/file.jsonl` on busy environments should expect
~5-10× more lines than v1.3.0; we'll measure this and document it
in the README before release.
