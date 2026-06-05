# Polish event rendering — vendor aliases, visible truncation, modal ordering

## Why

A live /tui-audit (2026-06-05, office floor) surfaced three rendering
papercuts:

1. **Event labels render raw IEEE vendor strings.** The events strip showed
   `Anhui Huami Information Technology Co., Ltd.  ·  (unknown)` while the BLE
   list shows `Huami` — the `_BLE_VENDOR_DISPLAY` alias map exists but the
   event formatters bypass it. Long registrant strings eat the row and bury
   the device label.
2. **Hard truncation reads like real text.** The BLE services column rendered
   `Device Informati` (chopped "Device Information") with no marker, while
   the vendor cell renders `Qualcomm Technolo…`. `fit_cells` silently chops;
   a comment at `_COL_MDNS_SERVICES` already widened a column to dodge
   exactly this ("fit_cells doesn't add an ellipsis indicator").
3. **The events modal can show non-monotonic timestamps.** Anonymous BLE
   adverts are presence-gated; the seen event deliberately carries the
   FIRST-observed timestamp (ble.py documents why: the JSONL answers "when
   did the device appear") but is emitted at gate-clear, while named devices
   emit instantly — so ring order ≠ timestamp order and the modal reads as
   disorder (observed: 18:54:09 → :15 → :09 → :18 → :15).

## What Changes

1. `_ble_event_vendor_label` runs the resolved vendor through
   `_BLE_VENDOR_DISPLAY` — the same alias map the BLE list and the census
   fold already use. Unaliased vendors pass through; `(anonymous)` /
   `(unknown)` fallbacks unchanged.
2. `fit_cells` gains an `ellipsis=True` keyword: when the text overflows, it
   truncates one cell short and appends `…`, still cell-exact and never
   splitting a wide glyph. Applied to the BLE name + services columns and
   the mDNS name + services columns; `_fit_vendor` reuses it instead of its
   private copy of the same logic.
3. The EventsScreen modal orders rows newest-first **by event timestamp**
   (stable sort over the ring snapshot) instead of raw ring (emission)
   order. The bottom strip (append-only RichLog) and the JSONL log are
   untouched — the first-seen timestamp semantics stay exactly as the
   documented design in `ble.py` intends.

## Impact

- Affected specs: `tui-shell` (two ADDED requirements: event vendor display
  alias; modal timestamp ordering), `i18n` (MODIFIED: the pad/fit
  requirement documents the ellipsis variant).
- Affected code: `src/diting/tui.py` (`_ble_event_vendor_label`,
  `_fit_vendor`, BLE/mDNS row builders, `EventsScreen._render_body` +
  a small `_events_newest_first` helper), `src/diting/i18n.py`
  (`fit_cells`).
- Not changed: JSONL timestamps / emission order, the events strip, the
  duplicate-grouping and census-fold logic (they run on the sorted list).
