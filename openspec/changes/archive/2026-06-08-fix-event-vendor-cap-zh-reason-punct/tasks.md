# fix-event-vendor-cap-zh-reason-punct — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) for the vendor cap + reason punctuation
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Failing tests: event vendor cap (long unaliased → truncated
      `…`, no padding; short → unchanged; aliased → alias); reason
      clause (en ASCII, zh full-width `（…、…）`)

## 2. Fix 1 — event vendor cap

- [x] 2.1 `_BLE_EVENT_VENDOR_MAX` constant + cap in
      `_ble_event_vendor_label` (alias → fit_cells truncate-only)
- [x] 2.2 Add the handful of exact long-tail aliases seen live
      (Qualcomm QTIL, Oppo, Resideo) to `_BLE_VENDOR_DISPLAY`

## 3. Fix 2 — zh reason punctuation

- [x] 3.1 `get_lang` into the i18n import
- [x] 3.2 `_format_reason_clause` helper; use at both roam-reason
      call sites (tui.py ~3495 / ~3512)

## 4. Verify

- [x] 4.1 `uv run pytest`
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 4.3 `openspec validate --specs --strict` +
      `openspec validate fix-event-vendor-cap-zh-reason-punct --strict`
