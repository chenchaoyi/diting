## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` — replace the row that describes the help modal opening / closing via `h` with `?`. Update the "Each binding (`q`, `p`, `r`, `s`, `c`, `h`, `n`)" row to drop `h` (it's a no-op now) and add `?` to the bound set.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. tui — rebind help modal

- [x] 2.1 `src/diting/tui.py::DitingApp.BINDINGS` — change `Binding("h", "show_help", t("Help"))` to `Binding("question_mark", "show_help", t("Help"))`. The Textual key-name for `?` is `question_mark`.
- [x] 2.2 `src/diting/tui.py::HelpScreen.BINDINGS` — change `Binding("escape,h,q", "app.pop_screen", t("Close"))` to `Binding("escape,question_mark,q", "app.pop_screen", t("Close"))`. Update the class docstring's "dismissed by Esc or h again" to reference `?`.
- [x] 2.3 `src/diting/tui.py::DitingApp.compose` (or wherever the GroupedFooter info group is built) — change the footer-group label tuple `("h", t("Help"))` to `("?", t("Help"))`.
- [x] 2.4 `src/diting/tui.py` — modal scroll-hint passes `t("↑/↓/PgUp/PgDn to scroll  ·  Esc or ? to close")` (and the i18n key value updates accordingly).
- [x] 2.5 `src/diting/tui.py` — help-body content (`line("h", t("toggle this help"))` and the navigation comment `**Info**: ``h`` help · ``b`` basics`) updates to `?`.

## 3. i18n catalog

- [x] 3.1 `src/diting/i18n.py` — rename catalog keys `"Esc or h to close"` → `"Esc or ? to close"` and `"↑/↓/PgUp/PgDn to scroll  ·  Esc or h to close"` → `"↑/↓/PgUp/PgDn to scroll  ·  Esc or ? to close"`. Update the ZH translations to use `?` too: `"Esc 或 ? 关闭"`.

## 4. Docs

- [x] 4.1 `README.md` — change `| h | open / close the in-app help screen |` to `| ? | open / close the in-app help screen |`. Change inline "Press `h` inside the TUI" to "Press `?` inside the TUI".
- [x] 4.2 `docs/zh/README.md` — same. Mirror.

## 5. Tests

- [x] 5.1 `tests/test_tui_smoke.py` — `test_help_modal_open_and_close` uses `("h", "escape")` → `("question_mark", "escape")`; `test_help_modal_h_to_close` (rename to `test_help_modal_question_mark_to_close`) uses `("h", "h")` → `("question_mark", "question_mark")`; `test_help_modal_renders_through_pilot_query` uses `await pilot.press("h")` → `await pilot.press("question_mark")`.
- [x] 5.2 New test: `test_pressing_h_is_a_no_op` — drive the App, press `h`, assert the screen stack still has just the main view.

## 6. CI gates

- [x] 6.1 `uv run pytest`
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 6.3 `openspec validate --specs --strict`
- [x] 6.4 `openspec validate help-key-question-mark --strict`
