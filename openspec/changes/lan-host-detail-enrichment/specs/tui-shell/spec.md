## MODIFIED Requirements

### Requirement: Modal screens SHALL push onto a stack and Esc / their own letter SHALL close
Each modal SHALL be opened via `app.push_screen(...)` and SHALL close on Esc, `q`, or the same key that opened it. The five bundled modals — HelpScreen (`?`), BasicsScreen (`b`), EventsScreen (`m`), BLEDetailScreen (`i`), **LANDetailScreen (`i`)** — all follow this convention. Modals SHALL render center-middle with a heavy-bordered box and a footer hint listing the close keys.

The `h` key SHALL NOT be bound to any action; the slot is reserved for a future per-view binding without colliding with the global help shortcut.

The `i` keystroke is **view-contextual**: on Wi-Fi it opens `WifiDetailScreen`, on BLE it opens `BLEDetailScreen`, on Bonjour it opens `BonjourDetailScreen`, on **LAN** it opens `LANDetailScreen`. Each detail modal closes via `Esc` / `i` / `q`.

`LANDetailScreen` SHALL render four sections:

1. **Identity** — Name, Vendor, Role (when self or gateway).
2. **Network** — IP, MAC, Reverse DNS (when present), **Latency** (when `last_rtt_ms` is known), **Reachable** (always rendered).
3. **Bonjour services** — list of category names when `bonjour_services` is non-empty; otherwise a single dim-italic placeholder line `(no Bonjour services)` (EN) / `（无 Bonjour 服务）` (ZH). The section is always shown so the user has a clear signal that the cross-reference channel was checked.
4. **Activity** — First seen, Last seen.

The **Latency** row SHALL render `XX.X ms` from `last_rtt_ms`. When `last_rtt_ms` is None the row SHALL be omitted (nothing useful to show).

The **Reachable** row SHALL render:
- `this sweep` (EN) / `此次扫描` (ZH) when `last_reachable_at` is within the last sweep cadence
- A relative duration via `_format_duration_short` when older (e.g. `2m 14s ago`)
- `never` (EN) / `从未` (ZH) when `last_reachable_at` is None (host is in the ARP cache but diting has never gotten a ping reply for it this session)

#### Scenario: User opens LAN detail on a row
- **WHEN** the user is on the LAN view, presses `down` to land on a row, then presses `i`
- **THEN** `LANDetailScreen` pushes onto the stack; the underlying view stays mounted; pressing `i` or `Esc` closes the modal back to the LAN view with the cursor row preserved

#### Scenario: User opens LAN detail on a host with known latency
- **WHEN** the user opens LANDetailScreen on a row whose `last_rtt_ms=2.4` and `last_reachable_at` is within the last sweep cadence
- **THEN** the Network section renders an extra row `Latency  2.4 ms`, and the Reachable row renders `this sweep`

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
