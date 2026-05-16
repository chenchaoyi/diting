## 1. Test plan + i18n scaffold (write first per project rules)

- [ ] 1.1 Add new rows to `tests/TESTING.md` (EN) and `docs/zh/TESTING.md` (ZH) — one row per requirement in `specs/macos-helper/spec.md` and `specs/wifi-detail-modal/spec.md`. Cover: associate JSON parser, `j` binding opens confirmation, cancel does not dispatch, success / auth_failed / cancelled / enterprise_unsupported / ssid_not_found notifies, `(joining…)` annotation appears + clears, Enterprise footer text.
- [ ] 1.2 Add EN keys to `src/diting/i18n.py` for: the `Join` binding label, the `Switch to {ssid}?` confirm prompt, the gap-warning line ("Current Wi-Fi will disconnect for ~2-5 s; open TCP connections (SSH, calls, transfers) will reset."), success notify (with + without Keychain hint), auth-failed notify, cancelled notify, Enterprise refusal notify, SSID-not-found notify, generic associate-error notify, `(joining…)` annotation, footer hint for `j` (personal + Enterprise variants).
- [ ] 1.3 Add the matching ZH translations for every key from 1.2 (EN ↔ ZH parity is a CLAUDE.md hard rule).

## 2. Backend seam — Python side

- [ ] 2.1 Add `AssociateResult` dataclass to `src/diting/backend.py` with fields `ok: bool`, `bssid: str | None`, `keychain_saved: bool`, `error_code: str | None` (`"cancelled" | "auth_failed" | "enterprise_unsupported" | "ssid_not_found" | "unknown"`), `error_message: str | None`. Add abstract `Backend.associate(self, ssid: str, *, bssid: str | None = None) -> AssociateResult`.
- [ ] 2.2 Implement `NullBackend.associate(...)` returning an `AssociateResult(ok=False, error_code="unknown", error_message="no backend")` so headless tests / fallbacks degrade safely.
- [ ] 2.3 Add `_helper.associate(helper_path, ssid, *, bssid) -> AssociateResult` in `src/diting/_helper.py`. Spawn `diting-tianer associate --ssid <ssid> [--bssid <bssid>]` with `stdin=PIPE` (closed immediately, empty input), capture stdout + stderr, parse the JSON response, map exit codes (0/5/6/7/8/64) onto the dataclass.
- [ ] 2.4 Wire `MacosBackend.associate(...)` in `src/diting/macos_backend.py` to call `_helper.associate(...)`. Return `AssociateResult(ok=False, error_code="unknown", error_message="helper not installed")` when `_helper_path` is None.
- [ ] 2.5 Unit-test `_helper.associate`'s parser with synthetic stdout / exit-code pairs for every documented outcome (`tests/test_helper_associate.py`).

## 3. Helper — Swift side

- [ ] 3.1 In `helper/Sources/diting-tianer/main.swift`, add an `associate` case to the top-level `switch args[1]` block (around `helper/Sources/diting-tianer/main.swift:1545`).
- [ ] 3.2 Write a flag parser that accepts `--ssid <SSID>` (required) and `--bssid <BSSID>` (optional). Reject `--password` with exit 64 (security guard from the spec).
- [ ] 3.3 Read stdin once (`FileHandle.standardInput.readDataToEndOfFile`), trim trailing `\n`, treat empty as "no caller-supplied password".
- [ ] 3.4 Build an `AssociateWorker: NSObject, CLLocationManagerDelegate` (modelled on `ScanWorker`) that registers with CoreLocation, then performs a CoreWLAN scan to locate the `CWNetwork` for the SSID. On miss → exit 8 (`ssid_not_found`).
- [ ] 3.5 Enterprise detection: if the resolved `CWNetwork` reports only Enterprise security variants, emit `{"schema": 1, "error": "<localized>", "code": "enterprise_unsupported"}` on stdout and exit 5. No sheet, no associate call.
- [ ] 3.6 Saved-credential fast path: call `CWInterface.associate(toNetwork:password:nil error:)`. On success → emit `{"schema": 1, "ok": true, "bssid": ..., "keychain_saved": false}` and exit 0. On failure with "password required" / authentication-error code AND stdin was empty → fall through to 3.7. On any other failure → emit `auth_failed` and exit 7.
- [ ] 3.7 AppKit sheet: build an `NSPanel` with an `NSImageView` (helper bundle icon), an `NSTextField` prompt, an `NSSecureTextField`, a "Remember this network" `NSButton` checkbox (default ON), Join + Cancel buttons. `NSApp.activate(ignoringOtherApps: true)` then `panel.makeKeyAndOrderFront(nil)`. Bind Enter to Join, Esc to Cancel.
- [ ] 3.8 Sheet → Join: call `CWInterface.associate(toNetwork:password:<typed> error:)`. On success and checkbox ON → call `+[CWKeychain setWiFiPassword:forSSID:]` and set `keychain_saved` to `true` (catch `nil`/throw and report `keychain_saved: false`, still exit 0). On success and checkbox OFF → `keychain_saved: false`, exit 0. On failure → emit `auth_failed`, exit 7.
- [ ] 3.9 Sheet → Cancel: emit `{"schema": 1, "error": "user cancelled", "code": "cancelled"}` on stdout and exit 6. No association attempted.
- [ ] 3.10 Caller-supplied password path: when stdin contained a non-empty password, use it directly in the `associate(...)` call from 3.6 (skip the `nil` attempt). On success → exit 0; on failure → exit 7. The AppKit sheet is NOT shown on this path.
- [ ] 3.11 Wipe the password `String` buffer (overwrite with zeros via `withUnsafeMutableBytes` on a backing `Data`) before subprocess exit, on every code path.
- [ ] 3.12 Update `--help` text in `main.swift` to document the `associate` subcommand and its exit codes.
- [ ] 3.13 Build the helper bundle locally and confirm `./diting-tianer.app/Contents/MacOS/diting-tianer associate --help` prints the new section.

## 4. TUI — confirmation modal + join action

- [ ] 4.1 Add `class JoinConfirmScreen(ModalScreen)` to `src/diting/tui.py`. Compose: title "Switch to <SSID>?", a body that renders the gap-warning line (from 1.2) verbatim so every confirm makes the cost explicit, Join + Cancel buttons with Cancel default-focused. Bindings: `escape,n,q` → cancel, `y` → confirm. Pass the result back via `dismiss(bool)`.
- [ ] 4.2 Add `Binding("j", "wifi_join", t("Join"))` to `WifiDetailScreen.BINDINGS`.
- [ ] 4.3 Implement `WifiDetailScreen.action_wifi_join()` — early-out + Enterprise-hint notify when the inspected `ScanResult` is Enterprise (use existing security-type inspection if present; otherwise add a tiny `_is_enterprise(scan)` helper). Otherwise push `JoinConfirmScreen(ssid=...)` and await its result.
- [ ] 4.4 On confirm, dispatch `Backend.associate(ssid, bssid)` via Textual's worker (`@work` decorator or `self.app.run_worker(...)`) so the helper subprocess does not block the UI thread.
- [ ] 4.5 Translate the `AssociateResult` into a single `self.app.notify(...)` per outcome class, with severity / message per the `wifi-detail-modal` spec's notify requirement.
- [ ] 4.6 Update `WifiDetailScreen._render_footer` (or wherever the footer's `t("Esc / i to close")` is set) to also document `j`. When the inspected row is Enterprise, swap to the Enterprise hint variant.

## 5. TUI — `(joining…)` annotation

- [ ] 5.1 On `DitingApp` (in `src/diting/tui.py`), add `_app_joining_to: tuple[str, datetime] | None = None`. Set it when `action_wifi_join` confirms; deadline = `now + 10s`.
- [ ] 5.2 In `_render_identity` / `_section_identity` of `WifiDetailScreen`, when `_app_joining_to[0] == self._scan.ssid` and the deadline has not passed, append `(joining…)` next to `(associated)` styling.
- [ ] 5.3 Hook into the App's poll-tick path so the moment a new `Connection.bssid` matches the joined SSID, `_app_joining_to` clears.
- [ ] 5.4 On any non-success `AssociateResult`, clear `_app_joining_to` before emitting the notify.
- [ ] 5.5 Add a passive deadline check in the modal's render path so a hung helper (no failure event, no successful poll) still clears the annotation after 10 s.

## 6. Self-test gates (CLAUDE.md hard rule #3)

- [ ] 6.1 `uv run pytest` — must pass; covers new helper-parser tests and the Textual smoke tests for `j` / confirm modal.
- [ ] 6.2 `uv run python scripts/tui_snapshot.py --mode regression` — synthetic fixtures with both Personal and Enterprise rows; capture before/after and make sure no other panel rendering regresses.
- [ ] 6.3 `openspec validate --specs --strict` — passes after archive (skipping this is fine pre-merge; useful as a sanity check on the delta deltas).
- [ ] 6.4 `openspec validate wifi-connect-from-detail --strict` — passes locally before pushing.
- [ ] 6.5 Manual gate on a real Mac (CLAUDE.md `/tui-audit`): join an open network → join a Keychain-saved WPA2 network (no prompt fires) → join a fresh WPA2 network (sheet appears, password is accepted, second attempt skips the sheet) → press `j` on an Enterprise row (refusal notify, no sheet). Documented in the PR description.

## 7. Surface updates (CLAUDE.md hard rule #6)

- [ ] 7.1 Update `README.md` hotkey table — add `j` to the Wi-Fi view section.
- [ ] 7.2 Update `docs/zh/README.md` hotkey table — Chinese parity.
- [ ] 7.3 Update `CHANGELOG.md` with a one-line entry under the unreleased section.

## 8. Final validate + archive prep

- [ ] 8.1 Run `openspec validate wifi-connect-from-detail --strict` one last time; confirm zero warnings.
- [ ] 8.2 Stage commits in logical chunks: helper change, Python backend change, TUI change, docs / i18n. Each commit must keep tests green so a bisect remains useful.
- [ ] 8.3 Push to `claude/wifi-connect-detail-page-wmcN0`. Do NOT open a PR until the user asks for one (per `Claude Code on the Web` operating rules).
