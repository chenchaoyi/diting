# diting TUI — UI kit

A high-fidelity HTML recreation of the diting macOS TUI. Use it as a
visual reference, or paste components into mocks/marketing.

- `index.html` — interactive demo. Toggle `view: wifi` ↔ `view: ble`,
  open the Events modal (`m`), watch the footer keybindings change.
- `app.jsx` — every component (`Window`, `Panel`, `SignalBar`,
  `ConnectionPanel`, `DiagnosticsPanel`, `ScanPanel`, `RoamLog`,
  `BlePanel`, `EventsModal`, `Footer`).
- `tui.css` — UI kit shell only. Pulls colors / type from
  `../../colors_and_type.css`.

This is a recreation, not production code. Logic is illustrative —
RSSI values, cluster grouping, and the event log are static fixtures
from the real TUI snapshots. Components are intentionally simple so
they can be lifted into other mocks.
