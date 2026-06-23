## Why

Two install-time gaps from a user screenshot:

- **The permission-granting block is loose text, not a numbered step.** The
  installer renders `[1/6]…[6/6]` and then dumps `diting setup`'s output below
  step 6 as un-framed lines. It should be the installer's own final numbered
  step so the grant reads as part of the structured flow.
- **Notifications never shows.** `setup`'s live status line prints only Location
  and Bluetooth, and the poll returns the instant those two (the *required*
  grants) land — which is before the user has even answered the Notifications
  prompt (the helper requests it third). So the third permission the installer
  promised ("Location → Bluetooth → Notifications") is invisible, and the
  best-effort note prints "not granted" while the prompt is still pending.

## What Changes

- **Add a 7th installer step, `Permissions`,** that frames `diting setup`'s
  (indented) output as the final numbered step. The step total goes 6 → 7;
  `Permissions` is the last step.
- **Show all three permissions in `setup`'s live status** (Location, Bluetooth,
  Notifications) and **wait a bounded grace** after the required grants land for
  the best-effort Notifications prompt to settle before reporting — rather than
  exiting the moment Location + Bluetooth land. Notifications is read as a
  distinct status (pending / denied / granted), so a not-yet-answered prompt
  shows as `waiting`, not `not granted`.

## Impact

- Specs: `installation` (numbered Permissions step), `permission-setup`
  (Notifications visibility + settle grace).
- Code: `install.sh` (step total 7 + `Permissions` step), `src/diting/cli.py`
  (`_run_setup` three-way status + grace; `_setup_state_json` /
  `_maybe_report_notifications` for the status read), `src/diting/_helper.py`
  (`notification_status` string probe), `src/diting/permission.py` (probe
  returns a Notifications status). No helper rebuild required (Python +
  shell only; the `notification-status` subcommand already exists).
