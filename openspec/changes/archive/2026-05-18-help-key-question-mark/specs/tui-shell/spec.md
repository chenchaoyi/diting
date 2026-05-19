## MODIFIED Requirements

### Requirement: Modal screens SHALL push onto a stack and Esc / their own letter SHALL close
Each modal SHALL be opened via `app.push_screen(...)` and SHALL close on Esc, `q`, or the same key that opened it. The four bundled modals — HelpScreen (`?`), BasicsScreen (`b`), EventsScreen (`m`), BLEDetailScreen (`i`) — all follow this convention. Modals SHALL render center-middle with a heavy-bordered box and a footer hint listing the close keys.

The `h` key SHALL NOT be bound to any action; the slot is reserved for a future per-view binding without colliding with the global help shortcut.

#### Scenario: User opens help, reads, closes
- **WHEN** the user presses `?` then `Esc`
- **THEN** HelpScreen pushes onto the stack, the underlying view stays mounted underneath, Esc pops it back to the main view

#### Scenario: User opens BLE detail, presses `i` to close
- **WHEN** the user presses `i` on a BLE row, then `i` again
- **THEN** BLEDetailScreen pushes, then pops; the cursor row is unchanged

#### Scenario: Pressing `h` is a no-op
- **WHEN** the user presses `h` from any view
- **THEN** nothing happens; the key is intentionally unbound so it is free for a future shortcut without colliding with the global help binding

### Requirement: Hidden bindings SHALL exist for power-user navigation
The footer SHALL only show the eight primary bindings. Additional bindings — BLE row navigation (`up`, `down`, `enter`, `i`), modal filter-cycling (`0`/`1`/`2`/`3`/`4` in the events modal), scroll-within-modal — SHALL exist with `show=False` and SHALL be documented in the help modal but NOT clutter the footer.

#### Scenario: User opens help to find arrow-key behavior
- **WHEN** they press `?`
- **THEN** the help modal lists every binding including the hidden ones
