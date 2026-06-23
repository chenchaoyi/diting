## Why

During a `/tui-audit` (and any repeated scanning while Location is ungranted)
the macOS Location prompt re-popped on **every** scan tick. Root cause: the
helper's `scan` subcommand calls `requestWhenInUseAuthorization()` (and
`startUpdatingLocation()`) unconditionally on every invocation. When the bundle's
Location authorization is `notDetermined` — e.g. a freshly-rebuilt cdhash after a
release, which is exactly the audit's situation — each scan fires a fresh prompt.
Because `scan` runs once per poll tick, the dialog stacked up.

Surfacing the prompt is the GUI helper's job (one dialog, driven by the
install / `diting setup` / TUI auto-launch flow). The scan should never be a
prompt source.

## What Changes

- The `scan` subcommand registers as a CoreLocation consumer by assigning a
  delegate (which delivers the settled authorization via the callback WITHOUT
  prompting — the same mechanism `location-status` uses) and only registers +
  scans (`requestWhenInUseAuthorization` is a no-op for an already-authorized
  bundle) once the status has settled to authorized. For `notDetermined` /
  `denied` / `restricted` it emits a redacted scan and never calls
  `requestWhenInUseAuthorization`.
- Verified locally against the current `notDetermined` machine: `scan` returns
  redacted JSON in ~6 s and three back-to-back scans pop **zero** dialogs (was: a
  prompt per scan).

## Impact

- Specs: `macos-helper` (the `scan` subcommand never prompts).
- Code: `helper/Sources/diting-tianer/main.swift` (`ScanWorker`). Needs a helper
  rebuild. No Python change. The authorized scan path is byte-identical to before
  (still `requestWhenInUseAuthorization` + `startUpdatingLocation` +
  scan-with-retry) — only the prompting on a non-authorized status is removed.
