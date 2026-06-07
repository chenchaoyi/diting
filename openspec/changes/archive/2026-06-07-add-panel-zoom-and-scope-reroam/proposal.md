# add-panel-zoom-and-scope-reroam

## Why

Two live-use frictions from the 2026-06-07 session. (1) The `c`
Re-roam binding ("重选 AP") is a Wi-Fi action, but it shows in the
footer and fires on every view — pressing it from the BLE/Bonjour/LAN
view bounces the Wi-Fi link with no visible connection to what the
user is looking at. (2) The four list views (Wi-Fi / BLE / Bonjour /
LAN) share one panel slot squeezed between the connection, diagnostics
and events panels; in dense environments the entry count far exceeds
the visible rows and there is no way to enlarge the list — unlike
events, which has the `m` full-screen browser.

## What Changes

- The `c` Re-roam binding becomes Wi-Fi-view-scoped: it disappears
  from the footer (and the command palette) and does not fire on the
  BLE / Bonjour / LAN views.
- A new `z` Zoom binding maximizes the active list panel in place to
  fill the screen — live updates, sorting, row-selection and inspect
  keep working because it is the same widget, not a snapshot modal.
  Pressing `z` again (or Esc) restores the normal layout. Cycling
  views with `n` while zoomed keeps the zoom on the newly active
  panel.
- Footer, help modal, README (EN+ZH) document both.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `tui-shell`: the footer requirement changes (group 2 gains `zoom`;
  `re-roam` shows only in the Wi-Fi view); a new requirement adds the
  in-place panel-maximize contract.

## Impact

- `src/diting/tui.py` — `GroupedFooter.refresh_layout` (conditional
  `c`, new `z`), `DitingApp` bindings + `check_action` + zoom action,
  `action_toggle_view` zoom-follow.
- `src/diting/i18n.py` — new `Zoom` key strings (EN catalog + ZH).
- `tests/test_tui_smoke.py` — zoom toggle / view-follow / reroam-scope
  coverage; `tests/TESTING.md` + `docs/zh/TESTING.md` first.
- `README.md` + `docs/zh/README.md` — key tables.
- No helper, wire-format, or companion impact.
