# tui-shell Specification

## Purpose

Defines the diting TUI's top-level layout — the four-panel
arrangement (Connection / Diagnostics / Scan-or-BLE / Events), the
view-toggle mechanic that swaps Wi-Fi scan vs BLE list in place, the
modal-screen lifecycle, and the GroupedFooter convention. Capability
specs for the panel CONTENTS (wifi-scanning, bluetooth-scanning,
link-health, etc.) ride on top of this layout contract.
## Requirements
### Requirement: The TUI SHALL have exactly four stacked panels in a fixed order
The third-slot panel SHALL cycle through four views in this order: **Wi-Fi** → **BLE** → **Bonjour** → **LAN**, wrapping back to Wi-Fi. The `n` keystroke advances the cycle by one. The current view's panel SHALL be visible; the other three SHALL have `display=False` so the layout never reflows on toggle.

The fourth view's panel header is `LAN`. The cycle's stop labels (in both EN and ZH catalogs) are: `Wi-Fi`, `BLE`, `Bonjour`, `LAN`.

The LAN view's content rendering follows the existing lazy-poller pattern:

- **Before the first snapshot lands:** the panel renders a single dim-italic placeholder line `(sweeping subnet…)` (EN) / `(正在扫描子网…)` (ZH). The placeholder disappears as soon as the first `LANInventoryUpdate` snapshot lands.
- **After the first snapshot lands:** the panel renders one row per `LANHost` from the latest snapshot, sorted by IP ascending, with `is_self` and `is_gateway` hosts pinned to the top in that order with a `★` star marker.

#### Scenario: User cycles through all four views
- **WHEN** the user presses `n` four times starting from the Wi-Fi view
- **THEN** the third-slot panel cycles Wi-Fi → BLE → Bonjour → LAN → Wi-Fi; each panel renders its own contents; the Diagnostics panel's content tracks the active view

#### Scenario: User cycles into the LAN view before the first snapshot
- **WHEN** the user lands on the LAN view and the first sweep is still in flight
- **THEN** the LAN panel body shows a single dim-italic line `(sweeping subnet…)`; the line is replaced by the rows table as soon as the first snapshot arrives

### Requirement: Diagnostics panel content SHALL follow the active view
When the active view is `lan`, the Diagnostics panel SHALL render a LAN-side summary:

1. **Visible LAN inventory** — total host count, named-via-Bonjour count, unknown-vendor count.
2. **Subnet** — CIDR notation, with `· capped from /N` annotation when the netmask was wider than the effective cap (/24 by default, /22 with `DITING_LAN_INVENTORY_WIDE=1`).
3. **Last sweep** — relative time since the most recent ARP read.

Before the first snapshot lands the Diagnostics panel SHALL show a single dim-italic line `(sweeping subnet…)` instead of any of the above.

#### Scenario: User in LAN view, first snapshot has arrived
- **WHEN** the LAN poller has snapshot `hosts=17`, `named=4`, `unknown_vendor=2`, `subnet=192.168.1.0/24`, `last_sweep_at=8s ago`
- **THEN** Diagnostics renders `LAN inventory  17 hosts · 4 named (Bonjour) · 2 unknown vendor · subnet 192.168.1.0/24 · last sweep 8s ago`

#### Scenario: User in LAN view, no snapshot yet
- **WHEN** the LAN poller has been constructed but no `LANInventoryUpdate` has been emitted yet
- **THEN** Diagnostics renders one dim-italic line `(sweeping subnet…)`

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

#### Scenario: User opens LAN detail on a never-reached host
- **WHEN** the user opens LANDetailScreen on a row whose `last_rtt_ms=None` and `last_reachable_at=None` (kernel ARP entry pre-existing from before diting started, host has since gone offline)
- **THEN** the Network section's Latency row is omitted; the Reachable row renders `never`

#### Scenario: User opens LAN detail on a host with no Bonjour services
- **WHEN** the user opens LANDetailScreen on a row whose `bonjour_services` is empty
- **THEN** the Bonjour services section header is still rendered, followed by a single dim-italic line `(no Bonjour services)`; the section is NOT omitted entirely

#### Scenario: User opens help, reads, closes
- **WHEN** the user presses `?` then `Esc`
- **THEN** HelpScreen pushes onto the stack, the underlying view stays mounted underneath, Esc pops it back to the main view

#### Scenario: User opens BLE detail, presses `i` to close
- **WHEN** the user presses `i` on a BLE row, then `i` again
- **THEN** BLEDetailScreen pushes, then pops; the cursor row is unchanged

#### Scenario: Pressing `h` is a no-op
- **WHEN** the user presses `h` from any view
- **THEN** nothing happens; the key is intentionally unbound so it is free for a future shortcut without colliding with the global help binding

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

### Requirement: The footer SHALL be a single GroupedFooter with three semantic groups
`GroupedFooter` SHALL split the App's bindings into three groups
separated by `│` dividers, in this order:

1. **App** — `quit`, `pause`
2. **Scan / view** — `rescan`, `cycle sort`, `re-roam`, `toggle view`
3. **Modals** — `events`, `help`, `basics`

This grouping is more readable than Textual's flat default Footer
on a tool with eight bindings, and gives the user a faster path to
"is this an app control or a scan action?".

#### Scenario: User reads the footer
- **WHEN** they look at the bottom of the TUI
- **THEN** they see `quit  pause  │  rescan  sort  reroam  view  │  events  help  basics` (or the ZH equivalent)

### Requirement: Hidden bindings SHALL exist for power-user navigation
The footer SHALL only show the eight primary bindings. Additional
bindings — BLE row navigation (`up`, `down`, `enter`, `i`), modal
filter-cycling (`0`/`1`/`2`/`3`/`4` in the events modal),
scroll-within-modal — SHALL exist with `show=False` and SHALL be
documented in the help modal but NOT clutter the footer.

#### Scenario: User opens help to find arrow-key behavior
- **WHEN** they press `h`
- **THEN** the help modal lists every binding including the hidden ones

### Requirement: The header SHALL show title + clock; the subtitle SHALL describe the live state
The TUI SHALL render a custom `BrandHeader` widget at the top of
the screen — a four-row Horizontal container with the diting radar
mark on the left and a three-line title / subtitle / clock stack on
the right, separated from the panels below by a one-cell-tall
`tall` border in brand orange (`#fea62b`).

The radar mark SHALL be rendered with Unicode half-block characters
(`▀` / `█` / `▄`) in foreground `#fea62b`, matching the pixel grid
of `docs/design/diting-design/assets/logo-mark.svg`. The mark MUST
NOT be replaced by an icon font or PNG.

The right-hand stack SHALL render exactly three lines, top to
bottom:

1. The current local time as `HH:MM:SS`, right-aligned, dim-styled.
2. The App's `title` attribute (already pinned to `diting v<version>`
   by the version Requirement), bold-styled.
3. The App's `sub_title` attribute (the short live-updated string
   built by `_build_subtitle()` — `view: ... · scan Ns · PAUSED`
   when paused), dim-styled.

The header SHALL react to changes in `App.title` and `App.sub_title`
without explicit notification from the call site (i.e. the widget
watches those reactives and re-renders), so existing `self.sub_title
= ...` assignments continue to drive the live state.

#### Scenario: Title bar shows the brand mark + version + subtitle
- **WHEN** the user launches the TUI
- **THEN** the rendered top of the screen contains at least one Unicode half-block glyph (`▀`, `█`, or `▄`) on the left in brand orange
- **AND** the App's `title` text (`diting v<X.Y.Z>`) is visible to its right
- **AND** the App's `sub_title` text (`view: wifi · scan 7s` by default) is visible below the title
- **AND** a clock reading `HH:MM:SS` is right-aligned on the top row of the header

#### Scenario: User pauses polling
- **WHEN** the user presses `p`
- **THEN** the subtitle line of the header updates from `view: wifi · scan 7s` to `view: wifi · scan 7s · PAUSED` immediately, without the user pressing any other key
- **AND** the brand mark and title remain unchanged

#### Scenario: User toggles to BLE view
- **WHEN** the user presses `n` from the Wi-Fi view
- **THEN** the subtitle line updates from `view: wifi · ...` to `view: ble · ...`
- **AND** the brand mark and title remain unchanged

### Requirement: TUI visual language SHALL conform to the design system
The diting TUI and any UI-adjacent surface (README, marketing snapshots, modals, slide decks, docs site) SHALL conform to the design system at `docs/design/diting-design/`. That directory (`README.md`, `colors_and_type.css`, `SKILL.md`, `assets/`) is the single source of truth for visual language and copy voice. Reviewers MAY block any PR that introduces:

- a hex value not declared as a CSS custom property in
  `docs/design/diting-design/colors_and_type.css`
- a font face other than Fira Code or JetBrains Mono on a mono
  surface (TUI, snapshot title bars, code blocks)
- emoji in user-visible strings (Unicode glyphs like `σ`, `↔`,
  `⚠`, `▁▂▃▄▅▆▇█`, `→` ARE NOT emoji and ARE allowed)
- imports of icon libraries (Lucide, Heroicons, Material
  Symbols, etc.); the only mark is `docs/design/diting-design/assets/logo-mark.svg`
  (or the wordmark `logo.svg`)
- copy that capitalises the brand (`Diting`, `DITING`, `Wifiscope`)
  outside of shell env vars (`DITING_*`) where uppercase is
  required by the platform
- copy that uses first-person plural (`we`, `our`) where the
  brand voice is second-person (`you`)
- empty-state strings that are not parenthesised italic
  (`(scanning…)`, `(no APs from last scan — likely throttle, retrying)`)
- panel chrome that uses rounded "card" containers, gradients,
  drop shadows other than `--shadow-window` / `--shadow-modal`,
  or borders other than the heavy 1px orange box-drawing frame

The Requirement points at `docs/design/diting-design/` rather than
embedding hex values inline so future palette adjustments don't
require a spec amendment — the canonical file is the contract.

#### Scenario: A new PR adds an off-palette hex value to the TUI theme
- **WHEN** a PR introduces `color: "#3a92e8"` in `src/diting/tui.py`
- **AND** `#3a92e8` is not present anywhere in `docs/design/diting-design/colors_and_type.css`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL substitute a CSS custom property already declared in the design system or surface a real new-token request before merging

#### Scenario: A new PR adds an emoji to a help modal string
- **WHEN** a PR adds `t("📡 Scanning Wi-Fi…")` to `src/diting/i18n.py`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL replace the emoji with prose, a Unicode functional glyph (e.g. `σ`, `↔`), or remove the decoration entirely

#### Scenario: A new PR introduces a Lucide icon import to a Textual widget
- **WHEN** a PR adds `from textual_lucide import Icon` (or any equivalent icon library) anywhere under `src/diting/`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL either drop the icon or, if the surface genuinely needs a mark, use `docs/design/diting-design/assets/logo-mark.svg` for brand placement only

### Requirement: Each list-style view panel SHALL share the same row-select + inspect gesture contract
All four list-style view panels — Wi-Fi, BLE, Bonjour, **LAN** — SHALL implement the same row-cursor + inspect contract:

- `up` / `down` move the cursor among the panel's rows; the cursor highlights via row-level `reverse` styling.
- `enter` or `i` opens the detail modal for the selected row.
- A mouse click on a row selects + opens the modal in one gesture.
- The modal closes on `Esc` / `i` / `q`; the cursor row is preserved.

The LAN panel's row key for cursor tracking SHALL be the host's MAC (`mac.lower()`). When a tracked MAC drops out of the latest snapshot, the cursor SHALL clear gracefully — the next render's row is not assumed to exist.

#### Scenario: LAN cursor stable across re-sort
- **WHEN** the user selects a LAN row, then the next snapshot reshuffles row order (e.g. a host's `last_seen` updates and changes ordering)
- **THEN** the cursor stays on the same MAC's row, wherever it now sits

#### Scenario: LAN cursor target drops out of snapshot
- **WHEN** the selected MAC is not present in the next snapshot (host went silent and aged out)
- **THEN** the cursor clears; no exception is raised; the panel renders the new snapshot with no selection

### Requirement: The App title SHALL include the running version
`DitingApp.title` SHALL be set to `"diting v<version>"` where `<version>` is the value of `importlib.metadata.version("diting")`. The Textual header renders this on the left of the screen, so the user always sees the running version without pressing any key.

If `importlib.metadata.version("diting")` raises `PackageNotFoundError`, the title SHALL fall back to `"diting v0+unknown"` — the TUI MUST NOT fail to start.

#### Scenario: Title bar shows the running version
- **WHEN** the user launches the TUI
- **THEN** the App's `title` attribute equals `diting v<X.Y.Z>` where `<X.Y.Z>` matches the installed package version
- **AND** the version remains visible throughout the session — toggling views does not erase it

#### Scenario: Subtitle is unaffected
- **WHEN** the user toggles views or pauses polling
- **THEN** `sub_title` continues to render the existing session-state bits (`view: ... · scan Ns · PAUSED`)
- **AND** `title` remains `diting v<version>`

### Requirement: Wi-Fi-anchored event lines SHALL surface the affected SSID alongside the BSSID / AP-name
The Events panel's renderer for `RoamEvent` and `RFStirEvent` SHALL include the associated SSID (carried by the event itself) as part of the event line:

- `RoamEvent`: when `previous_ssid == new_ssid` (the common case — band switch within an ESS, or inter-AP roam keeping the same network) the line SHALL render a single `SSID: <name>` segment after the BSSID arrow. When the SSIDs differ the line SHALL render `SSID: <prev> → <new>` using the same arrow glyph as the BSSID pair. When both SSIDs are `None` OR both are `""` (hidden) the SSID segment SHALL be omitted entirely; `SSID: n/a` SHALL NOT appear.
- `RFStirEvent`: when `ssid` is a non-empty string the line SHALL append `· SSID <name>` after the location body. When `ssid` is `None` or `""` the segment SHALL be omitted.

AP-name rendering is unchanged: it continues to come from `format_bssid` (roam line) and `event.location` (rf_stir line), both of which read `aps.yaml` via `NetworkInventory`. SSID context is additive — a fully-populated `aps.yaml` keeps showing the friendly AP name, and an empty inventory keeps showing the cluster label / raw BSSID; both cases gain the SSID segment for free.

i18n: the new wrapper strings (`SSID: {ssid}`, `SSID: {prev} → {new}`, `SSID {ssid}`) SHALL be added to the EN + ZH catalogs.

#### Scenario: Roam between band siblings on the same SSID
- **WHEN** the event ring contains a `RoamEvent` with `previous_ssid="tedo"` and `new_ssid="tedo"`
- **THEN** the rendered line carries `SSID: tedo` exactly once, after the BSSID arrow segment

#### Scenario: Roam across two distinct SSIDs
- **WHEN** the event has `previous_ssid="home"` and `new_ssid="office"`
- **THEN** the rendered line carries `SSID: home → office`

#### Scenario: Roam with both SSIDs unknown (TCC redacted)
- **WHEN** the event has `previous_ssid=None` and `new_ssid=None`
- **THEN** the rendered line OMITS the SSID segment; the BSSID arrow segment renders unchanged

#### Scenario: Hidden SSID on both sides
- **WHEN** the event has `previous_ssid=""` and `new_ssid=""` (CoreWLAN returns empty string for hidden SSIDs)
- **THEN** the rendered line OMITS the SSID segment; empty strings are not surfaced as `SSID: `

#### Scenario: RF stir with a known SSID
- **WHEN** the event has `ssid="tedo_5G"` and `location="?af:5e:9d"`
- **THEN** the rendered line reads `?af:5e:9d 处 RF 扰动 σ 4.8 dB · 中 · SSID tedo_5G` (positions of i18n decorations may vary; the `SSID tedo_5G` segment is present)

#### Scenario: RF stir without an SSID
- **WHEN** the event has `ssid=None`
- **THEN** the rendered line is unchanged from the legacy (pre-enrichment) shape — the trailing `· SSID …` segment is absent


### Requirement: The subtitle SHALL include a scene chip
The `BrandHeader`'s subtitle line (rendered from `App.sub_title` / `_build_subtitle()`) SHALL include the active scene as a short chip alongside the existing view name and scan-interval indicator. The chip uses dim styling consistent with the rest of the subtitle.

Format (EN):

```
view: Wi-Fi · scan 7s · [home]
```

Format (ZH):

```
视图：Wi-Fi · 扫描间隔 7s · [家]
```

The chip text is the scene name in the active locale (EN catalog: `home` / `office` / `public` / `audit`; ZH catalog: `家` / `公司` / `公共` / `排查`). The square brackets are part of the format and are NOT locale-dependent.

The subtitle SHALL re-render when the active view or scan interval changes; the scene chip itself never changes during a session (scene is fixed at startup), but it MUST be re-rendered with the subtitle to remain visible after each refresh.

#### Scenario: EN home scene chip
- **WHEN** `diting --scene home` is launched in an EN locale
- **THEN** the subtitle reads `view: Wi-Fi · scan 7s · [home]`

#### Scenario: ZH office scene chip
- **WHEN** `diting --scene office --lang zh` is launched
- **THEN** the subtitle reads `视图：Wi-Fi · 扫描间隔 7s · [公司]`

#### Scenario: Audit scene visible in title
- **WHEN** `diting --scene audit` is launched
- **THEN** the subtitle includes `[audit]` (EN) or `[排查]` (ZH) — a fast visual indicator that all gating is disabled

### Requirement: Scene classification SHALL print a one-line banner at startup
When the scene was resolved by `scenes.yaml` lookup or by the auto-detect heuristic (i.e. `scene_source ∈ {yaml, auto}`), diting SHALL print exactly one line to **stderr** before launching the TUI / monitor, explaining the choice. The banner format is:

EN:
- `auto-detected scene: <scene> (<reason>)` — for source `auto`
- `pinned scene: <scene> (matched "<key>" in scenes.yaml)` — for source `yaml`
- `scene: home (default — no Wi-Fi connection at startup)` — for source `default` when no connection is available

ZH equivalents in the matching catalog. The banner SHALL go to **stderr** (not stdout) so that `diting monitor > out.jsonl` streams stay clean. When `DITING_SCENE_QUIET=1` is set, the banner SHALL be suppressed (for users / scripts that want silent startup).

When the scene was resolved by `--scene` flag or `DITING_SCENE` env var (source `cli` or `env`), NO banner is printed — the user already knows what they asked for.

The banner SHALL fire exactly once per session, before the TUI's alt-screen takes over (so it stays visible in the shell's scroll-back after diting exits).

#### Scenario: auto-detect banner names the reason
- **WHEN** diting launches on a WPA2 Enterprise network without `--scene` / env / yaml
- **THEN** stderr carries one line: `auto-detected scene: office (WPA2 Enterprise auth)`

#### Scenario: scenes.yaml hit banner names the match key
- **WHEN** `scenes.yaml` contains `{ ssid: Meituan, scene: office }` and diting launches connected to `Meituan`
- **THEN** stderr carries one line: `pinned scene: office (matched "Meituan" in scenes.yaml)`

#### Scenario: explicit `--scene` is silent
- **WHEN** diting launches with `--scene office`
- **THEN** no scene banner is printed

#### Scenario: DITING_SCENE_QUIET=1 suppresses the banner
- **WHEN** `DITING_SCENE_QUIET=1 diting` is invoked on a WPA2 Enterprise network
- **THEN** the scene is still resolved to `office` (auto), the chip still shows in the TUI, but no banner is printed

### Requirement: EventsScreen SHALL collapse consecutive duplicate BLE-seen rows under a `×N` group
The EventsScreen modal renderer SHALL group runs of consecutive `BLEDeviceSeenEvent` entries whose `(vendor, name_label)` tuple is identical into a single rendered row with a `×N` suffix, where `N` is the count of folded rows. Grouping SHALL apply ONLY to the EventsScreen modal render path; the underlying `EventRing` ordering, the `BLEDeviceSeenEvent` data class, and the JSONL log on disk SHALL be unchanged.

Source-side dedup on `BLEDeviceSeenEvent` is correct per `identifier` — one event per privacy-rotated UUID. Apple Continuity and Microsoft CDP rotate identifiers continuously, so a single physical device (Find-My beacon, MS CDP advertiser, Huami fitness band) emits a fresh `BLEDeviceSeenEvent` on every rotation. Over a ~90-second capture in a dense office, the events modal becomes a flood of `device seen: Apple, Inc. · (anonymous)` / `Microsoft · (anonymous)` lines that drown out the events the user actually wants to see (roam, link drop, DHCP rotation, LAN host arrival).

The EventsScreen modal renderer SHALL group runs of consecutive `BLEDeviceSeenEvent` entries whose `(vendor, name_or_anonymous_label)` tuple is identical into a single rendered row with a `×N` suffix appended after the existing summary text, where `N` is the count of folded rows including the first. The timestamp displayed SHALL be the timestamp of the FIRST event in the run (earliest); a `→ HH:MM:SS` continuation marker SHALL be appended to indicate the most-recent timestamp in the run when `N ≥ 2`.

Grouping SHALL be strictly *consecutive* — any non-`BLEDeviceSeenEvent` row, OR any `BLEDeviceSeenEvent` with a different `(vendor, name_or_anonymous_label)` tuple, SHALL terminate the run. The relative ordering of heterogeneous events is preserved. No row order is rearranged to maximise grouping.

The `name_or_anonymous_label` SHALL be:
- the literal string `(anonymous)` when the event's stored device name field is `None` or empty
- the rendered `(rotating ID)` placeholder when the device name would have been substituted in the BLE list per the `bluetooth-scanning` rotating-identifier guard
- the verbatim name otherwise

Grouping SHALL apply ONLY to the EventsScreen modal render path. The underlying `EventRing` ordering, the `BLEDeviceSeenEvent` data class, and the JSONL log on disk SHALL be unchanged. Reads of the JSONL log by `diting analyze` and external consumers see every individual event as before.

Filter buckets (the `0`-`7` filter cycle defined in the prior EventsScreen requirement) SHALL apply BEFORE grouping. Switching to the `[1] roam` bucket suppresses BLE events entirely and shows no `×N` grouping for non-BLE rows. Switching back to `[5] ble` reapplies grouping over the BLE-only filtered list.

#### Scenario: Three consecutive identical Apple-anonymous BLE-seen events
- **WHEN** the modal renders an `EventRing` whose tail contains three `BLEDeviceSeenEvent`s with `(vendor="Apple, Inc.", name=None)` at `18:10:33`, `18:10:34`, `18:10:36`, followed by an unrelated `roam` event
- **THEN** the modal renders one line `18:10:33  [BLE]  device seen: Apple, Inc.  ·  (anonymous)  ×3  → 18:10:36` followed by the `[ROAM]` line in its original position

#### Scenario: Two BLE-seen events for different vendors do not fold
- **WHEN** the ring has `(Apple, Inc., None)` at `18:10:33` then `(Microsoft, None)` at `18:10:34`
- **THEN** both rows render separately with no `×N` suffix on either

#### Scenario: Non-BLE event breaks the run
- **WHEN** the ring has three identical `(Apple, Inc., None)` BLE-seen rows interleaved as `seen, seen, roam, seen`
- **THEN** the first two BLE rows render as one folded `×2` row, the `roam` renders as its own row, and the trailing BLE row renders as a standalone (no `×N`) row

#### Scenario: Rotating-ID name folds with itself
- **WHEN** the ring has two BLE-seen events with `(vendor="Apple, Inc.", name="NZ1NhvIw3H5T5cSy3kULrJ")` followed by a third with `(vendor="Apple, Inc.", name="Mc7g8sUZpL0eX2qY4Wt1Pq")` (different rotating ID per identifier)
- **THEN** both rows render under a single `(rotating ID) ×3` group, because the rendered label is `(rotating ID)` for all three — the substitution happens before equality comparison

#### Scenario: JSONL log is untouched
- **WHEN** ten identical `(Apple, Inc., None)` BLE-seen events fire over five seconds and the user is logging with `--log /tmp/diting.jsonl`
- **THEN** `/tmp/diting.jsonl` contains ten distinct `ble_device_seen` lines, one per event, each with its own timestamp — grouping is modal-only

#### Scenario: Filter to roam, then back to BLE
- **WHEN** the user presses `1` (roam filter), then `5` (BLE filter) with the same underlying ring
- **THEN** the roam filter renders only roam rows with no folding; switching to BLE recomputes folding from scratch over only the BLE rows
