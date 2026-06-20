## 1. Test plan first

- [x] 1.1 Update `tests/TESTING.md` (EN) — new `permission-setup` section (drive/verify, denied→Settings, non-TTY/JSON non-blocking, helper-missing, exit codes), a `macos-helper` row for `notification-status`, an `installation` row for the step-6 `diting setup` invocation, and a `cli` row for the `setup` verb
- [x] 1.2 Mirror into `docs/zh/TESTING.md` (ZH parity)

## 2. Helper: notification-status probe

- [x] 2.1 Add a `notification-status` subcommand to `helper/Sources/diting-tianer/main.swift` — `getNotificationSettings` → exit 0 on `.authorized`/`.provisional`, non-zero otherwise; bounded ~few-second timeout; list it in `--help`
- [x] 2.2 Rebuild the helper locally (`./helper/build.sh`) and verify `notification-status` exit codes by hand

## 3. Python probes + shared drive-loop

- [x] 3.1 `_helper.has_notification_permission(binary)` (runs `notification-status`) + `_helper.has_notification_status_subcommand(binary)` (`--help` grep, like `has_ble_scan_subcommand`)
- [x] 3.2 `_helper` (or new module): a System-Settings Privacy-pane opener (`open "x-apple.systempreferences:…Privacy_<Pane>"`) + the per-permission pane map
- [x] 3.3 Extract the shared primitives (probe, open-bundle, open-Settings-pane) into `permission.py`; `diting setup` uses them. The TUI's `_ensure_helper_ready` keeps its existing splash-driven probe/poll path (load-bearing + test-covered) — converging it onto the shared loop is deferred to avoid regressing TUI launch

## 4. `diting setup`

- [x] 4.1 `_run_setup(args)`: locate/build helper → graceful error if absent/not-a-bundle; interactive = TTY and not `--json` and not `DITING_SETUP_NONINTERACTIVE`
- [x] 4.2 Interactive: open bundle (locale-threaded `DITING_LANG`/`-AppleLanguages`), block-and-verify Location+Bluetooth (poll to grant/timeout, live status); drive Notifications best-effort (verify if probe available, else unknown)
- [x] 4.3 Denied recovery: after grace window, a still-missing required grant → open the exact Privacy pane + print enable instructions
- [x] 4.4 Non-interactive: probe-once, no open/block; print per-permission state + guidance
- [x] 4.5 `--json`: one object (`location`/`bluetooth`/`notifications` granted-or-unknown + overall readiness) to stdout, prose to stderr, locale-stable keys; exit-code convention (0 ready, 1 required-missing, 2 usage)
- [x] 4.6 Add `setup` to `_COMMANDS` table + canonical verbs; route in `_dispatch`

## 5. Installer

- [x] 5.1 `install.sh` step 6: after copy + `xattr` de-quarantine, invoke `"${BIN_DIR}/diting" setup` with the locale-appropriate `DITING_LANG`; non-TTY (TIER log) → non-interactive (`--json` / `DITING_SETUP_NONINTERACTIVE=1`); remove the fire-and-forget `open`
- [x] 5.2 Preserve `DITING_INSTALL_TESTONLY` markers (add a "would run diting setup" marker) so `test_install.py` stays green; keep tier rendering intact

## 6. Tests

- [x] 6.1 `tests/test_setup.py`: fake probes → drive/verify success; required-missing→exit 1; denied path opens pane (patched `open`); non-TTY + `--json` non-blocking (no bundle open); helper-missing graceful exit; Notifications unknown on old helper
- [x] 6.2 `tests/test_helper.py`: `has_notification_permission` + `has_notification_status_subcommand` (patched subprocess)
- [x] 6.3 `tests/test_cli.py`: `setup` routing + manifest entry; `setup --help`
- [x] 6.4 `tests/test_install.py`: step-6 emits the `diting setup` marker under TESTONLY
- [x] 6.5 `uv run pytest`

## 7. Docs + parity

- [x] 7.1 `docs/agents.md` (+ zh): document `diting setup` (and that it's how install grants are completed)
- [x] 7.2 `README.md` (+ zh): mention `diting setup` for permission (re)granting
- [x] 7.3 Any new user-facing `t()` strings get EN + ZH catalog entries

## 8. Gates

- [x] 8.1 `uv run pytest`
- [x] 8.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 8.3 `openspec validate --specs --strict` and `openspec validate installer-permission-setup --strict`
