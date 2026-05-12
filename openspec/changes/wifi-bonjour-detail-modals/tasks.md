## 1. Test scaffolding (update test plan first, per SDD)

- [x] 1.1 Add new rows to `tests/TESTING.md` (EN): "Wi-Fi detail modal opens on row select", "Wi-Fi selection stable across re-sort", "Wi-Fi selection clears when BSSID drops out", "Bonjour detail modal opens on row select", "Bonjour selection stable across re-sort", "Bonjour TXT-record folding for long values"
- [x] 1.2 Mirror the new rows in `docs/zh/TESTING.md`

## 2. Wi-Fi detail modal — core

- [x] 2.1 Add `_wifi_selected_key: str | None` to the App and a `_scan_row_key()` helper that returns lowercase-stripped BSSID, falling back to `f"{ssid}#{channel}"` (or `f"#{channel}"` for empty SSID)
- [x] 2.2 Add `WifiDetailScreen(ModalScreen)` to `src/diting/tui.py` mirroring `BLEDetailScreen` (width 100, height 90%, sections rendered as Text, footer "Esc / i to close")
- [x] 2.3 Implement Identity section: SSID (or `(hidden)`), BSSID (or `(redacted by TCC — grant Location Services for full data)`), AP-name from `aps.yaml` when present, OUI vendor when BSSID is available, `(associated)` annotation when row matches active `Connection.bssid`
- [x] 2.4 Implement Radio + Signal + Beacon IE + Activity sections. Beacon IE section is omitted entirely when all of its fields are `None`. (Note: MCS / NSS are negotiated link state on `Connection`, not on `ScanResult`, so they are intentionally absent from the per-AP modal.)
- [x] 2.5 Bind `escape` / `i` / `q` to close in the modal's BINDINGS; same `t("Close")` label as BLE

## 3. Wi-Fi detail modal — wiring on `ScanPanel`

- [x] 3.1 Extend `ScanPanel` with a `_y_to_key: list[str | None]` rebuilt every render, mirroring `BLEPanel._y_to_id`
- [x] 3.2 Add `on_click` to `ScanPanel` translating `get_content_offset(body)` to a key, calling `app._wifi_set_selected(key, inspect=True)`
- [x] 3.3 Highlight the selected row via `row.stylize("reverse")` (same gesture as BLE)
- [x] 3.4 Add `_wifi_set_selected(key, *, inspect=False)` on App; when `inspect`, look up the matching `ScanResult` against the current snapshot and `push_screen(WifiDetailScreen(scan=…, connection=…, inv=…))`
- [x] 3.5 Add `action_wifi_select_next` / `action_wifi_select_prev` / `action_wifi_inspect` on App; each is a no-op when `_view_mode != "wifi"`. Replace the BLE-specific `up`/`down`/`enter,i` bindings with a `select_prev` / `select_next` / `inspect_selected` dispatcher that calls all three per-view actions (each gates itself by view).

## 4. Bonjour detail modal — core

- [x] 4.1 Add `_bonjour_selected_key: str | None` to the App and a `_bonjour_row_key(d)` helper returning `f"{d.name}.{d.service_type}"`
- [x] 4.2 Add `BonjourDetailScreen(ModalScreen)` to `src/diting/tui.py` mirroring the BLE modal layout (width 100, height 90%, scrollable body, footer "Esc / i to close")
- [x] 4.3 Implement Identity section: instance name (with `._<service-type>.local.` suffix stripped, matching list rendering), raw service type token, i18n category label, vendor
- [x] 4.4 Implement Network section: host (with `.local` suffix preserved), port, addresses (IPv4 listed before IPv6, one per line)
- [x] 4.5 Implement TXT records section: 2-column key/value table; values > 60 chars folded to `<N-byte payload> 8d4b…0000… (hex)` (first 16 raw bytes as hex). Section omitted entirely when `txt` is empty.
- [x] 4.6 Implement Activity section: first seen / last seen as "Xs ago" (reuse BLE's relative-time helper)
- [x] 4.7 Bind `escape` / `i` / `q` to close

## 5. Bonjour detail modal — wiring on `BonjourPanel`

- [x] 5.1 Extend `BonjourPanel` with `_y_to_key: list[str | None]` rebuilt every render
- [x] 5.2 Add `on_click` to `BonjourPanel` calling `app._bonjour_set_selected(key, inspect=True)`
- [x] 5.3 Highlight the selected row via `row.stylize("reverse")`
- [x] 5.4 Add `_bonjour_set_selected(key, *, inspect=False)` on App; when `inspect`, push `BonjourDetailScreen(device=…)`
- [x] 5.5 Add `action_bonjour_select_next` / `action_bonjour_select_prev` / `action_bonjour_inspect`; each no-ops when `_view_mode != "mdns"`. Wired through the same `select_prev` / `select_next` / `inspect_selected` dispatcher.

## 6. i18n

- [x] 6.1 Add EN catalog keys: section titles ("Radio", "Beacon IE", "Network", "TXT records"), modal titles ("Wi-Fi access point", "Bonjour service"), field labels ("AP name", "channel width", "PHY mode", "noise", "SNR", "BSS load", "BSS station count", "802.11r", "802.11k", "802.11v", "country code", "port", "addresses", "service type", "category", "instance"), inline notes ("(associated)", "(redacted by TCC — grant Location Services for full data)", "<{n}-byte payload>", "hex", "(empty)", "yes", "no"). Reused `t("Esc / i to close")`, `t("Close")`, `t("Identity")`, `t("Activity")`, `t("Signal")`, `t("first seen")` / `t("last seen")`, `t("ago")`, `t("(unknown)")`, `t("(hidden)")`, `t("SSID")`, `t("BSSID")`, `t("RSSI")`, `t("channel")`, `t("band")`, `t("security")`, `t("vendor")`, `t("host")` from existing catalog.
- [x] 6.2 Add matching ZH values in `_ZH` for every new key

## 7. Smoke + snapshot tests

- [x] 7.1 New `tests/test_tui_smoke.py` cases (`test_wifi_inspect_opens_modal_on_first_press`, `test_wifi_selection_keyed_by_bssid_survives_resort`, `test_wifi_selection_clears_when_target_drops_out`, plus matching Bonjour trio) and `tests/test_tui_helpers.py` rendering tests (`_scan_row_key` / `_bonjour_row_key` keying, Wi-Fi / Bonjour modal section assertions, TXT folding)
- [x] 7.2 Added `wifi_detail_modal` + `bonjour_detail_modal` synthetic scenarios to `scripts/tui_snapshot.py`. Regression run: 13 scenarios, 29 asserts, 0 failed.
- [x] 7.3 `uv run pytest` — 484 passed (21 new)

## 8. Docs

- [x] 8.1 Help-modal copy: `↑/↓` and `enter / i` now read as cross-panel "list cursor" / "inspect the selected row" instead of BLE-only
- [x] 8.2 `README.md`: BLE-detail-modal paragraph generalised to "Press `i` (or click a row) on any list view — Wi-Fi, BLE, or Bonjour — for a detail modal"
- [x] 8.3 `docs/zh/README.md` mirrors the same change in Chinese

## 8b. Live navigation inside the modal

- [x] 8b.1 Add a public `sync_to_app_selection()` method to each of `WifiDetailScreen` / `BonjourDetailScreen` / `BLEDetailScreen` that re-fetches the current selection from the App and re-renders the modal body (BLE also refreshes the RSSI-history sparkline from `_ble_history.get(ident)`)
- [x] 8b.2 Wire the App's `action_select_prev` / `action_select_next` to walk `self.screen_stack` and call `sync_to_app_selection()` on any open detail modal. Single helper `_sync_open_detail_modal()` keeps the dispatch in one place.
- [x] 8b.3 New smoke tests: `test_wifi_detail_modal_tracks_selection_on_arrow_keys`, `test_bonjour_detail_modal_tracks_selection_on_arrow_keys` verify the modal's internal scan / device record advances on ↓ / ↑
- [x] 8b.4 Spec deltas updated to record the new live-nav requirement on all three modal capabilities (`wifi-detail-modal`, `bonjour-detail-modal`, `ble-detail-modal`); proposal.md + design.md updated to reflect why arrow bindings live on the App, not on each modal

## 9. Validation gates before PR

- [x] 9.1 `uv run pytest` — 484 passed, 0 failures
- [x] 9.2 `uv run python scripts/tui_snapshot.py --mode regression --check` — 29/29 asserts passed
- [x] 9.3 `openspec validate --specs --strict` — 17/17 passed
- [x] 9.4 `openspec validate wifi-bonjour-detail-modals --strict` — change validates
