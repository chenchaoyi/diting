## Why

The installer copies the helper bundle and fires `open` once to surface the TCC
prompts — but it's fire-and-forget (`2>/dev/null || true`) and exits immediately
without waiting, verifying, or handling failure. If the user dismisses or misses
a prompt, the *first* `diting` launch re-prompts — exactly the "I have to grant
again" friction the user wants gone. The robust "open + poll each grant to
completion with per-permission status" loop already exists, but only runs at TUI
launch (`_ensure_helper_ready`), not at install. This change drives and verifies
the grants at install time so the first launch just works, and adds a
re-runnable `diting setup` that owns this flow with comprehensive error handling.

Hard constraint (documented, not worked around): macOS TCC grants cannot be set
programmatically — the user must click "Allow". `setup` drives the OS prompts and
verifies the outcome; it does not (cannot) grant silently.

## What Changes

- Add **`diting setup`** — locate/prime the helper, open it to trigger the OS
  prompts, then **block-and-verify** Location + Bluetooth (the two grants
  required for core function) by polling until granted or a timeout, with live
  per-permission status. It also drives the Notifications prompt (best-effort).
  Comprehensive error handling:
  - no helper / helper not in an `.app` bundle → clear, actionable message;
  - a **previously-denied** grant (macOS won't re-prompt) → detect it, **open
    System Settings to the exact Privacy pane**, and print step-by-step
    instructions;
  - **non-interactive** (non-TTY / CI / `--json`) → do NOT block; report current
    state + instructions and exit per the documented convention;
  - timeout → proceed with partial state and a clear summary;
  - `--json` → one machine-readable status object (per-permission granted flags).
- Extract the install/TUI permission-driving loop into one reusable headless
  routine used by both `diting setup` and the TUI's `_ensure_helper_ready`.
- Add a **`notification-status`** probe subcommand to the Swift helper (mirrors
  `bluetooth-status`: exit 0 when Notifications authorization is granted, non-zero
  otherwise) so `setup` can VERIFY the Notifications grant, not just request it.
  `setup` degrades gracefully against an older helper that lacks the probe
  (reports Notifications as requested-but-unverified rather than failing).
- The **installer** runs `diting setup` after copying + de-quarantining the
  helper, so grants complete and are verified during install. Non-TTY installs
  (CI / piped) stay non-blocking. `DITING_INSTALL_TESTONLY` keeps its markers.
- `capabilities` + `--help` gain the `setup` verb.

## Capabilities

### New Capabilities
- `permission-setup`: the `diting setup` flow — drive + verify Location /
  Bluetooth / Notifications, denied-grant recovery (open Settings + guide),
  non-interactive behaviour, JSON status, and the exit-code convention.

### Modified Capabilities
- `cli`: add `setup` to the canonical subcommand vocabulary; manifest + `--help`.
- `installation`: the installer SHALL drive + verify the TCC grants at install
  (via `diting setup`) instead of a fire-and-forget `open`, while staying
  non-blocking on non-TTY installs.
- `macos-helper`: add the `notification-status` probe subcommand to the helper's
  Python-integration surface.

## Impact

- `src/diting/cli.py` — new `_run_setup`; `setup` in the `_COMMANDS` table +
  canonical verbs + dispatch. Extract the permission-driving loop (shared by
  `_ensure_helper_ready`).
- `src/diting/_helper.py` — `has_notification_permission(binary)` +
  `has_notification_status_subcommand(binary)` probes; a System-Settings-pane
  opener helper.
- `helper/Sources/diting-tianer/main.swift` — new `notification-status`
  subcommand (UNUserNotificationCenter `getNotificationSettings`, exit-code
  only). No JSON-schema change → no helper schema bump. Requires a helper
  rebuild; the universal2 bundle ships in the next release.
- `install.sh` — step 6 invokes `diting setup` after copy + de-quarantine;
  non-TTY stays non-blocking; TESTONLY markers preserved.
- `tests/` — `tests/test_setup.py` (drive/verify with fake probes, denied path,
  non-TTY, JSON, timeout) + `test_cli.py` (`setup` routing + manifest) +
  `test_helper.py` (notification-status probe + graceful degradation) +
  `test_install.py` (the new step-6 invocation marker). Update `tests/TESTING.md`
  (EN + ZH) first.
- `docs/agents.md` + zh, `README.md` + zh, `docs/RELEASE.md` if the helper-build
  note needs it. EN ↔ ZH parity throughout.
