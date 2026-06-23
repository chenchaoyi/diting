## ADDED Requirements

### Requirement: BLE diagnostics counts SHALL be labeled so they reconcile with the list

The BLE diagnostics panel SHALL label its counts so a reader can reconcile them
with the BLE list without ambiguity:

- The visible-device count SHALL be labeled as advertising devices (e.g. `N
  advertising`), not an unqualified "total", because the list footer counts the
  advertising rows together with the separate Connected-peripherals group; the
  Connected count is shown on its own diagnostics row.
- The rotation-fold annotation on the Vendors line SHALL name its unit (e.g.
  `(+N rotations folded)`), since it counts rotating-ID advertisements the
  merger collapsed — not vendors — and an unqualified `(+N folded)` appended to
  the vendor histogram reads as folded vendors.

#### Scenario: Visible count is labeled advertising
- **WHEN** the BLE diagnostics panel renders the visible-device line
- **THEN** the count is labeled as advertising devices, so it plus the Connected-peripherals row reconciles with the list footer

#### Scenario: Fold annotation names its unit
- **WHEN** the merger has collapsed rotating-ID advertisements into visible rows
- **THEN** the Vendors line's fold annotation names the unit (`rotations folded`), so it does not read as folded vendors
