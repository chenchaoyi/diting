## Why

Post-merge audit of PR #30 (mDNS / Bonjour panel) found a
**discoverability gap**: today only the active view is visible, and
the only hint at the other two views is the footer's `n  → BLE`
breadcrumb. A user who never presses `n` past BLE never learns that
Bonjour exists. The full set of three views — Wi-Fi · BLE · Bonjour
— is invisible from any single screen.

Plus four small post-merge polish items from the same audit:

1. `3 service types` suffix leaks raw English under `DITING_LANG=zh`
   (catalog-key whitespace mismatch).
2. Subtitle reads `view: mdns` instead of `view: Bonjour` (internal
   token leaked to the user-facing label).
3. Service-instance names truncated without ellipsis and carry the
   redundant `._airplay._tcp.local.` suffix.
4. The audit's other minor findings (none material — included for
   completeness in the test plan).

## What Changes

- **Always-visible tab indicator** in the third-slot panel's border
  title. The title becomes a 3-segment view list — `Wi-Fi · BLE ·
  Bonjour` — with the active view styled bold cyan and the other
  two dimmed. The existing panel-specific detail (`Nearby BSSIDs
  (104) · sort: AP` / `Nearby BLE devices (37)` / `Nearby Bonjour
  (3)`) moves to the panel's `border_subtitle` (bottom of frame),
  so no information is lost.
- **Subtitle display name**: header subtitle renders `view: Wi-Fi`
  / `view: BLE` / `view: Bonjour` (was `view: wifi` / `view: ble` /
  `view: mdns`). The internal mode token stays `mdns` everywhere
  in code; only the user-facing label changes.
- **i18n fix**: `3 service types` suffix wraps through the catalog
  correctly. Catalog key matches call-site whitespace.
- **Render polish**: Bonjour row's name column strips the trailing
  service-type suffix (e.g., `ccy MBP2024 M4 Office._airplay._tcp.local.`
  becomes `ccy MBP2024 M4 Office` — the service type is already shown
  one column over).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `tui-shell`: one MODIFIED Requirement adding the three-view tab
  indicator to the panel layout contract. The existing 3-way `n`
  toggle Requirement (already in spec) is unchanged; only the
  "what's visible on screen" affordance grows.

## Impact

- **Files**:
  - `src/diting/tui.py` — `_view_tabs_border_title()` helper, used
    by `_refresh_scan_panel` / `_refresh_ble_panel` /
    `_refresh_mdns_panel`. Border-subtitle assignment for the
    existing detail line.
  - `src/diting/tui.py` — `_view_display_name()` map for the
    subtitle (and the tab labels), replacing the bare `t(view_mode)`.
  - `src/diting/i18n.py` — `"  ·  {n} service types"` catalog key
    matches the call site.
  - `src/diting/mdns.py` (or `tui.py`) — strip
    `._<service-type>.local.` suffix in `_bonjour_row_line` before
    fit_cells.
  - `tests/test_tui_smoke.py` — extend the 3-way toggle test to
    assert that all three view names appear in the active panel's
    border title regardless of mode.
  - `tests/test_mdns.py` — new test for the suffix-strip render
    helper.
  - `tests/TESTING.md` + `docs/zh/TESTING.md`.
  - `CHANGELOG.md` + `docs/zh/CHANGELOG.md`.
- **Tests**: 2-3 new unit/smoke cases.
- **CI gates**: pytest, snapshot regression 16/16, specs strict.
- **External**: no version bump.
