## 1. Test plan (test-first, per CLAUDE.md hard rule)

- [x] 1.1 Add a "Startup splash" section to `tests/TESTING.md` under the `cli` capability table — frame-data invariants, Tier A/B/C dispatch, status-line tick sequence, splash teardown before alt-screen.
- [x] 1.2 Mirror into `docs/zh/TESTING.md`.

## 2. `src/diting/splash.py` — renderer module

- [x] 2.1 Create `src/diting/splash.py` with module-level constants:
  - `_FRAMES: tuple[str, ...]` — 2 or 3 hand-authored frames, each a multi-line string with the same row / column count as `_LOGO_MARK_ART` in `tui.py:6181`.
  - `_FRAME_INTERVAL_S: float = 0.25` (4 Hz).
  - `_NARROW_THRESHOLD_COLS: int = 30`.
- [x] 2.2 Implement `run_with_splash(steps, *, console=None)` that returns `list[bool]`. Drives Rich `Live` in Tier A, falls back per the design's ladder. Each step renders as `[..]` while in flight, `[✓]` on truthy return, `[✗]` on falsy return or caught exception. Exceptions re-raise after teardown.
- [x] 2.3 Implement Tier B (narrow TTY) via `\r` overwrites without Live — same status semantics, single static beast frame.
- [x] 2.4 Implement Tier C (non-TTY) via a single `print("diting starting...")` and direct callable invocations with no rendering.
- [x] 2.5 Wire the i18n keys for the three status labels.

## 3. `src/diting/cli.py` — host the splash

- [x] 3.1 In `_ensure_helper_ready` (`cli.py:1256`), keep the helper-locate phase (`find_helper` + `try_build` + the `predates 0.5.0` rebuild prose) BEFORE the splash. The splash wraps only the three permission probes.
- [x] 3.2 Build the `steps` list of `(label, callable)` pairs for the three probes; call `splash.run_with_splash(steps)`; consume the resulting `[bool, bool, bool]` into the existing `location_ok` / `bluetooth_ok` variables.
- [x] 3.3 Verify the existing missing-grant flow (helper-bundle `open` + 2 s grant polling) runs cleanly after splash teardown. The instructional `Permissions required:` prose continues to print to stdout, post-splash.

## 4. `src/diting/i18n.py` — catalog entries

- [x] 4.1 Add `"helper located"`, `"checking Location Services"`, `"checking Bluetooth"` to the EN catalog as self-keys (EN source IS the catalog key).
- [x] 4.2 Add ZH translations per the i18n delta spec: `"已找到 helper"`, `"检查 Location Services"`, `"检查 Bluetooth"`.

## 5. Tests

- [x] 5.1 `tests/test_splash.py::test_frames_share_row_and_column_count` — every entry in `_FRAMES` has the same `.splitlines()` length and per-line cell width as `_LOGO_MARK_ART`.
- [x] 5.2 `tests/test_splash.py::test_adjacent_frames_differ_by_at_most_two_cells` — pairwise compare each adjacent frame; assert hamming distance ≤ 2 over the grid.
- [x] 5.3 `tests/test_splash.py::test_run_with_splash_tier_c_non_tty` — Console fixture with `is_terminal=False`, run two callables; assert single `"diting starting..."` line printed, both callables invoked, return list is `[True, True]`.
- [x] 5.4 `tests/test_splash.py::test_run_with_splash_tier_b_narrow` — Console fixture with `is_terminal=True` + `size.width=20`; assert no Live driver instantiated, beast frame printed once, statuses updated via `\r`.
- [x] 5.5 `tests/test_splash.py::test_run_with_splash_tick_sequence` — Tier C mode, three callables; assert each returns in order and the result list reflects the truthy / falsy responses.
- [x] 5.6 `tests/test_splash.py::test_run_with_splash_callable_falsy_marks_step_failed` — one callable returns False; assert that step appears as `[✗]` in the captured output and the function returns `[True, False, True]` (subsequent steps still run).
- [x] 5.7 `tests/test_splash.py::test_run_with_splash_callable_raising_reraises_after_teardown` — callable raises `OSError`; assert the exception propagates AFTER teardown (no live cursor leak), step is `[✗]`.
- [x] 5.8 `tests/test_splash.py::test_run_with_splash_zh_locale` — set ZH, run a single step; assert status labels render with `检查 Location Services` etc.
- [x] 5.9 `tests/test_cli.py::test_ensure_helper_ready_drives_splash_for_two_tcc_probes` — monkeypatch `_helper.has_permission` + `_helper.has_bluetooth_permission`; assert `splash.run_with_splash` is called once with a 3-element steps list (helper / Location / Bluetooth).

## 6. CI gates

- [x] 6.1 `uv run pytest` — green
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression` — unaffected, green
- [x] 6.3 `openspec validate --specs --strict` — green
- [x] 6.4 `openspec validate startup-splash --strict` — green

## 7. Manual visual check

- [ ] 7.1 Run `uv run diting` in a normal-width iTerm2 tab; confirm splash renders without flicker, status ticks visibly through the three steps, teardown is clean.
- [ ] 7.2 Run `uv run diting | cat`; confirm Tier C fallback prints `diting starting...` and nothing else.
- [ ] 7.3 Run `uv run diting` in a 20-column window; confirm Tier B static frame + `\r` updates.
- [ ] 7.4 Run `DITING_LANG=zh uv run diting`; confirm the three status labels read in Chinese.
- [ ] 7.5 With Bluetooth permission temporarily revoked (TCC reset), confirm splash shows `[✗] 检查 Bluetooth` and the existing missing-permission prompt flow runs unaffected after teardown.

## 8. Wrap-up

- [x] 8.1 EN ↔ ZH parity check on `i18n.py` and the TESTING entries.
- [ ] 8.2 Commit and push the branch `feat/startup-splash`.
- [ ] 8.3 Open the PR using the repo template.
