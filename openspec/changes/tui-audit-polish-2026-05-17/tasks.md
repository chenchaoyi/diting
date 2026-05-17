## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — append entries under `wifi-scanning` for BSSID dedup + Tx idle cache; under `ble-detail-modal` for services empty state; under `mdns-scanning` for by-host sort + unknown-vendor label.
- [x] 1.2 `docs/zh/TESTING.md` — mirror entries in ZH.

## 2. Scan BSSID dedup (`wifi-scanning`)

- [x] 2.1 `src/diting/_helper.py::scan` — build a `dict[str, ScanResult]` keyed by lowercase BSSID; on collision, keep the higher-RSSI row (treat `None` as `-200`). Rows with `bssid is None` are kept verbatim (no dedup key).
- [x] 2.2 `src/diting/macos_backend.py::MacOSWiFiBackend.scan` — apply the same dedup to the direct-CoreWLAN fallback path, so both paths return a uniformly-deduped list.
- [x] 2.3 `tests/test_helper.py` — add `test_scan_dedup_by_bssid_keeps_strongest_rssi`, `test_scan_dedup_preserves_insertion_order`, `test_scan_dedup_skips_none_bssid_rows`.

## 3. Tx Rate idle cache (`wifi-scanning`)

- [x] 3.1 `src/diting/models.py::Connection` — add `tx_rate_idle: bool = False` field.
- [x] 3.2 `src/diting/macos_backend.py::MacOSWiFiBackend` — track `_last_nonzero_tx_rate: float | None` and `_last_tx_rate_key: tuple[str | None, str | None]`. In `_connection_snapshot` (or wherever `Connection` is built), substitute the cached rate when `transmitRate()` returns 0/None on the same `(ssid, bssid)` key; set `tx_rate_idle=True` only when substituting. Reset cache on key change.
- [x] 3.3 `src/diting/tui.py` — Connection panel's Tx / Max row appends `" (idle)"` after the Tx Mbps value when `conn.tx_rate_idle` is true. The label MUST go through `t()` so the ZH catalog can localise it.
- [x] 3.4 `src/diting/i18n.py` — add `"(idle)": "（空闲）"` to the EN and ZH catalogs.
- [x] 3.5 `tests/test_macos_backend.py` (create if absent) — add `test_tx_rate_idle_cache_substitutes_on_zero_same_ap`, `test_tx_rate_idle_cache_clears_on_bssid_change`, `test_tx_rate_idle_flag_false_on_first_zero_with_no_history`.
- [x] 3.6 `tests/test_tui_helpers.py` — assert the Connection panel renders `"144.0 Mbps (idle) / 867 Mbps"` when `tx_rate_idle=True` and `"144.0 Mbps / 867 Mbps"` when `False`.

## 4. Services empty-state em-dash (`ble-detail-modal`)

- [x] 4.1 `src/diting/tui.py::WifiDetailScreen._section_services` (≈line 3580) — replace `self._label(out, t("(none advertised)"), None)` with a direct `out.append("  " + t("(none advertised)") + "\n", style="dim italic")`. (Note: despite the class name `WifiDetailScreen`, this method is on the BLE detail modal — confirm and grep.)
- [x] 4.2 Sweep the same file for other `_label(out, t("(none …)"), None)` calls (extra UUIDs, other services) and apply the same fix.
- [x] 4.3 `tests/test_tui_helpers.py` — add `test_ble_detail_services_empty_state_has_no_trailing_emdash` asserting that the rendered Text for a service-less device contains "(none advertised)" but NOT the em-dash glyph on that line.

## 5. Bonjour by-host sort (`mdns-scanning`)

- [x] 5.1 `src/diting/tui.py::BonjourPanel.update_*` — accept a `sort_mode` argument; default `"service"`. Implement `_render_service_mode` (existing) + `_render_by_host_mode` (new, group by `host`, fold services list, alphabetise short names, comma-join).
- [x] 5.2 `src/diting/tui.py::DitingApp` — extend the `s`-key handler so that when `view == "bonjour"` it cycles `"service" → "by-host" → "service"`. Mode state stored on the app instance (parallel to Wi-Fi's `_scan_sort_mode`).
- [x] 5.3 `src/diting/i18n.py` — add catalogues for the new sort-mode names: `"service"` (EN+ZH), `"by-host"` (EN+ZH), and any new placeholder strings introduced.
- [x] 5.4 `tests/test_tui_helpers.py` — `test_bonjour_panel_by_host_mode_folds_services_alphabetically`, `test_bonjour_panel_s_key_cycles_modes`, `test_bonjour_panel_by_host_truncates_long_services_with_ellipsis`.
- [x] 5.5 `scripts/tui_snapshot.py` — add a regression scenario `bonjour_by_host_mode` (synthetic backend) so the layout is locked under CI.

## 6. Unknown-vendor label parity (`mdns-scanning`)

- [x] 6.1 `src/diting/tui.py` — locate the mDNS "Top vendors" line builder, replace the literal `?` glyph used for the unknown bucket with `t("(unknown)")`. (BLE side already does this; the function is likely in the diagnostics-lines helper near the existing `_bonjour_diagnostics_lines` / equivalent.)
- [x] 6.2 `tests/test_tui_helpers.py` — `test_mdns_diagnostics_top_vendors_uses_unknown_label`.

## 7. README / docs

- [x] 7.1 `README.md` — if the README mentions the `s` sort behaviour for the Bonjour panel, extend the row to call out `by-host` as a second mode. Otherwise no README change is needed (verify).
- [x] 7.2 `docs/zh/README.md` — mirror.

## 8. CI gates

- [x] 8.1 `uv run pytest`
- [x] 8.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 8.3 `openspec validate --specs --strict`
- [x] 8.4 `openspec validate tui-audit-polish-2026-05-17 --strict`
