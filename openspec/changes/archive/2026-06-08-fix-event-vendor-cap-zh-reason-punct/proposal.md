# fix-event-vendor-cap-zh-reason-punct

## Why

Two rendering polish items from the 2026-06-08 live zh `/tui-audit`:

1. **BLE event rows render the vendor at unbounded length.**
   `_ble_event_vendor_label` resolves the vendor through the
   display-alias map but, unlike the BLE list's `_fit_vendor`, applies
   no length cap. Long-tail IEEE registrant strings present in the
   user's real environment — `GuangDong Oppo Mobile Telecommunications
   Corp., Ltd.` (52), `Qualcomm Technologies International, Ltd.
   (QTIL)` (48) — render full-length in the events strip and modal. In
   the zh UI a 50-char English vendor is a wall of Latin in an
   otherwise-Chinese event log.

2. **Roam-score reasons use ASCII punctuation in Chinese prose.**
   The reason clause is built as `f" ({', '.join(translated)})"`, so
   in zh it renders `(信号强, 5 GHz)` — half-width parens and comma
   inside Chinese text, where zh prose elsewhere uses full-width
   `（）` / `、`.

## What Changes

- `_ble_event_vendor_label` caps the resolved vendor to a fixed cell
  budget with a visible ellipsis (truncate-only, no padding — the
  event line is free-flow, not a fixed column). A handful of common
  long-tail vendors gain display aliases so they read clean rather
  than truncated.
- The roam-reason clause is wrapped in locale-correct punctuation:
  full-width `（…）` joined by `、` in zh, ASCII `( …, … )` in en.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `tui-shell`: the event-row vendor requirement is extended — after
  alias resolution the vendor label SHALL be capped to a fixed cell
  budget with a visible ellipsis (an unaliased long-tail registrant
  no longer passes through at full length).
- `roam-detection`: new requirement — the roam-score reason clause
  SHALL use locale-correct list punctuation (full-width `（…）` / `、`
  in zh, ASCII in en).

## Impact

- `src/diting/tui.py` — `_ble_event_vendor_label` cap; a few entries
  in `_BLE_VENDOR_DISPLAY`; a `_format_reason_clause` helper used by
  the two roam-reason call sites; `get_lang` added to the i18n import.
- `tests/test_tui_helpers.py` — vendor-cap + reason-punctuation cases;
  `tests/TESTING.md` + `docs/zh/TESTING.md` first.
- No i18n catalog key changes, no wire-format/protocol impact.
