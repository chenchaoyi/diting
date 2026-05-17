## 1. Helper — Keychain read path

- [ ] 1.1 In `helper/Sources/diting-tianer/main.swift`, remove the `"AirPort"` service probe from `attemptKeychainRead(ssid:)`. Leave only the `"com.chenchaoyi.diting.tianer"` service read.
- [ ] 1.2 Add a `prompt: String` parameter to `readSecGenericPassword(...)`; pass it through as `kSecUseOperationPrompt` in the query dict.
- [ ] 1.3 Caller (`attemptKeychainRead`) builds the prompt from a locale dispatch — read `LANG` / `LC_ALL` env, pick EN/ZH string, interpolate the SSID.
- [ ] 1.4 Map `SecItemCopyMatching` status values to the new `keychain_read` variant strings: `"diting"` on success, `"miss"` on `errSecItemNotFound`, `"denied"` on `errSecUserCanceled`, `"err:<status>"` on anything else.
- [ ] 1.5 Wire the cached read into the associate worker BEFORE the `associate(toNetwork:password:nil)` call — on hit, pass the password explicitly to `associate(toNetwork:password:<recovered>)`. Open networks continue to use `password: nil`.

## 2. Helper — Keychain write path

- [ ] 2.1 In `attemptKeychainWrite(ssid:password:)`, replace the `SecItemAdd` query's untouched attrs with a `kSecAttrAccessControl` built via `SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, &error)`. Bail to `keychain_saved: false` on access-control creation failure (don't abort the associate).
- [ ] 2.2 Confirm the `SecItemUpdate` fallback on `errSecDuplicateItem` writes ONLY `kSecValueData` in its update attrs (so the original ACL is preserved). Add a code comment explaining why — easy to "fix" later by passing the full attr dict and break ACL preservation.
- [ ] 2.3 Verify nothing else in the file references `"AirPort"` service. Remove the constant if it became dead.

## 3. Helper — build verification

- [ ] 3.1 `make helper` — confirm Swift compiles cleanly with the new `Security.framework` calls (no new imports needed, `import Security` is already in main.swift).
- [ ] 3.2 Run the helper directly: `helper/diting-tianer.app/Contents/MacOS/diting-tianer associate --ssid <test-SSID>` on a real Mac. Verify:
  - First-time SSID: sheet appears, type password, Touch ID prompt confirms the write
  - Second invocation: Touch ID prompts, silent associate
  - Cancel Touch ID: falls through to sheet (`keychain_read: "denied"` in response JSON)
- [ ] 3.3 Inspect the keychain entry in Keychain Access.app — confirm `com.chenchaoyi.diting.tianer` / `<SSID>` exists in the login keychain, and Access Control tab shows "Ask for Touch ID or login password" (or similar — exact wording is macOS-version-dependent).

## 4. Test plan documentation

- [ ] 4.1 `tests/TESTING.md` (EN) — add a "wifi-keychain-touch-id" sub-section under the macos-helper test plan with the five manual checks from the proposal's test plan additions.
- [ ] 4.2 `docs/zh/TESTING.md` — mirror the EN entries verbatim translated.

## 5. Python-side parser (no surface change, defensive only)

- [ ] 5.1 `tests/test_helper_associate.py` — add a regression assertion that `keychain_read: "denied"` parses without error (existing parser ignores unknown variant strings, but lock the behaviour with an explicit test).

## 6. User-visible doc updates

- [ ] 6.1 `README.md` — update the `j` hotkey row in the keybindings table: replace "previously-saved networks silent, others prompt for password" wording with "previously-saved networks confirm via Touch ID, others prompt for password".
- [ ] 6.2 `docs/zh/README.md` — mirror with ZH equivalent.

## 7. CI gates

- [ ] 7.1 `uv run pytest` — full unit + smoke suite passes.
- [ ] 7.2 `uv run python scripts/tui_snapshot.py --mode regression` — synthetic regression unchanged.
- [ ] 7.3 `openspec validate --specs --strict` — canonical specs validate.
- [ ] 7.4 `openspec validate wifi-keychain-touch-id --strict` — this change validates.

## 8. Archive

- [ ] 8.1 After merge, run `/opsx:archive wifi-keychain-touch-id` (or `openspec archive wifi-keychain-touch-id`) to fold the delta into `openspec/specs/macos-helper/spec.md` canonically.
