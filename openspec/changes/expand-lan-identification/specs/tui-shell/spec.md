## MODIFIED Requirements

### Requirement: Modal screens SHALL push onto a stack and Esc / their own letter SHALL close
Each modal SHALL be opened via `app.push_screen(...)` and SHALL close on Esc, `q`, or the same key that opened it. The bundled modals — HelpScreen (`?`), BasicsScreen (`b`), EventsScreen (`m`), BLEDetailScreen (`i`), LANDetailScreen (`i`), **LANProbeConsentScreen (`P`)** — all follow this convention. Modals SHALL render center-middle with a heavy-bordered box and a footer hint listing the close keys.

The `h` key SHALL NOT be bound to any action; the slot is reserved for a future per-view binding without colliding with the global help shortcut.

The `i` keystroke is **view-contextual**: on Wi-Fi it opens `WifiDetailScreen`, on BLE it opens `BLEDetailScreen`, on Bonjour it opens `BonjourDetailScreen`, on **LAN** it opens `LANDetailScreen`. Each detail modal closes via `Esc` / `i` / `q`.

`LANDetailScreen` SHALL render five sections:

1. **Identity** — Name, Class (when `device_class` is non-None), Vendor (normalized display), Vendor (IEEE) (dim continuation line with the raw IEEE registry string when `vendor_raw != vendor`), **Model** (when `upnp_model` is non-None, falling back to a parenthesised "(year)" / "(generation)" substring of `upnp_friendly_name` when that contains one), Role (when self or gateway).
2. **Network** — IP, MAC, Reverse DNS (when present), **Latency** (when `last_rtt_ms` is known), **TTL** (when `ttl` is known, format `<value> (<class>)` e.g. `64 (unix)`), **Reachable** (always rendered).
3. **Active discovery** — NBNS name, UPnP server header, UPnP friendly name, UPnP model. Section header is always rendered when active probing has run for this host; lines are omitted individually when their respective field is None. When no active-discovery field is populated, render a single dim-italic placeholder line `(not probed)` (EN) / `（未主动探测）` (ZH).
4. **Bonjour services** — list of category names when `bonjour_services` is non-empty; otherwise a single dim-italic placeholder line `(no Bonjour services)` (EN) / `（无 Bonjour 服务）` (ZH).
5. **Activity** — First seen, Last seen. When `(now - first_seen) < 24 h`, the First-seen value SHALL be styled bold to surface freshness.

The **Latency** row SHALL render `XX.X ms` from `last_rtt_ms`. When `last_rtt_ms` is None the row SHALL be omitted.

The **Reachable** row SHALL render:
- `this sweep` (EN) / `此次扫描` (ZH) when `last_reachable_at` is within the last sweep cadence
- A relative duration via `_format_duration_short` when older
- `never` (EN) / `从未` (ZH) when `last_reachable_at` is None

#### Scenario: User opens LAN detail on a row
- **WHEN** the user is on the LAN view, presses `down` to land on a row, then presses `i`
- **THEN** `LANDetailScreen` pushes onto the stack; the underlying view stays mounted; pressing `i` or `Esc` closes the modal back to the LAN view with the cursor row preserved

#### Scenario: User opens LAN detail on a host with known latency and TTL
- **WHEN** the user opens LANDetailScreen on a row whose `last_rtt_ms=2.4`, `ttl=64`, `ttl_class="unix"`, and `last_reachable_at` is within the last sweep cadence
- **THEN** the Network section renders `Latency 2.4 ms`, `TTL 64 (unix)`, `Reachable this sweep`

#### Scenario: User opens LAN detail on a host with NBNS + UPnP enrichment
- **WHEN** the user opens LANDetailScreen on a host whose `nbns_name="LAB-PRINTER-01"`, `upnp_server="Linux/3.10 UPnP/1.0 HiSense"`, `upnp_friendly_name="Living Room TV"`, `device_class="tv"`
- **THEN** the Identity section's Class row renders `Class: tv`; the Model row renders `Model: Living Room TV` (from `upnp_friendly_name` when `upnp_model` is None); the Active discovery section renders `NBNS LAB-PRINTER-01`, `UPnP server Linux/3.10 UPnP/1.0 HiSense`, `Friendly name Living Room TV`

#### Scenario: User opens LAN detail when no probe has run for that host
- **WHEN** the user opens LANDetailScreen on a row whose four active-discovery fields are all None
- **THEN** the Active discovery section header is rendered, followed by a single dim-italic line `(not probed)` (EN) / `（未主动探测）` (ZH)

#### Scenario: First-seen bold when fresh
- **WHEN** the user opens LANDetailScreen on a row whose `first_seen` is 4 hours ago
- **THEN** the Activity section's First seen value is rendered in bold (signalling freshness); when the row is 48 hours old the value is rendered in the normal style

## ADDED Requirements

### Requirement: The LAN row SHALL include a one-cell Class column and prepend `[new]` chip for hosts new today
The LAN panel's row layout SHALL gain a new fixed-width Class column inserted as the **leftmost data column** (immediately after the optional `[new]` chip and immediately before the existing Vendor column). The column SHALL be `_COL_LAN_CLASS = 8` cells wide and render `LANHost.device_class` (or the empty string when None).

The final row layout (left → right) SHALL be:

```
[new]  class    vendor              name                    IP               MAC                last seen
```

Rationale: putting class first follows the Fing UX reference (design D14) — Type is the column users scan first; the same vendor (e.g. H3C) can be a router / AP / switch / IoT bridge, and the class disambiguates faster than vendor.

Rows whose `(now - first_seen) < 24 h` SHALL be prefixed with a `[new]` (EN) / `[新]` (ZH) chip in the existing dim-cyan style used by other subtitle chips. The chip prepends to the row line before the Class column. Rows older than 24 h SHALL NOT carry the chip.

The column-header line SHALL be extended to place the new Class column header (`class`) before the Vendor column header (`vendor`).

#### Scenario: Row for a TV first seen 2 hours ago
- **WHEN** the LAN poller emits a snapshot where one host has `first_seen` 2 h ago, `device_class="tv"`, `vendor="Hisense"`, `nbns_name="LIVING-ROOM-TV"`
- **THEN** the row line begins with `[new]` (in dim cyan), followed by `tv` (class), then `Hisense` (vendor), then `LIVING-ROOM-TV` (name), then IP, MAC, age

#### Scenario: Row for an IP camera
- **WHEN** the LAN poller emits a snapshot where one host has `device_class="camera"`, `vendor="Hikvision"`, `nbns_name=None`, `upnp_friendly_name="DS-2CD2143G2-IU"`
- **THEN** the row's Class column renders `camera`; the Vendor column renders `Hikvision`; the Name column renders `DS-2CD2143G2-IU`

#### Scenario: Row for a smart-home gateway
- **WHEN** the LAN poller emits a snapshot where one host has `device_class="smart-home"`, `vendor="Tuya"`
- **THEN** the row's Class column renders `smart-home`

#### Scenario: Row for an old host with no class
- **WHEN** the LAN poller emits a snapshot where one host has `first_seen` 48 h ago and `device_class=None`
- **THEN** the row does NOT carry the `[new]` chip; the Class column renders as empty padding (column width preserved)

### Requirement: The LAN view SHALL bind uppercase `P` to a public-scene one-shot active probe consent modal
When the active scene is `public` AND `DITING_LAN_PROBE` is unset (i.e. active probing is currently off in this scene), the LAN view SHALL bind uppercase `P` to `app.push_screen(LANProbeConsentScreen(...))`. The key SHALL be a no-op when probing is already enabled (home/office/audit scenes, or `DITING_LAN_PROBE=1`).

`LANProbeConsentScreen` SHALL render center-middle with a heavy-bordered box and SHALL display:

1. The current scene (`Scene: public`) and the connected SSID (`Network: <ssid>` or `Network: (disassociated)`).
2. An enumeration of the exact UDP packets that will be sent: `NBNS UDP 137 unicast`, `SSDP M-SEARCH UDP 1900 multicast`, `mDNS UDP 5353 multicast`.
3. A consequences statement listing: "other guests' devices receive your probes", "hotel / airport IDS may flag this as scanning", "captive portals may rate-limit or disconnect".
4. A "One-shot probe. Re-confirm next time." line.
5. A footer with `[ esc cancel ]   [ y probe now ]`.

The `y` confirm key SHALL be **inactive** for the first 2 seconds the modal is open. During the cooldown the footer SHALL render `[ esc cancel ]   [ wait 2s ]` (with the second button in dim style). After the cooldown the second button SHALL render `[ y probe now ]` in normal style. Pressing `y` during the cooldown SHALL be silently ignored.

On `y` after cooldown, the modal SHALL:

1. Append a `LANActiveProbeConsentedEvent` to the JSONL log via `EventLogger.emit_lan_active_probe_consented(...)`.
2. Set the poller's `_one_shot_probe_armed` flag to True.
3. Call `poller.force_now()` to schedule an immediate sweep.
4. Close the modal.

On `esc` the modal SHALL close without side effect.

While `_one_shot_probe_armed` is True, the LAN view's subtitle SHALL include a `[probing]` (EN) / `[探测中]` (ZH) chip in the same style as other subtitle chips. The chip SHALL be removed after the probe sweep completes and the resulting `LANInventoryUpdate` lands.

#### Scenario: User confirms after cooldown
- **WHEN** active scene is `public`, the LAN view is focused, the user presses `P`, waits 2 s, presses `y`
- **THEN** the modal closes; a `lan_active_probe_consented` JSONL line is emitted; the LAN subtitle gains a `[probing]` chip; the next sweep runs NBNS + SSDP + mDNS-meta once; after that sweep's snapshot lands, the chip is removed

#### Scenario: User press-throughs are ignored during cooldown
- **WHEN** the user presses `P` and then `y` within 500 ms
- **THEN** no event is logged, no probe runs, the modal stays open in the cooldown state

#### Scenario: User cancels with esc
- **WHEN** the user presses `P` then `esc` at any point (before or after cooldown)
- **THEN** the modal closes; no event is logged; no probe runs; `_one_shot_probe_armed` stays False

#### Scenario: P binding inactive in home scene
- **WHEN** active scene is `home` and the user presses `P` in the LAN view
- **THEN** nothing happens (no modal, no event); scene-default probing already runs every sweep

#### Scenario: P binding inactive when env override on
- **WHEN** active scene is `public` BUT `DITING_LAN_PROBE=1` is set in the environment
- **THEN** `P` does nothing because probing is already running every sweep
