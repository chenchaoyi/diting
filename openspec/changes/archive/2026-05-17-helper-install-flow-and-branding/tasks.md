## 1. Icon assets

- [x] 1.1 Rasterise `docs/design/diting-design/assets/logo-mark.svg` to seven sizes (16, 32, 64, 128, 256, 512, 1024 px at 1x; plus 2x variants where Apple's `.iconset` convention requires). Commit PNGs to `helper/Resources/AppIcon.iconset/icon_*.png`.
- [x] 1.2 Add the `iconutil --convert icns` step to `helper/build.sh` that produces `Contents/Resources/AppIcon.icns` from the iconset.
- [x] 1.3 Add `<key>CFBundleIconFile</key><string>AppIcon</string>` to `helper/Info.plist`.

## 2. Helper Swift changes

- [x] 2.1 In `helper/Sources/diting-tianer/main.swift`, change `detectHelperLang`'s second fallback from `Locale.preferredLanguages.first` to `Bundle.main.preferredLocalizations.first` (still prefer `DITING_LANG` env first). Update the leading comment.
- [x] 2.2 Rework `HelperAppDelegate` into a sequenced state machine: enum `InstallStep { requestingLocation, requestingBluetooth, requestingNotifications, allDone }`. Start at `requestingLocation`; advance on each TCC callback resolving to a non-`.notDetermined` state. Update `statusLabel.stringValue` on every transition with three lines (one per permission) prefixed by `1/3` / `2/3` / `3/3` and showing waiting / granted / denied state.
- [x] 2.3 Add the `requestingNotifications` step using `UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])`. Tolerate the auth result (no abort on denial). Schedule auto-close 4 s after the third step settles.
- [x] 2.4 Add a `notify` subcommand at the top-level argv switch (alongside `wifi-scan`, `ble-scan`, `bluetooth-status`, `scan`). Implementation: parse `--title <T>` and `--body <B>` flags; call `UNUserNotificationCenter.current().requestAuthorization` (no-op when already granted); build a `UNMutableNotificationContent` and add it as a `UNNotificationRequest` with `trigger: nil`; wait on a `DispatchGroup` for up to 1 s for the add completion; exit 0.
- [x] 2.5 Verify that adding the icon + new subcommand does not affect the existing macOS-26 LaunchServices outer/inner split for `scan`. Re-read the scan path's leading comment and confirm no overlap.

## 3. install.sh changes

- [x] 3.1 Add a `detect_locale()` shell helper that reads `defaults read -g AppleLanguages 2>/dev/null`, takes the first array entry, and echoes `zh` if it starts with `zh` else `en`. Fail open to `en` when `defaults` errors or returns empty.
- [x] 3.2 Change the bundle-prime invocation (currently `open "$DST_BUNDLE" 2>/dev/null || true`) to pass `--env DITING_LANG=<lang>` and `--args -AppleLanguages '(<tag>)'` where `<tag>` is `zh-Hans` when `<lang>=zh` else `en`. Keep the foreground (no `-g`) launch.
- [x] 3.3 Update the on-screen install-time copy (`note "..."`) to mention three prompts instead of two, and to call out the cdhash-change re-grant for upgrading users.

## 4. cli.py runtime locale parity

- [x] 4.1 In `src/diting/cli.py` around line 905 (the helper auto-prime path), add the same `--args -AppleLanguages '(<tag>)'` to the `open_argv` list so the runtime helper launch agrees with install.sh.

## 5. Watchdog routing

- [x] 5.1 In `src/diting/_watchdog.py`, replace `_macos_notify`'s `osascript` subprocess with a call to `<helper-bin> notify --title <title> --body <message>`. Resolve the helper path via the existing `macos_helper.resolve_helper_binary()`. If the helper is unavailable, return without error (silent skip per spec).
- [x] 5.2 Add a 3-second wall-clock timeout via `asyncio.wait_for(proc.wait(), timeout=3.0)`. Catch and swallow `FileNotFoundError`, `OSError`, `asyncio.TimeoutError`.

## 6. Tests

- [x] 6.1 Update `tests/test_watchdog.py` (or wherever `_macos_notify` is exercised): switch the asserted subprocess invocation from osascript to the helper `notify` path. Cover the "helper unavailable → silent skip" path with a mocked `resolve_helper_binary` returning `None`.
- [x] 6.2 Add a unit test that asserts `helper/Resources/AppIcon.iconset/` contains the standard size set and `helper/Info.plist` declares `CFBundleIconFile=AppIcon` (a shell + grep test under `tests/install/` or a Python test under `tests/`).
- [x] 6.3 Add an install.sh test (TESTONLY mode that already gates the open call) that confirms the new `--env DITING_LANG=` and `--args -AppleLanguages` flags are present in the would-run command.

## 7. Docs

- [x] 7.1 Update `README.md` and `docs/zh/README.md`: mention the three permissions, the icon, and that notifications now carry the diting logo.
- [x] 7.2 Update `docs/RELEASE.md` and `docs/zh/RELEASE.md`: add a release-note bullet about the cdhash change forcing a one-time re-grant for upgrading users.
- [x] 7.3 Update `tests/TESTING.md` + `docs/zh/TESTING.md` rows for `installation`, `macos-helper`, `anomaly-watchdog` capabilities to reference the new tests.
- [x] 7.4 Update `CHANGELOG.md` and `docs/zh/CHANGELOG.md` with a v1.0.x entry describing the install-flow + branding pass.

## 8. Gates

- [x] 8.1 `uv run pytest` — all existing tests + new tests pass.
- [x] 8.2 `uv run python scripts/tui_snapshot.py --mode regression` — regression snapshot passes.
- [x] 8.3 `openspec validate --specs --strict` — all canonical specs validate.
- [x] 8.4 `openspec validate helper-install-flow-and-branding --strict` — proposal validates.
- [x] 8.5 Local manual: run `helper/build.sh`, inspect the bundle's `Contents/Resources/AppIcon.icns` exists and renders in Finder; run `diting-tianer notify --title test --body hi` and confirm a notification appears with the diting logo.
