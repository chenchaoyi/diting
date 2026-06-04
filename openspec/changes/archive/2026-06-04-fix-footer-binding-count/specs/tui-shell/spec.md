# tui-shell — delta

## MODIFIED Requirements

### Requirement: Hidden bindings SHALL exist for power-user navigation
The footer SHALL only show the ten primary bindings. Additional
bindings — BLE row navigation (`up`, `down`, `enter`, `i`), modal
filter-cycling (`0`/`1`/`2`/`3`/`4` in the events modal),
scroll-within-modal — SHALL exist with `show=False` and SHALL be
documented in the help modal but NOT clutter the footer.

#### Scenario: User opens help to find arrow-key behavior
- **WHEN** they press `h`
- **THEN** the help modal lists every binding including the hidden ones
