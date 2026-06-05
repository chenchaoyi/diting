# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — rows for the three
  behaviors (event vendor alias, fit_cells ellipsis, modal ordering).

## 2. Vendor alias in event rows
- [x] 2.1 `tui.py` — `_ble_event_vendor_label` maps through
  `_BLE_VENDOR_DISPLAY`.

## 3. Visible truncation
- [x] 3.1 `i18n.py` — `fit_cells(..., ellipsis=True)`.
- [x] 3.2 `tui.py` — BLE name/services (×2 sites each), mDNS name/services
  use the ellipsis form; `_fit_vendor` reuses it.

## 4. Modal ordering
- [x] 4.1 `tui.py` — `_events_newest_first` helper; `EventsScreen._render_body`
  sorts the filtered snapshot by timestamp desc (stable).

## 5. Tests
- [x] 5.1 `test_tui_helpers.py` — alias applied / pass-through; modal order
  monotonic for interleaved timestamps. `test_i18n.py` — ellipsis truncation,
  exact width, CJK boundary, fits-unchanged.

## 6. Gates
- [x] 6.1 `uv run pytest`, snapshot regression,
  `openspec validate --specs --strict`,
  `openspec validate polish-event-rendering --strict`.
