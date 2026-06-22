# Tasks

## Helper window
- [x] Rewrite `HelperAppDelegate` window: top-aligned constraints (no void),
      app icon, title, secondary intro, per-permission status rows with
      color-coded glyphs (brand orange for the active step), content-fit sizing
- [x] Add `closingWindow` neutral footnote string (EN+ZH) for the denied-outcome
      auto-close case

## Latency
- [x] `runLocationStatusProbe` honors `DITING_LOC_SETTLE` (default 4.0)
- [x] `_helper.location_status` / `_auth_status` accept a `settle` override and
      set the env on the subprocess
- [x] `permission.probe` accepts `settle` and threads it into the Location probe
- [x] `_run_setup` opens the bundle before any blocking probe; interactive
      pre-check uses a short settle; `--json` / non-interactive keep default

## Installer output
- [x] `_run_setup` left-pads human output by `DITING_SETUP_INDENT`
- [x] `install.sh` sets `DITING_SETUP_INDENT` so setup lines align under the
      helper step

## Tests + docs
- [x] `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` (ZH) rows BEFORE test code
- [x] `test_setup.py`: indent env pads output; pre-check passes a settle;
      `--json` unaffected
- [x] Build helper, run all four CI gates
