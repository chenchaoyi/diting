## Why

A real-environment `/tui-audit` (2026-06-23) surfaced three render
ambiguities:

- **Help modal merges label + description.** The two-column help `line()` does
  `f"{label:<6}"` then appends the description with no separator. `:<6` is a
  minimum width, so a label that is exactly 6 chars (`Events`) or longer
  (`enter / i`) abuts its text → `Eventsstrip`, `enter / iinspect`, which read
  as typos.
- **BLE "(+N folded)" sits on the Vendors line.** It correctly counts
  rotating-ID adverts the merger collapsed, but appended to the vendor
  histogram (`… · (+183 folded)`) against ~30 devices it reads as "+183 more
  vendors folded" — impossible and confusing.
- **BLE "Visible BLE N total" didn't reconcile with the footer.** The list
  footer counts advertising rows + the separate Connected-peripherals group
  (`32`), while the diagnostics said `30 total`, so the word "total" read as a
  grand total that was off by the connected count.

## What Changes

- Help `line()` always renders a separator between the key/label and its
  description (no merged words), for every label length.
- The BLE rotation-fold annotation names its unit: `(+N rotations folded)`.
- The BLE visible-count diagnostic reads `N advertising` (not `N total`), so it
  reconciles with the footer alongside the existing Connected-peripherals row.
- Cosmetic: add a display alias for the long-tail `Edifier International
  Limited` registrant (29 chars) so it shows `Edifier`.

## Impact

- Specs: `tui-shell` (help-row separation), `bluetooth-scanning` (unambiguous
  BLE diagnostics labels).
- Code: `src/diting/tui.py` (`line`, `_ble_visible_line`, `_ble_vendors_line`,
  `_BLE_VENDOR_DISPLAY`), `src/diting/i18n.py` (`{n} advertising`,
  `(+{n} rotations folded)`). Tests updated for the new strings + a help-row
  separation regression test. No behaviour beyond render text.
