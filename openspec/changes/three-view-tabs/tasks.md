## 1. Test plan first

- [x] 1.1 Update the `tui-shell` row in `tests/TESTING.md` to cite the
      new tab-indicator + border-subtitle test cases.
- [x] 1.2 Mirror to `docs/zh/TESTING.md`.

## 2. Display-name map + helper

- [x] 2.1 Add `_VIEW_DISPLAY_NAMES = {"wifi": "Wi-Fi", "ble": "BLE",
      "mdns": "Bonjour"}` near the top of `src/diting/tui.py`.
- [x] 2.2 Add `_view_display_name(mode: str) -> str` helper that
      reads from the map (returns `mode` unchanged when unknown).
- [x] 2.3 Replace the inline `_NEXT_LABEL` dict inside
      `GroupedFooter.refresh_layout` with calls to
      `_view_display_name(next_mode)` so there's a single source of
      truth for view labels.

## 3. Tab indicator helper

- [x] 3.1 Add `_view_tabs_border_title(active: str) -> str` helper
      that composes the Rich-markup string
      `"[bold cyan]<active>[/]  ·  [dim]<other1>[/]  ·  [dim]<other2>[/]"`
      in cycle order.
- [x] 3.2 Verify Textual `border_title` accepts Rich markup with
      per-segment styles (smoke test in the existing test suite).

## 4. Wire into the three refresh functions

- [x] 4.1 `_refresh_scan_panel`: set
      `panel.border_title = _view_tabs_border_title("wifi")` and
      move the existing `Nearby BSSIDs (N) · sort: ap` content into
      `panel.border_subtitle`.
- [x] 4.2 `_refresh_ble_panel` / `BLEPanel.update_devices`: same
      treatment for the BLE view. Border subtitle carries
      `Nearby BLE devices (N)`; border title carries the tab indicator
      with `"ble"` active.
- [x] 4.3 `_refresh_mdns_panel` / `BonjourPanel.update_devices`:
      same for the mDNS view. Border subtitle carries
      `Nearby Bonjour (N)`; border title carries the tab indicator
      with `"mdns"` active.

## 5. Subtitle display-name fix

- [x] 5.1 In `_build_subtitle`, replace `t(self._view_mode)` with
      `_view_display_name(self._view_mode)` so the header reads
      `view: Bonjour` instead of `view: mdns`.

## 6. Bonjour row suffix strip

- [x] 6.1 Add `_strip_service_suffix(name, service_type)` helper in
      `src/diting/tui.py` next to `_bonjour_row_line`. Strips
      `.<service_type with trailing dot>` and `.<service_type without
      trailing dot>` patterns.
- [x] 6.2 Wire into `_bonjour_row_line`: compute the display name
      via `_strip_service_suffix(d.name, d.service_type)` before
      passing to `fit_cells`.

## 7. i18n catalog fix for `service types`

- [x] 7.1 In `src/diting/tui.py:_bonjour_diagnostic_lines`, split
      the diagnostic-line append into two pieces:
      `line.append("  ·  ", style="dim")` then
      `line.append(t("{n} service types", n=...), style="dim")`.
      That way the existing catalog key (`"{n} service types"`)
      finally matches the call.

## 8. Tests

- [x] 8.1 `test_view_tabs_border_title_lists_all_three_views` —
      pure helper test, asserts both EN/ZH labels appear in the
      composed Rich-markup string for every active mode.
- [x] 8.2 `test_view_display_name_maps_internal_tokens_to_user_names`
      — `_view_display_name("mdns") == "Bonjour"` and friends.
- [x] 8.3 `test_strip_service_suffix_strips_known_suffix`,
      `::test_strip_service_suffix_leaves_other_names_unchanged`.
- [x] 8.4 `test_tui_smoke.py::test_panel_border_title_carries_tab_indicator`
      — pilot test verifying the active panel's border_title
      contains all three labels.
- [x] 8.5 `test_tui_smoke.py::test_bonjour_diagnostic_service_types_translated_in_zh`
      — set DITING_LANG=zh, render the diagnostic line, assert
      `种服务` appears and `service types` does not.

## 9. CHANGELOG

- [x] 9.1 `CHANGELOG.md` `[Unreleased] → ### Changed` entry
      describing the always-visible tab indicator and the
      subtitle / suffix-strip / `service types` polish items.
- [x] 9.2 `docs/zh/CHANGELOG.md` mirror.

## 10. Self-test + ship

- [x] 10.1 `uv run pytest` — expect 452 + ~6 new = ~458 pass.
- [x] 10.2 `uv run python scripts/tui_snapshot.py --mode regression
      --check` — 16/16.
- [x] 10.3 `openspec validate --specs --strict` — 16/16.
- [x] 10.4 `openspec validate three-view-tabs --strict` — change
      valid.
- [x] 10.5 Live `DITING_LANG=zh` capture — confirm all three view
      labels visible in the third panel's border title regardless
      of active view; `service types` rendered as `种服务` under ZH;
      subtitle reads `view: Bonjour` not `view: mdns`; Bonjour rows
      no longer carry `._airplay._tcp.local.` suffix in the name
      column.
- [x] 10.6 Commit (explicit `git add <files>`), push, open PR.

## 11. Post-merge

- [ ] 11.1 `openspec archive three-view-tabs` — applies the
      MODIFIED `tui-shell` Requirement into canonical
      `openspec/specs/tui-shell/spec.md`.
