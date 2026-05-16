## Why

The diting TUI today opens with Textual's default one-row `Header`
widget: a flat black band carrying the title (`diting v1.0.12`) on
the left, the subtitle (`view: wifi · scan 7s`) directly to its
right, and a clock on the far right. It works, but it does the
brand a disservice — every other panel below it is unmistakably
diting (heavy orange box-drawing borders, near-black canvas,
the radar-arc voice in the empty states), and then the top of the
screen is generic Textual chrome.

The design system already ships the answer. `docs/design/diting-
design/assets/logo-mark.svg` is a 9×7 pixel-art radar mark in brand
orange — antenna stem, a wide body with a centre cutout, two pairs
of feet, and a thin underbar. It maps cleanly onto Unicode half-
block characters (`▀`, `█`, `▄`), which Fira Code renders at exactly
the cell grid. We can put that mark on screen, in the right colour,
without an icon library — the same way Claude Code's startup TUI
shows its own banner.

Doing so:

- Makes diting recognisable from a screenshot taken at any zoom
  level — the wordmark is small at small terminal sizes, the mark
  is not.
- Closes a design-system gap: the README marketing snapshot has a
  full wordmark in its title; the actual TUI does not.
- Costs nothing per frame after first render — the logo is static
  string content, and the clock / title / subtitle keep their
  existing refresh cadence.

## What Changes

- `src/diting/tui.py`: add a new `BrandHeader` widget (Horizontal
  container, height 4 with a tall orange bottom border) composed of
  a `_LogoMark` Static rendering the pixel-art mark in
  `#fea62b` and a `_TitleStack` Static rendering three lines —
  clock (right-aligned, dim), `diting v<version>` (bold), and the
  subtitle (dim). `DitingApp.compose()` yields `BrandHeader`
  instead of `Header(show_clock=True)`.
- `_TitleStack` watches `app.title` / `app.sub_title` so existing
  assignments to `self.sub_title` continue to drive the live
  state — no call-site changes required.
- `scripts/tui_snapshot.py`: bump the regression capture height
  from 56 to 60 rows so the new four-row header does not push the
  bottom panels off the captured area.
- `tests/test_tui_smoke.py`: add coverage that `BrandHeader`
  mounts and renders both the mark and the live title/subtitle.
- `tests/TESTING.md` + `docs/zh/TESTING.md`: update the existing
  `tui-shell` "header" row to point at the new tests and replace
  the `(gap — no subtitle assertion)` annotation.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `tui-shell`: tighten the header Requirement so the brand mark is
  always visible alongside the title + subtitle + clock.

## Impact

- `src/diting/tui.py`: one new widget pair (~70 lines), one-line
  swap in `compose()`. The widget pulls from the existing
  `self.title` / `self.sub_title` reactives so no other call site
  changes.
- `src/diting/i18n.py`: no new strings — the mark is glyph-only and
  the title / subtitle text is untouched. EN ↔ ZH parity holds.
- `scripts/tui_snapshot.py`: pilot `size=` tuple bumped from
  `(160, 56)` to `(160, 60)`.
- No new runtime deps; the mark uses Unicode half-blocks already
  available in Fira Code.
