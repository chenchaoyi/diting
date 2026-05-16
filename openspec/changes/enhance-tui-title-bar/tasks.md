## 1. BrandHeader widget

- [x] 1.1 Add `_LogoMark` Static widget to `src/diting/tui.py` — fixed
      width 11, height 3, foreground `#fea62b`, content the 3-row half-
      block rendering of `docs/design/diting-design/assets/logo-mark.svg`.
- [x] 1.2 Add `_TitleStack` Static widget — width `1fr`, height 3.
      Pulls live state from `app.title` / `app.sub_title` and renders
      a Rich `Group` of three lines: clock (right-aligned, dim), title
      (bold, foreground white), subtitle (dim). `on_mount` hooks
      `self.watch(self.app, "title", ...)`, `self.watch(self.app,
      "sub_title", ...)`, and `set_interval(1.0, ...)` for the clock.
- [x] 1.3 Add `BrandHeader` Horizontal container — height 4,
      background `#121212`, `border-bottom: tall #fea62b`. Composes
      `_LogoMark` then `_TitleStack`.

## 2. Wire BrandHeader into DitingApp

- [x] 2.1 Replace `yield Header(show_clock=True)` in
      `DitingApp.compose()` with `yield BrandHeader(id="brand-header")`.
- [x] 2.2 Drop the now-unused `Header` import from
      `from textual.widgets import ...`.

## 3. Regression snapshot height

- [x] 3.1 Bump `pilot.app.run_test(size=...)` in
      `scripts/tui_snapshot.py` from `(160, 56)` to `(160, 60)` so the
      four-row brand header does not eat into the captured panel area.

## 4. Tests

- [x] 4.1 Extend `tests/test_tui_smoke.py` with
      `test_brand_header_renders_logo_mark` — assert a `BrandHeader`
      mounts and its rendered text contains at least one of the
      half-block glyphs (`▀` / `█` / `▄`).
- [x] 4.2 Extend `tests/test_tui_smoke.py` with
      `test_brand_header_carries_live_title_and_subtitle` — after
      construction, the header renders the App's title and subtitle
      strings (`diting v<...>` and `view: wifi · scan 7s`).

## 5. TESTING.md updates (EN + ZH parity)

- [x] 5.1 Update `tests/TESTING.md` `tui-shell` section:
      replace the `(gap — no subtitle assertion in pytest)`
      annotation on the "Header shows title + clock; subtitle
      reflects live state" row with the two new test IDs, and add
      a fresh row "Brand mark visible in the header".
- [x] 5.2 Mirror the same EN edit into `docs/zh/TESTING.md` so the
      ZH plan stays in parity.

## 6. Gates

- [x] 6.1 `uv run pytest` passes (existing + new tests).
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
      passes (the height bump may shift assertion content; re-run
      to confirm no regressions).
- [x] 6.3 `openspec validate --specs --strict` passes.
- [x] 6.4 `openspec validate enhance-tui-title-bar --strict` passes.
