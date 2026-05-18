## MODIFIED Requirements

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
Each modal SHALL be opened via `app.push_screen(...)` and SHALL close on Esc, `q`, or the same key that opened it. The five bundled modals — HelpScreen (`?`), BasicsScreen (`b`), EventsScreen (`m`), BLEDetailScreen (`i`), **LANDetailScreen (`i`)** — all follow this convention. Modals SHALL render center-middle with a heavy-bordered box and a footer hint listing the close keys.

The `h` key SHALL NOT be bound to any action; the slot is reserved for a future per-view binding without colliding with the global help shortcut.

The `i` keystroke is **view-contextual**: on Wi-Fi it opens `WifiDetailScreen`, on BLE it opens `BLEDetailScreen`, on Bonjour it opens `BonjourDetailScreen`, on **LAN** it opens `LANDetailScreen`. Each detail modal closes via `Esc` / `i` / `q`.

#### Scenario: User opens LAN detail on a row
- **WHEN** the user is on the LAN view, presses `down` to land on a row, then presses `i`
- **THEN** `LANDetailScreen` pushes onto the stack; the underlying view stays mounted; pressing `i` or `Esc` closes the modal back to the LAN view with the cursor row preserved

#### Scenario: User opens help, reads, closes
- **WHEN** the user presses `?` then `Esc`
- **THEN** HelpScreen pushes onto the stack, the underlying view stays mounted underneath, Esc pops it back to the main view

#### Scenario: User opens BLE detail, presses `i` to close
- **WHEN** the user presses `i` on a BLE row, then `i` again
- **THEN** BLEDetailScreen pushes, then pops; the cursor row is unchanged

#### Scenario: Pressing `h` is a no-op
- **WHEN** the user presses `h` from any view
- **THEN** nothing happens; the key is intentionally unbound so it is free for a future shortcut without colliding with the global help binding

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
