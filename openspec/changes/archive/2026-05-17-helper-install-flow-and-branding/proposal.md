## Why

The first thing a curl-bash user sees after install is three windows
stacked at once — the helper's status window in one language, a
macOS Location prompt with the Chinese display name "谛听 · 天耳", and
a Bluetooth prompt that just says "diting-tianer.app" (the raw
bundle filename, because macOS reads the Bluetooth prompt header from
the on-disk filename, not `CFBundleDisplayName`). Three different
names, mixed languages, no order. Users report 摸不着头绪.

Separately, the notifications the anomaly watchdog fires today carry
the AppleScript scroll icon — `_watchdog.py` shells out to
`/usr/bin/osascript -e 'display notification ...'`, so macOS attaches
osascript's icon. There's no way to override the icon while the
Python TUI is the sender, since it isn't a bundle.

The helper bundle is the only diting component that is a real `.app`,
holds TCC grants, and has an identity macOS can hang an icon on.
Re-routing things through it solves both problems together.

## What Changes

### Locale follow-through (install + runtime)

- `install.sh` reads the macOS user-preferred language via
  `defaults read -g AppleLanguages`, derives `DITING_LANG=en|zh`, and
  passes it to the helper at first launch:
  `open --env DITING_LANG=... --args -AppleLanguages '(<tag>)' <bundle>`.
- The `-AppleLanguages` arg forces Cocoa's `NSUserDefaults` to pick
  the matching `.lproj` for *this process* — so the Location TCC
  prompt header, the prompt bodies, and the helper's own status
  window all use the same locale. (Today `Locale.preferredLanguages`
  and `Bundle.preferredLocalizations` can disagree under LaunchServices,
  which is what produced the English/Chinese mix in the screenshot.)
- Helper's `detectHelperLang()` keeps `DITING_LANG` as the
  authoritative source. The fallback switches from
  `Locale.preferredLanguages.first` to `Bundle.main.preferredLocalizations.first`
  so absent-env runs still agree with macOS's lproj choice.
- **BREAKING (UX)**: the helper UI language now follows the diting
  startup locale (Python `--lang` flag / `DITING_LANG` env / macOS
  preference, in that order). Users on an English-language Mac who
  run `diting --lang zh` will see the helper in Chinese on its next
  launch.

### Sequenced permission flow

- The helper's install-time run requests permissions in a fixed
  order: Location → Bluetooth → Notifications. Each next request
  fires only after the previous one's auth callback resolves
  (either Allow or Don't Allow). Users see one macOS prompt at a
  time on top of the status window, not a stack.
- The status window text becomes a live wizard: shows
  `1/3 Location` / `2/3 Bluetooth` / `3/3 Notifications` lines that
  update as each grant lands. Auto-closes ~4 s after the third grant.
- **BREAKING (helper)**: the helper now requests *three* TCC
  permissions instead of two. A first-time install adds one extra
  click. Users upgrading from v1.0.x land in the same flow on next
  install but only see the new (Notifications) prompt.

### diting logo on the helper bundle

- Pre-rendered PNGs at 16/32/64/128/256/512/1024 px land under
  `helper/Resources/AppIcon.iconset/` (committed to the repo —
  rasterised from `docs/design/diting-design/assets/logo-mark.svg`
  once, no build-time SVG dependency).
- `helper/build.sh` runs `iconutil --convert icns` (built into
  macOS) to produce `AppIcon.icns` inside the bundle.
- `helper/Info.plist` gets `CFBundleIconFile=AppIcon`.

### Helper-sent notifications

- New helper subcommand `diting-tianer notify --title T --body B`
  uses `UNUserNotificationCenter` to post the notification. Because
  the sender is the helper bundle, macOS attaches the bundle's
  icon (now the diting logo) instead of the AppleScript scroll.
- Notification authorisation is requested up-front during the
  install-time helper run (the new third prompt). Lazy fallback:
  if `notify` is invoked without authorisation, the helper
  silently drops the notification (the watchdog tolerates
  best-effort delivery today).
- `src/diting/_watchdog.py` swaps the `/usr/bin/osascript` invocation
  for `<helper-bin> notify --title ... --body ...`. The helper-path
  resolution that already exists in `src/diting/macos_helper.py`
  is reused.

## Capabilities

### New Capabilities
<!-- none — every spec already exists -->

### Modified Capabilities
- `installation`: install.sh derives locale from macOS preference
  and threads it into the helper launch; defines that install
  must produce one ordered prompt flow rather than the prior
  parallel one.
- `macos-helper`: the helper bundle ships an icon, runs a
  sequenced three-permission flow at install time, exposes a
  `notify` subcommand, and trusts `Bundle.preferredLocalizations`
  over `Locale.preferredLanguages` for the language fallback.
- `anomaly-watchdog`: the macOS notification path is now via the
  helper, not osascript. Authorization is the helper's job; the
  watchdog only specifies the message.

## Impact

- `install.sh`: locale detection + new `open --args -AppleLanguages` + DITING_LANG env passing.
- `helper/Info.plist`: `CFBundleIconFile=AppIcon`.
- `helper/build.sh`: `iconutil --convert icns Resources/AppIcon.iconset -o diting-tianer.app/Contents/Resources/AppIcon.icns`.
- `helper/Resources/AppIcon.iconset/icon_*.png`: new asset files (7 sizes × {1x,2x} where applicable).
- `helper/Sources/diting-tianer/main.swift`: new `notify` subcommand; `HelperAppDelegate` reworked so Location/BT/Notifications are requested in sequence with status-window updates; `detectHelperLang` falls back to `Bundle.main.preferredLocalizations.first`; new `NSUsageDescription` keys if `UNUserNotificationCenter.requestAuthorization` needs one (verify; usually not).
- `src/diting/_watchdog.py`: replace `_macos_notify` body with a call to the helper binary; reuse `macos_helper.resolve_helper_binary()`.
- New tests: `test_macos_helper.py` for the `notify` subcommand path; `test_watchdog.py` for the routing change; install.sh's locale-derivation test under `tests/install/` (we already have shell-test scaffolding for install.sh).
- README + docs/zh README: mention the third permission, the icon, and that the helper sends notifications.
- No new Python or Swift deps. No new bundle layout breaking the existing TCC cdhash (CFBundleIconFile addition can change cdhash — need to verify; if it does, users re-grant once).
