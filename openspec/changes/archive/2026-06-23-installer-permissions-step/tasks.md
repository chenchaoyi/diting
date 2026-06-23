# Tasks

## Installer step 7
- [x] `install.sh`: introduce `STEP_TOTAL=7`; replace the hard-coded `/6` in
      `step` / `die_with_marker` with it
- [x] Add a `step_open` header helper (numbered row, no trailing ✓) and render
      the grant as `[7/7] Permissions`, framing `diting setup`'s indented output
      (both the real and TESTONLY branches)
- [x] `test_install.py`: assert `[6/7]` + `[7/7]` + `Permissions` (was `[6/6]`)

## Notifications visibility
- [x] `_helper.notification_status` returns a status string (authorized /
      denied / not_determined / unknown) via the `notification-status` exit codes
- [x] `permission.probe` returns Notifications as that status (or None on an
      older helper)
- [x] `_run_setup`: live status line shows all three; after the required grants
      land, wait a bounded grace for Notifications to settle before reporting
- [x] `_setup_state_json` / `_maybe_report_notifications` read the status
      (authorized → granted; pending shown as waiting, not denied)

## Tests + docs
- [x] `tests/TESTING.md` + `docs/zh/TESTING.md` rows BEFORE test code
- [x] `test_setup.py`: notifications status string in the line + `--json` map;
      grace lets a pending Notifications settle
- [x] Run all four CI gates
