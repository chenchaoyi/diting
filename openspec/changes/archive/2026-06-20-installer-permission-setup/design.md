## Context

`_ensure_helper_ready` (`cli.py`) already locates/builds the helper, probes
Location (`_helper.has_permission` — a `scan` that returns ≥1 BSSID) and
Bluetooth (`_helper.has_bluetooth_permission` — the `bluetooth-status`
subcommand), and on a miss `open`s the bundle and polls every 2 s up to 180 s
with per-permission status. The helper's GUI launch
(`HelperAppDelegate.applicationDidFinishLaunching`) already requests all three
grants (Location → Bluetooth → Notifications). The installer (`install.sh` step
6) copies the bundle, strips quarantine, and fires `open` fire-and-forget, then
exits. There is no Notifications probe and no `diting setup` command.

## Goals / Non-Goals

**Goals:**
- Drive + verify the grants at install so first launch is clean.
- A re-runnable `diting setup` with comprehensive error handling + JSON status.
- Verify Notifications (new helper probe), degrading gracefully on old helpers.

**Non-Goals:**
- Granting TCC silently (impossible on macOS — user must click Allow).
- Changing the helper's GUI prompt flow (it already requests all three).
- Any JSON-schema / helper-schema change.
- Blocking CI / non-TTY installs.

## Decisions

### D1 — `diting setup`, sharing one drive-loop with the TUI
Extract the "open bundle + poll grants to completion" logic into a reusable
function (e.g. `permission.ensure_grants(binary, *, interactive, timeout,
on_status)` returning a per-permission result). `diting setup` and
`_ensure_helper_ready` both call it; the TUI keeps its splash callback, `setup`
prints plain status. Keeps one code path for the load-bearing poll loop.

### D2 — Block-and-verify Location + Bluetooth; best-effort Notifications
Location + Bluetooth are required (Wi-Fi scan list, BLE view) → `setup` blocks
on them (poll to grant or timeout). Notifications is optional (only `--notify`)
→ `setup` drives the prompt and verifies if the helper supports the probe, but
NEVER blocks on it and never fails the run for a missing Notifications grant.

### D3 — `notification-status` helper probe + graceful degradation
Add `diting-tianer notification-status`: query
`UNUserNotificationCenter.getNotificationSettings`; exit 0 when
`.authorizationStatus == .authorized` (or `.provisional`), non-zero otherwise.
Python side: `has_notification_permission(binary)` runs it;
`has_notification_status_subcommand(binary)` (a `--help` grep, like
`has_ble_scan_subcommand`) gates whether verification is even possible. On an
older helper without the subcommand, `setup` reports Notifications as
`requested` (state unknown) rather than `denied`, so it never lies.

### D4 — Denied-grant recovery (open Settings + guide)
A grant still missing after the bundle was opened AND a short grace window
elapsed is treated as denied/restricted (macOS won't re-prompt a settled
denial). `setup` then opens the exact Privacy pane via
`open "x-apple.systempreferences:com.apple.preference.security?Privacy_<Pane>"`
(`Privacy_LocationServices` / `Privacy_Bluetooth` / `Privacy_Notifications`) and
prints step-by-step enable instructions. Best-effort: if `open` fails, the
instructions still print.

### D5 — Non-interactive behaviour
`setup` is non-interactive when stdout is not a TTY OR `--json` is given OR
`DITING_SETUP_NONINTERACTIVE=1`. In that mode it probes current state ONCE, does
NOT open the bundle or block, prints (or emits JSON) the per-permission state +
what the user must do, and exits per the convention. This keeps `curl | bash`
under CI and `setup --json` from an agent fast and non-blocking.

### D6 — Exit codes
`0` all required grants present (Notifications best-effort); `1` a required grant
(Location/Bluetooth) is still missing after the flow (so a wrapper can detect the
incomplete state); `2` usage error; helper-absent is `1` with a clear message.
`--json` always exits 0 with the state in the document (an agent reads the flags,
not the code) — except usage errors (2).

### D7 — Installer integration
`install.sh` step 6: copy + de-quarantine as today, then call
`"${BIN_DIR}/diting" setup` (the just-installed binary). On a TTY install this
blocks-and-verifies; the helper's own status window + the OS prompts drive the
clicks, and `setup` confirms. On non-TTY (TIER LOG / CI) the installer passes
`--json` (or sets `DITING_SETUP_NONINTERACTIVE=1`) so it never blocks. The
`DITING_INSTALL_TESTONLY` path keeps emitting its existing markers (adds one for
"would run diting setup") so `test_install.py` stays green. The fire-and-forget
`open` is removed (setup owns the open).

## Risks / Trade-offs

- [Install now pauses for user clicks] → That is the point (block-and-verify, the
  chosen UX). A timeout (e.g. 180 s) bounds the wait; non-TTY never blocks.
- [Notifications verify needs a new helper → only works after the next release] →
  Graceful degradation (D3): old helper ⇒ Notifications reported requested, not
  failed. Location/Bluetooth verify works against the current helper unchanged.
- [Swift change pulls in a helper rebuild + universal2 release build] → The
  subcommand is exit-code-only (no JSON), small and mirrors `bluetooth-status`;
  CI already builds the universal2 helper for releases.
- [`open "x-apple.systempreferences:..."` pane ids drift across macOS versions] →
  Best-effort; the printed instructions are the reliable fallback, and a wrong
  pane still lands the user in System Settings → Privacy.

## Migration Plan

1. Land the helper `notification-status` subcommand + Python probes.
2. Land `diting setup` (shared drive-loop) + dispatch + manifest.
3. Switch `install.sh` step 6 to `diting setup`.
4. Ships in the next release with the rebuilt universal2 helper; older installed
   helpers still work (Location/Bluetooth verified, Notifications best-effort).

## Open Questions

- None blocking. Whether `setup` should also offer a `--repair` that force-opens
  the Settings panes regardless of current state is deferred.
