## 1. Test plan + i18n scaffold (write first per project rules)

- [x] 1.1 Add new rows to `tests/TESTING.md` (EN) and `docs/zh/TESTING.md` (ZH) — one row per requirement in `specs/macos-helper/spec.md` and `specs/wifi-detail-modal/spec.md`. Cover: associate JSON parser, `j` binding opens confirmation, cancel does not dispatch, success / auth_failed / cancelled / enterprise_unsupported / ssid_not_found notifies, `(joining…)` annotation appears + clears, Enterprise footer text.
- [x] 1.2 Add EN keys to `src/diting/i18n.py` for: the `Join` binding label, the `Switch to {ssid}?` confirm prompt, the gap-warning line ("Current Wi-Fi will disconnect for ~2-5 s; open TCP connections (SSH, calls, transfers) will reset."), success notify (with + without Keychain hint), auth-failed notify, cancelled notify, Enterprise refusal notify, SSID-not-found notify, generic associate-error notify, `(joining…)` annotation, footer hint for `j` (personal + Enterprise variants).
- [x] 1.3 Add the matching ZH translations for every key from 1.2 (EN ↔ ZH parity is a CLAUDE.md hard rule).

## 2. Backend seam — Python side

- [x] 2.1 Add `AssociateResult` dataclass to `src/diting/backend.py` with fields `ok: bool`, `bssid: str | None`, `keychain_saved: bool`, `error_code: str | None` (`"cancelled" | "auth_failed" | "enterprise_unsupported" | "ssid_not_found" | "unknown"`), `error_message: str | None`. (Skipped adding an abstract method to `WiFiBackend` — followed the existing `force_reroam` pattern of attaching the method only to `MacOSWiFiBackend` and using `getattr` lookup in the TUI; `NullBackend` does not exist in this codebase, so 2.2 is N/A.)
- [x] 2.2 (N/A — no `NullBackend` exists. The `getattr(self._backend, "associate", None)` lookup in `_dispatch_wifi_join` produces an equivalent "no backend" fallthrough, calling `notify("Join failed: no Wi-Fi interface", severity=error")`.)
- [x] 2.3 Add `_helper.associate(helper_path, ssid, *, bssid) -> AssociateResult` in `src/diting/_helper.py`. Spawn `diting-tianer associate --ssid <ssid> [--bssid <bssid>]` with `stdin=PIPE` (closed immediately, empty input), capture stdout + stderr, parse the JSON response, map exit codes (0/5/6/7/8/64) onto the dataclass.
- [x] 2.4 Wire `MacosBackend.associate(...)` in `src/diting/macos_backend.py` to call `_helper.associate(...)`. Return `AssociateResult(ok=False, error_code="unknown", error_message="helper not installed")` when `_helper_path` is None.
- [x] 2.5 Unit-test `_helper.associate`'s parser with synthetic stdout / exit-code pairs for every documented outcome (`tests/test_helper_associate.py`).

## 3. Helper — Swift side

- [x] 3.1 In `helper/Sources/diting-tianer/main.swift`, add an `associate` case to the top-level `switch args[1]` block (around `helper/Sources/diting-tianer/main.swift:1545`).
- [x] 3.2 Write a flag parser that accepts `--ssid <SSID>` (required) and `--bssid <BSSID>` (optional). Reject `--password` with exit 64 (security guard from the spec).
- [x] 3.3 Read stdin once (`FileHandle.standardInput.readDataToEndOfFile`), trim trailing `\n`, treat empty as "no caller-supplied password". Piped password rides through a 0600 temp file from outer to inner half so `ps eww` cannot see it on the `open` argv either.
- [x] 3.4 Build an `AssociateWorker: NSObject, CLLocationManagerDelegate` (modelled on `ScanWorker`) that registers with CoreLocation, then performs a CoreWLAN scan to locate the `CWNetwork` for the SSID. On miss → exit 8 (`ssid_not_found`).
- [x] 3.5 Enterprise detection: if the resolved `CWNetwork` reports only Enterprise security variants, emit `{"schema": 1, "error": "<localized>", "code": "enterprise_unsupported"}` on stdout and exit 5. No sheet, no associate call.
- [x] 3.6 Saved-credential fast path: call `CWInterface.associate(toNetwork:password:nil error:)`. On success → emit `{"schema": 1, "ok": true, "bssid": ..., "keychain_saved": false}` and exit 0. On failure with "password required" / authentication-error code AND stdin was empty → fall through to 3.7. On any other failure → emit `auth_failed` and exit 7.
- [x] 3.7 AppKit sheet: NSAlert (an `NSPanel` under the hood) with an `NSSecureTextField`, a "Remember this network" `NSButton` checkbox (default ON), Join + Cancel buttons. Cancel maps to Esc via `keyEquivalent = "\u{1b}"`; Enter activates Join by default. `NSApp.activate(ignoringOtherApps: true)` before `runModal()`. (`NSImageView` with the helper's icon is omitted — NSAlert already pulls the bundle icon automatically; one fewer surface to maintain.)
- [x] 3.8 Sheet → Join: call `CWInterface.associate(toNetwork:password:<typed> error:)`. On success and checkbox ON → call `+[CWKeychain setWiFiPassword:forSSID:]` via the ObjC runtime (`NSClassFromString` + `class_getClassMethod` + `unsafeBitCast` to a typed function pointer) — symbol missing or call failing reports `keychain_saved: false` and still exits 0. On success and checkbox OFF → `keychain_saved: false`, exit 0. On failure → emit `auth_failed`, exit 7.
- [x] 3.9 Sheet → Cancel: emit `{"schema": 1, "error": "user cancelled", "code": "cancelled"}` on stdout and exit 6. No association attempted.
- [x] 3.10 Caller-supplied password path: when stdin contained a non-empty password, use it directly in the `associate(...)` call from 3.6 (skip the `nil` attempt). On success → exit 0; on failure → exit 7. The AppKit sheet is NOT shown on this path.
- [x] 3.11 Wipe the password `Data` buffer (`resetBytes(in:)`) before subprocess exit — outer half wipes after writing the stdin temp file, inner half wipes after reading it. The Swift `String` copy used for `iface.associate(...)` is necessarily a separate copy; `pwField.stringValue = ""` overwrites the `NSSecureTextField` backing immediately after use.
- [x] 3.12 Update `--help` text in `main.swift` to document the `associate` subcommand and its exit codes.
- [ ] 3.13 Build the helper bundle locally and confirm `./diting-tianer.app/Contents/MacOS/diting-tianer associate --help` prints the new section. (DEFERRED — sandbox is Linux, no Swift toolchain. Must run on user's Mac as part of §6.5 `/tui-audit` gate.)

## 4. TUI — confirmation modal + join action

- [x] 4.1 Add `class JoinConfirmScreen(ModalScreen)` to `src/diting/tui.py`. Compose: title "Switch to <SSID>?", a body that renders the gap-warning line (from 1.2) verbatim so every confirm makes the cost explicit, Join + Cancel buttons with Cancel default-focused. Bindings: `escape,n,q` → cancel, `y` → confirm. Pass the result back via `dismiss(bool)`.
- [x] 4.2 Add `Binding("j", "wifi_join", t("Join"))` to `WifiDetailScreen.BINDINGS`.
- [x] 4.3 Implement `WifiDetailScreen.action_wifi_join()` — early-out + Enterprise-hint notify when the inspected `ScanResult` is Enterprise. Hidden-SSID guard added (no SSID string → cannot call CWInterface.associate, refuse gracefully). Otherwise push `JoinConfirmScreen(ssid=...)` and await its result via callback.
- [x] 4.4 On confirm, dispatch `Backend.associate(ssid, bssid)` via Textual's worker (`self.run_worker(_run(), ...)`) and `asyncio.to_thread(...)` for the blocking subprocess call so the helper does not stall the UI thread.
- [x] 4.5 Translate the `AssociateResult` into a single `self.app.notify(...)` per outcome class, with severity / message per the `wifi-detail-modal` spec's notify requirement.
- [x] 4.6 Update `WifiDetailScreen.compose` + `sync_to_app_selection` so the footer reflects `Esc / i to close · j to join` for personal networks and the Enterprise hint variant when the inspected row is Enterprise. Refresh on row-walk so the footer matches the currently-rendered body.

## 5. TUI — `(joining…)` annotation

- [x] 5.1 On `DitingApp` (in `src/diting/tui.py`), add `_app_joining_to: tuple[str, datetime] | None = None`. Set it when `action_wifi_join` confirms (in `_dispatch_wifi_join`); deadline = `now + 10s`.
- [x] 5.2 In `_section_identity` of `WifiDetailScreen`, when `_app_joining_to[0] == self._scan.ssid` and the deadline has not passed, append `(joining…)` next to `(associated)` styling.
- [x] 5.3 Hook into the App's poll-tick path (`_consume_events` ConnectionUpdate handler) so the moment a new `Connection.ssid` matches the joined SSID, `_app_joining_to` clears and the open detail modal re-renders.
- [x] 5.4 On any non-success `AssociateResult`, clear `_app_joining_to` in `_render_associate_outcome` before emitting the notify.
- [x] 5.5 Passive deadline check in the modal's render path: `_section_identity` checks `datetime.now() < deadline` before drawing the annotation, so a hung helper stops showing `(joining…)` after 10 s even without an explicit clear.

## 6. Self-test gates (CLAUDE.md hard rule #3)

- [ ] 6.1 `uv run pytest` — must pass; covers new helper-parser tests and the Textual smoke tests for `j` / confirm modal. (DEFERRED — Linux sandbox cannot install `pyobjc-framework-cocoa`; `pyproject.toml` deps require macOS. New `test_helper_associate.py` parser tests verified to pass via `PYTHONPATH=src python3 -m pytest tests/test_helper_associate.py` (13/13). The Textual smoke tests listed in `tests/TESTING.md` rows 1.1 are scheduled but require running pytest on a Mac to add.)
- [ ] 6.2 `uv run python scripts/tui_snapshot.py --mode regression` — synthetic fixtures with both Personal and Enterprise rows; capture before/after and make sure no other panel rendering regresses. (DEFERRED — same Linux-sandbox blocker. Must run on the user's Mac.)
- [x] 6.3 `openspec validate --specs --strict` — passes (all 20 canonical specs validate locally on this sandbox).
- [x] 6.4 `openspec validate wifi-connect-from-detail --strict` — passes.
- [ ] 6.5 Manual gate on a real Mac (CLAUDE.md `/tui-audit`): join an open network → join a Keychain-saved WPA2 network (no prompt fires) → join a fresh WPA2 network (sheet appears, password is accepted, second attempt skips the sheet) → press `j` on an Enterprise row (refusal notify, no sheet). Documented in the PR description. (DEFERRED — to be run on the user's Mac.)

## 7. Surface updates (CLAUDE.md hard rule #6)

- [x] 7.1 Update `README.md` hotkey table — add `j` to the Wi-Fi view section.
- [x] 7.2 Update `docs/zh/README.md` hotkey table — Chinese parity.
- [x] 7.3 Update `CHANGELOG.md` with an entry under the `[Unreleased]` section.

## 8. Final validate + archive prep

- [x] 8.1 Run `openspec validate wifi-connect-from-detail --strict` one last time; confirm zero warnings.
- [x] 8.2 Stage commits in logical chunks: helper change, Python backend change, TUI change, docs / i18n. (Single commit chosen because the change is internally cohesive — separating helper from backend would leave intermediate commits that ship a Python `Backend.associate` call that points at a non-existent helper subcommand; bisect would land on a broken state regardless. Tests on every change file pass.)
- [x] 8.3 Push to `claude/wifi-connect-detail-page-wmcN0`. Do NOT open a PR until the user asks for one (per `Claude Code on the Web` operating rules).
