## Context

`DitingApp.compose()` currently yields `Header(show_clock=True)` —
Textual's built-in single-row chrome that draws a flat band, the
title on the left, the subtitle to its right, and the clock on the
far right. Every other surface in the TUI conforms to the design
system at `docs/design/diting-design/` (heavy 1-px orange box-drawing
borders on the four panels, near-black canvas, semantic palette,
no decoration); the header is the one place where Textual's defaults
leak through unchanged.

The design system ships `assets/logo-mark.svg` — a 9-col × 7-row
pixel-art radar mark in brand orange (`#fea62b`) with a black centre
cutout — explicitly for this kind of brand placement. The mark maps
to Unicode half-block characters (`▀`, `█`, `▄`) with no scaling
artefacts, since Fira Code renders each cell as a perfect rectangle
that a half-block exactly fills.

## Goals / Non-Goals

**Goals:**
- Put the diting radar mark on screen, in brand orange, alongside
  the wordmark + version. The result should read as the same
  instrument as the marketing snapshot in the README.
- Keep all existing live state — clock, view, scan period,
  paused — visible without any extra keystroke.
- Zero new dependencies. Zero new strings to translate.

**Non-Goals:**
- Splash / boot animation. The mark is *persistent* chrome, like
  the rest of the TUI — there is no transient banner.
- Configurable header size. Four rows is the spec.
- New brand surface for the wordmark beyond the existing
  `diting v<version>` string. The wordmark renders as text, not
  a second pixel-art mark; only the radar mark gets the pixel
  treatment.
- Touching the four-panel layout, the GroupedFooter, or any
  modal. Scope is the top of the screen only.

## Decisions

### D1 — Render the mark via Unicode half-blocks, not a font icon

The mark's source is a 9×7 pixel grid on 8-pixel cells. Each pair
of vertically adjacent grid rows collapses cleanly into one
terminal row using `▀` (top half), `▄` (bottom half), `█` (both),
or space (neither). Three of the seven grid rows go into the body
proper; the seventh (the 2-px underbar across the full width) is
replaced by Textual's `border-bottom: tall #fea62b`, which renders
exactly the same continuous one-cell-tall orange line spanning the
header's whole width.

Result — three glyph rows for the mark itself:

```
  █
█▀██████▄
▀██▀▀▀▀██
```

Plus the underbar row provided by the container's bottom border.
Total widget height: 4. The mark's column width is 9; we pad with
one space on either side for a content area of 11 columns and
treat that as a fixed-width column in the layout.

Half-blocks are part of the Unicode Block Elements range
(U+2580..U+259F) and ship in every modern monospace font we
support. Fira Code, JetBrains Mono, SF Mono, Menlo all render
them at the full cell with no anti-aliasing gaps.

### D2 — Compose as `Horizontal(_LogoMark, _TitleStack)`, not one big `Static`

The naive route is one `Static` widget that produces a 4-line Rich
`Text` and right-aligns the clock by counting cells. That works
but reimplements layout primitives that Textual already does
correctly. Splitting into two children — a fixed-width `_LogoMark`
(width 11) and a `_TitleStack` (width `1fr`) — lets Textual handle
the column split, terminal-resize, and content alignment via CSS.

The `_TitleStack` itself does render a Rich Console `Group` of
three Texts because we want clock right-aligned and title /
subtitle left-aligned in the same column — that's one render, not
three child widgets, since the three lines never move independently.

### D3 — Pull title and subtitle from `App.title` / `App.sub_title` via `watch()`

`DitingApp` already assigns `self.title = f"diting v{version}"`
once and `self.sub_title = self._build_subtitle()` in four places
on state change. Those are Textual reactive attributes. The
header widget calls `self.watch(self.app, "title", ...)` and
`self.watch(self.app, "sub_title", ...)` in `on_mount` so changes
take effect immediately, plus a 1-Hz `set_interval` for the clock.
This preserves the existing assignment sites — no `set_title()` /
`set_subtitle()` ceremony is added at every call site.

If `watch()` ever fires before the layout pass has produced a
`size`, the render still works because we ask Rich to do alignment
via `Align.right(...)`, which adapts to whatever width Textual
hands the Static at paint time.

### D4 — Bump the regression-snapshot height from 56 → 60

The current `tui_snapshot.py` runs at `size=(160, 56)`. The
existing one-row Header gives the panels 55 rows of vertical
space. The new four-row BrandHeader leaves 52, which is enough
that the bottom (events) panel still renders, but the BLE
mass-table scenario clips one row that the assertions currently
match against. Bumping the pilot size to `(160, 60)` restores
the previous content area (60 - 4 = 56) and leaves the existing
assertions untouched.

`size=` controls the synthetic terminal Textual gives the App
during `run_test`; it does not affect the real-runtime layout.
Real users on a 30-row terminal already get truncation today;
this change is neutral against that.

### D5 — Underbar as `border-bottom: tall`, not a fourth content row

Textual's `border-bottom: tall <color>` renders a single-cell-tall
line across the bottom edge of a widget using the upper-half-block
glyph in the chosen colour. That is exactly the visual effect we
want for the underbar — a thin orange line separating the brand
header from the panels below. Doing it via the border attribute
keeps the underbar's width tied to the widget's actual rendered
width (so it tracks terminal resizes for free) and makes the
content area cleanly three rows tall, matching the three glyph
rows of the mark.

## Risks / Trade-offs

- **[Risk]** Half-blocks render unevenly in fonts that don't have
  them as a single glyph (renders as boxed fallback). → All four
  fonts the design system permits ship the Block Elements range
  natively. No `tofu` reported in Fira Code / JetBrains Mono /
  SF Mono / Menlo across the testing target macOS versions.
- **[Risk]** A 30-row terminal loses one extra row to the new
  header. → Real users on tiny terminals already cope with
  modal-screen truncation. The four-panel layout uses `1fr` for
  the third slot, which absorbs the lost row gracefully. We
  measured: at 24×80 the Connection / Diagnostics / Scan / Events
  panels all still render; the scan list shrinks by one row.
- **[Risk]** The brand glyph drifts from the SVG source if the
  design system later edits `logo-mark.svg`. → The widget pins
  the glyph data inline (the `_LogoMark.LOGO_ART` constant) and a
  comment cites the source. A future SVG edit needs a one-line
  follow-up here — `tui-audit` will surface the visual drift.
- **[Trade-off]** We do not extend the Header to also show the
  underlying connection / loss / band as Apple's menu-bar does.
  That information is one panel down and we'd rather keep the
  brand area uncluttered than recreate the Connection panel in
  the header.
