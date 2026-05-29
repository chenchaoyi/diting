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

- `[BLE] device seen: <vendor> · <label>`
- `[BLE] device left: <vendor> · <label> · <duration>`
- `[BJ] service seen: <category> · <host>` (or `(unknown)` when category blank)
- `[BJ] service left: <category> · <host> · <duration>`
- `[LAN] host seen: <vendor> · <name-or-ip>` (`name` = bonjour_name OR hostname OR IP)
- `[LAN] host left: <vendor> · <name-or-ip> · <duration>`
- `[LAN] <vendor> · <name-or-ip> moved <previous_ip> → <new_ip>`

The `<label>` (name slot) for the two `[BLE]` formats SHALL follow the **same name cascade as the BLE list row** (`_ble_row_line`), via a single shared resolver so the two paths cannot drift: helper `name` → `(rotating ID)` when the name is a high-entropy rotating identifier → `device_type` (e.g. *Find My target*) → `device_class` (e.g. *iPhone*) → `(unknown)` as the terminal fallback (the name slot NEVER renders `(anonymous)`).

The `<vendor>` slot SHALL mirror the BLE list's vendor cell: the resolved vendor when present; otherwise `(anonymous)` ONLY when the event carries no vendor, no name, no `device_type`, no `device_class`, and no service categories (the `is_silent_device` definition, approximated from the event's own fields); otherwise `(unknown)`. This places `(anonymous)` in the same conceptual slot as the BLE list (the vendor cell) and makes `(anonymous)` mean exactly one thing — zero identifying information — across the diagnostic strip, the BLE list, and the events surface.

The verb "seen" — not "joined" — matches the canonical event type names (`ble_device_seen`, `bonjour_service_seen`, `lan_host_seen`) and the ZH translation (`出现` ≈ "appeared / seen"). These events fire on passive first observation (strangers' phones walking past, mDNS announces on the link, ARP cache entries appearing), NOT on a deliberate user-initiated association.

Each rendered line SHALL be at most one terminal row even on narrow widths; rendering SHALL use `fit_cells` for the long-name segment.

#### Scenario: BLE seen line with helper name
- **WHEN** a `BLEDeviceSeenEvent` with `name="Magic Keyboard"`, `vendor="Apple, Inc."` flows through `append_event`
- **THEN** the EventsPanel surfaces a line `[BLE] device seen: Apple, Inc. · Magic Keyboard`

#### Scenario: BLE seen line falls back to decoded class, not (anonymous)
- **WHEN** a `BLEDeviceSeenEvent` with `name=None`, `vendor="Apple, Inc."`, `device_type=None`, `device_class="iPhone"` flows through `append_event`
- **THEN** the line is `[BLE] device seen: Apple, Inc. · iPhone` — NOT `· (anonymous)`

#### Scenario: BLE seen line uses (unknown) when vendor known but nothing else
- **WHEN** a `BLEDeviceSeenEvent` with `name=None`, `vendor="HUAWEI Technologies"`, `device_type=None`, `device_class=None`, `service_categories=()` flows through `append_event`
- **THEN** the line is `[BLE] device seen: HUAWEI Technologies · (unknown)` — `(anonymous)` is reserved for the zero-information case

#### Scenario: BLE seen line is (anonymous) only when truly silent
- **WHEN** a `BLEDeviceSeenEvent` with `name=None`, `vendor=None`, `device_type=None`, `device_class=None`, `service_categories=()` flows through `append_event`
- **THEN** the line is `[BLE] device seen: (anonymous) · (unknown)` — `(anonymous)` occupies the vendor slot (mirroring the BLE list vendor cell + the diagnostic strip's `is_silent_device` count), the name slot falls back to `(unknown)`

#### Scenario: LAN DHCP rotation line
- **WHEN** a `LANHostDHCPRotationEvent` with `mac="de:ad:be:ef:00:01"`, `vendor="Apple, Inc."`, `bonjour_name="ccy-MBP24-M4-Office"`, `previous_ip="192.168.1.42"`, `new_ip="192.168.1.77"` flows through `append_event`
- **THEN** the line is `[LAN] Apple, Inc. · ccy-MBP24-M4-Office moved 192.168.1.42 → 192.168.1.77`

## ADDED Requirements

### Requirement: EventsScreen SHALL fold at-launch BLE seens into one expandable summary row
The `EventsScreen` modal (`m`) SHALL collapse each contiguous run of `BLEDeviceSeenEvent`s carrying `at_launch=True` into a single **summary row** in place of the individual rows, so the startup census does not bury genuine mid-session transitions. The fold SHALL be render-only: the underlying `EventRing` and the JSONL log SHALL retain every individual event. Nothing SHALL be hidden — the summary row SHALL be expandable to reveal every folded event.

The summary row SHALL render the count and a vendor breakdown: `session start · {N} devices already present` followed by the top vendors by descending count (e.g. `(Apple, Inc. ×8 · Microsoft ×5 · …)`), capping the inline breakdown at the top three vendors with a trailing `· …` when more exist. Folded seens with no resolvable vendor SHALL count under `(unknown)` / `(anonymous)` per the same placeholder rule as the per-row format.

Pressing Enter or `→` in `EventsScreen` SHALL toggle the at-launch census between collapsed (the summary row only) and expanded (the summary row followed by the individual cascade-formatted rows rendered in place beneath it). The default state SHALL be collapsed. The summary row SHALL carry an inline hint communicating the affordance (`enter to expand` when collapsed, `enter to collapse` when expanded). When no at-launch census fold exists, Enter/`→` SHALL be a no-op.

Post-launch BLE seens (`at_launch=False`), all `BLEDeviceLeftEvent`s, and all non-BLE events SHALL render individually as before — only the at-launch census run is folded. The fold SHALL be orthogonal to the `[5] BLE` filter bucket (the bucket filters by event type; the fold still applies within it). When the active filter excludes BLE seens, no summary row SHALL appear.

#### Scenario: At-launch census folds to one row
- **WHEN** the session start produced 20 `BLEDeviceSeenEvent`s with `at_launch=True` (8 Apple, 5 Microsoft, 7 others) and the user opens `EventsScreen`
- **THEN** the modal shows a single collapsed summary row `session start · 20 devices already present (Apple, Inc. ×8 · Microsoft ×5 · …)` in place of the 20 individual rows; the genuine post-launch events render below it individually

#### Scenario: Expanding the summary reveals every folded device
- **WHEN** the user presses Enter (or `→`) in `EventsScreen`
- **THEN** the summary row's hint flips to `enter to collapse` and the 20 individual cascade-formatted BLE-seen rows render beneath it; pressing Enter again re-collapses to the summary alone

#### Scenario: Mid-session arrival is never folded
- **WHEN** a device first appears and graduates at session minute 5 (so its `BLEDeviceSeenEvent.at_launch == False`)
- **THEN** its row renders individually in `EventsScreen`, outside any census summary row

#### Scenario: JSONL log is unaffected by the fold
- **WHEN** 20 at-launch seens fold into one summary row in the modal AND a `--log` sink is active
- **THEN** the JSONL file contains all 20 `ble_device_seen` lines (each with `at_launch:true`); the fold changed only the modal rendering
