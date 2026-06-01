# Per-run mute: a --no-companion flag for self-test

## Why

Self-testing the TUI while paired floods the phone with push notifications —
every scanned device / event is forwarded to the relay → APNs doorbell. The
env `DITING_COMPANION=0` already suppresses this, but it's undiscoverable and
easy to forget, and the explore/audit harness didn't set it, so a `/tui-audit`
run could spam a paired device.

## What Changes

- Add a global `--no-companion` flag (default TUI subcommand + `monitor`) that
  sets `DITING_COMPANION=0` for the run, so `build_sink` returns None and no
  event is forwarded. Pairing on disk is untouched — it's a per-run mute.
- The explore/self-test harness (`scripts/tui_snapshot.py --mode explore`)
  pins `DITING_COMPANION=0`, so an audit never forwards regardless.

## Impact

- Affected specs: `companion-bridge` (opt-in requirement gains a per-run
  disable).
- Affected code: `src/diting/cli.py` (flag + help), `scripts/tui_snapshot.py`,
  README EN/ZH.
- No protocol/wire change; pairing state untouched.
