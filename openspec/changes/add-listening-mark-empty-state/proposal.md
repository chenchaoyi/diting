# add-listening-mark-empty-state

## Why

The list panels' waiting states are a single dim line in a large empty
box — the LAN view in particular shows `(sweeping subnet…)` over a
blank panel for the several seconds an ICMP sweep takes. The user
asked for the diting mark to appear there with a simple motion: a
touch of character during the wait, without costing TUI performance.

## What Changes

- A reusable "listening mark" renders in the waiting state of the four
  list panels (Wi-Fi scan / BLE / Bonjour / LAN): the pixel-art beast
  (the existing `_LOGO_MARK_ART` half-block rendering — the mark
  itself is NOT redesigned) with a single radar pulse dot travelling
  away from the antenna, the localized waiting caption beneath.
- Animation is diegetic and gated: it ticks only while the panel is
  visible AND in its waiting state AND polling is not paused — the
  pulse is a visualization of the sweep actually running, so it
  freezes on `p` (pause) and disappears the moment rows land.
- Cadence ~0.6 s/frame over a 5-frame cycle (≤2 Hz repaint of one
  small Static) — negligible against the existing 1 Hz connection
  poll.
- The design system README gains a carve-out note under its
  "Animation: effectively none" rule for this diegetic listening
  pulse (design README is EN-only; no ZH mirror exists for it).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `tui-shell`: new requirement — list-panel waiting states render the
  animated listening mark with the visibility/empty/pause gating.

## Impact

- `src/diting/tui.py` — pure frame builder + per-panel waiting-state
  wiring (timer with pause/resume).
- `docs/design/diting-design/README.md` — animation carve-out note.
- `tests/test_tui_helpers.py` (frame builder) + `tests/
  test_tui_smoke.py` (waiting state shows the mark, data clears it);
  `tests/TESTING.md` + `docs/zh/TESTING.md` first.
- No i18n key changes (captions reuse existing strings); no README
  key-table change; no helper/protocol impact.
