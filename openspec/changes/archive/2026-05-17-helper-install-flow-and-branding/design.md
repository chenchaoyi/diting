## Context

The current install-time helper flow:

```
install.sh
  ├─ extract tarball
  ├─ copy diting-tianer.app to ~/Library/Application Support/diting/
  ├─ xattr -dr com.apple.quarantine
  └─ open <bundle>                ← no env, no args
       └─ helper process launches
            ├─ NSWindow (status panel)
            ├─ CLLocationManager.requestWhenInUseAuthorization()   ← fires immediately
            └─ CBCentralManager()                                  ← fires immediately
                 → macOS shows two prompts on top of the window
```

Two structural problems:
1. **Locale signal disagrees.** The status window picks language
   via `Locale.preferredLanguages.first`; macOS picks the TCC
   prompt header via `Bundle.preferredLocalizations` against the
   user's preferred-languages list intersected with the bundle's
   `CFBundleLocalizations`. Under LaunchServices these can return
   different first entries (the screenshot is proof: status window
   in EN, Location prompt in ZH). No good source of truth.
2. **Two prompts race.** `requestWhenInUseAuthorization` and the
   `CBCentralManager` init fire in parallel. macOS shows them
   simultaneously, the user gets a stack of windows in confused
   order.

Separately, the watchdog's notification path:

```
Python TUI (_watchdog.py)
  └─ subprocess: /usr/bin/osascript -e 'display notification "X" with title "Y"'
       → macOS shows notification with osascript's icon (the scroll)
```

There's no way for Python alone to supply an icon — the calling
process must be a bundle. The helper IS one, so route through it.

## Goals / Non-Goals

**Goals:**
- One ordered permission flow at install: Location → Bluetooth →
  Notifications. Status window is the only persistent window;
  each macOS prompt comes up one at a time on top of it.
- Helper UI language and macOS TCC prompt language agree, and
  both follow the diting startup locale (Python `--lang` >
  `DITING_LANG` env > macOS user preference).
- Watchdog notifications carry the diting logo (the helper
  bundle's icon) instead of the AppleScript scroll.
- No new external build dependencies (`iconutil` ships with
  macOS; PNG sources are committed).

**Non-Goals:**
- Renaming the on-disk bundle filename to fix the Bluetooth-prompt
  "diting-tianer.app" header. That's a separate, larger change.
- Replacing the helper status window with a proper Cocoa wizard
  (e.g. progress dots, buttons). The current `NSTextField` body
  is enough once it updates live and serialises the prompts.
- Replacing `osascript`-based notifications with a launch-agent
  daemon. The one-shot `diting-tianer notify` invocation is fine
  for the watchdog's frequency.
- Code signing / notarization. Bundle remains ad-hoc-signed.

## Decisions

### D1 — Locale source: `DITING_LANG` env at runtime, macOS preference at install

Three locale signals:

| Signal | Source | When it applies |
|---|---|---|
| Python CLI `--lang` flag | user typed `diting --lang zh` | runtime; passed through to helper as DITING_LANG |
| Diting global default | env DITING_LANG / LC_* / LANG (resolved by `i18n.detect_default_lang`) | runtime; what `cli.py` reads |
| macOS user preference | `defaults read -g AppleLanguages` | install time, before any `diting` invocation |

`install.sh` reads macOS preference because it has no other
source — the user hasn't run `diting` yet. At runtime, the
existing `cli.py:907` env-passing of `DITING_LANG` continues to
work.

The helper's `detectHelperLang()` keeps `DITING_LANG` first
priority. Fallback changes from `Locale.preferredLanguages.first`
to `Bundle.main.preferredLocalizations.first`. Rationale: that
function is what macOS itself uses to pick `.lproj`, so the
helper's status window aligns with the prompt header even when
no env is set.

### D2 — Force the macOS TCC prompt locale via `-AppleLanguages` launch arg

Cocoa apps honour `-AppleLanguages '(<tag>)'` as a command-line
flag that overrides the per-bundle language preference inside
NSUserDefaults *for that process*. macOS then picks the matching
`.lproj` for everything including TCC prompts.

We pass it in two places:
- `install.sh`: `open --env DITING_LANG=zh --args -AppleLanguages '(zh-Hans)' <bundle>`
- `src/diting/cli.py` (the helper auto-prime path at line ~905):
  same pattern, with the language tag derived from `i18n.get_lang()`.

For runtime subprocess calls (`diting-tianer wifi-scan`,
`diting-tianer ble-scan`, etc.), the locale isn't user-facing
so we don't need `-AppleLanguages` there. We do still pass
`DITING_LANG` for consistency (already happens via the existing
`subprocess` env inheritance).

### D3 — Sequenced TCC prompts via a state machine in `HelperAppDelegate`

The current delegate fires both Location and Bluetooth in
`applicationDidFinishLaunching`. New behaviour: a small state
machine with explicit "current step" state.

```
enum InstallStep {
    case requestingLocation
    case requestingBluetooth
    case requestingNotifications
    case allDone
}
```

Transitions:
- `applicationDidFinishLaunching` → `requestingLocation`,
  call `locationManager.requestWhenInUseAuthorization()`.
- `locationManager(_:didChangeAuthorization:)` callback
  with a non-`.notDetermined` status → advance to
  `requestingBluetooth`, instantiate `CBCentralManager` (which
  fires its own prompt during `centralManagerDidUpdateState`).
- `centralManagerDidUpdateState` callback with a non-`.unknown`
  state → advance to `requestingNotifications`, call
  `UNUserNotificationCenter.current().requestAuthorization(options:[.alert,.sound])`.
- Notifications callback completes → `allDone`, schedule
  auto-close after 4 s.

The status window's `statusLabel` rewrites on every transition,
showing all three lines plus an arrow indicating which one is
currently waiting on user input.

Failure modes (deny / restricted / unsupported) advance the state
machine the same way — we don't block on a denied permission. The
status window shows the denied state with a "Open System Settings"
hint, then proceeds.

### D4 — Icon pipeline: committed PNGs + macOS `iconutil`

`docs/design/diting-design/assets/logo-mark.svg` is the source of
truth. One-time, we rasterise it into the macOS standard sizes
(16, 32, 64, 128, 256, 512, 1024 px at 1x; 32, 64, 128, 256, 512,
1024 px at 2x — Apple's `.iconset` convention) and commit them at
`helper/Resources/AppIcon.iconset/icon_<size>x<size><@2x>.png`.

`helper/build.sh` adds one step:
```bash
iconutil --convert icns \
    Resources/AppIcon.iconset \
    --output "$BUNDLE/Contents/Resources/AppIcon.icns"
```

Why not generate the PNGs at build time:
- librsvg / Inkscape are not on macOS by default. Adding
  `brew install librsvg` to every contributor's setup is
  hostile to drive-by PRs.
- `qlmanage` / `sips` SVG rasterisation is brittle on
  pixel-art (anti-aliasing chooses non-pixel-aligned
  boundaries).
- The logo doesn't change. Re-rasterise only when it does;
  contributors don't need the toolchain.

### D5 — `notify` subcommand uses `UNUserNotificationCenter`

The Swift helper gains:

```swift
case "notify":
    let title = parseFlag("--title", argv) ?? ""
    let body  = parseFlag("--body",  argv) ?? ""
    runNotifyAndExit(title: title, body: body)
```

Implementation:
1. Configure `UNUserNotificationCenter.current().delegate = self`.
2. `requestAuthorization(options: [.alert, .sound])` — if
   authorization was already granted at install time this is a
   cheap no-op; if not, the user sees the system prompt now
   (matches our lazy-fallback design).
3. Build `UNMutableNotificationContent(title:, body:)` and add it
   to the center with `UNNotificationRequest(identifier:
   UUID().uuidString, content:, trigger: nil)` (immediate trigger).
4. Wait up to 1 s on a dispatch group so the notification actually
   surfaces before the process exits (notifications submitted by a
   process that exits too fast can drop on the floor).
5. `exit(0)` regardless of delivery state — best-effort.

`UNUserNotificationCenter` requires the process to be a properly-
identified bundle (CFBundleIdentifier). Our helper is. No
LaunchServices outer/inner gymnastics needed: notifications
work fine from a direct-exec subprocess of the bundle's binary
(unlike the macOS 26 Location TCC issue).

### D6 — Watchdog routes through the helper, falls back silently

`src/diting/_watchdog.py:_macos_notify` becomes:

```python
async def _macos_notify(*, title: str, message: str) -> None:
    helper = resolve_helper_binary()  # already exists in macos_helper.py
    if helper is None:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            str(helper), "notify",
            "--title", title, "--body", message,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except (FileNotFoundError, OSError, asyncio.TimeoutError):
        # Best-effort: a failure here must not propagate into the TUI.
        pass
```

No fallback to osascript. The osascript path's scroll icon was
the very thing we're removing; bringing it back as a fallback
re-introduces the visual inconsistency. If the helper isn't
installed, notifications silently fail (which is the same
contract we have today on broken installs).

## Risks / Trade-offs

- **[Risk]** Adding `CFBundleIconFile` + `AppIcon.icns` changes
  the bundle's cdhash. Existing users re-grant Location and
  Bluetooth on the next install. → Acceptable; we surface it in
  the release notes and in the install.sh on-screen text. macOS
  does keep the prior grants until the cdhash actually changes,
  so the v1.0.8 install will fire grants once, future v1.0.x
  installs at the same bundle path won't.
- **[Risk]** `UNUserNotificationCenter.requestAuthorization`
  permission can be revoked by the user in System Settings,
  silently breaking watchdog alerts. → No telemetry path to
  detect this from inside the TUI; user-facing docs note that
  notifications can be re-enabled in System Settings.
- **[Risk]** The sequenced flow lengthens the install path —
  the user now sees three prompts instead of two, in order.
  → The proposal makes this explicit; the alternative
  (parallel prompts) was the source of the complaint.
- **[Risk]** `defaults read -g AppleLanguages` returns an
  array; parsing it in bash is awkward. → Use `defaults read
  -g AppleLanguages 2>/dev/null | head -1` and grep for `zh`;
  fail open to `en`. Acceptable for an install-time signal.
- **[Risk]** Forcing `-AppleLanguages` via `--args` overrides
  the user's per-bundle language preference if they set one
  in System Settings → Language & Region → Apps. → Users who
  intentionally pin the bundle to a specific locale would lose
  that pinning. We document this and accept it: the diting
  startup locale is the explicit signal, the per-app
  preference is implicit.

## Migration Plan

Single-PR migration. install.sh and helper bundle are versioned
together (both ship in the same tarball), so there's no
mid-migration state. Existing installs will re-prompt for
Location + Bluetooth on next install due to cdhash change; this
is documented in the release notes.

Rollback: `git revert` the PR. The cdhash invalidation isn't
reversible from the user's side without a fresh install, but the
flow itself goes back to the pre-PR state.
