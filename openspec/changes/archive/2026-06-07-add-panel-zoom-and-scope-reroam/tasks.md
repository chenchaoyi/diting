# add-panel-zoom-and-scope-reroam — tasks

## 1. Test plan first

- [x] 1.1 Add the zoom + scoped-reroam rows to `tests/TESTING.md`
- [x] 1.2 Mirror them in `docs/zh/TESTING.md`
- [x] 1.3 Write failing smoke tests: `z` maximizes the active panel /
      restores; zoom follows `n`; `check_action("reroam")` is False
      off-Wi-Fi; footer omits `c` off-Wi-Fi and shows `z` everywhere

## 2. Re-roam scoping

- [x] 2.1 `check_action` gate on `reroam` (Wi-Fi view only)
- [x] 2.2 Conditional footer entry in `GroupedFooter.refresh_layout`
- [x] 2.3 Help modal marks re-roam Wi-Fi-only (EN + ZH i18n)

## 3. Panel zoom

- [x] 3.1 `z` binding + `action_toggle_zoom` (maximize active panel /
      minimize)
- [x] 3.2 `Esc` restore binding gated by maximize state via
      `check_action`
- [x] 3.3 `action_toggle_view` keeps zoom across view cycles
- [x] 3.4 Footer + help modal entries (EN + ZH i18n)

## 4. Docs

- [x] 4.1 README.md key table + docs/zh/README.md in the same PR

## 5. Verify

- [x] 5.1 `uv run pytest`
- [x] 5.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 5.3 `openspec validate --specs --strict` and
      `openspec validate add-panel-zoom-and-scope-reroam --strict`
