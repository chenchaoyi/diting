## Why

PR #69's `associate` subcommand spec assumed that
`CWInterface.associate(toNetwork:password:nil error:)` would silently
pull the SSID's password out of the System Keychain — that's what
macOS does for Apple's own `WiFiAgent` because Apple's process has
the `com.apple.wifi.system-services` entitlement and is on the ACL
of every AirPort Keychain item. diting's ad-hoc-signed helper bundle
has neither, so on real hardware the `password: nil` call fails for
any secured SSID and the user sees our password sheet **every time**
they re-join — defeating the whole "saved password = silent join"
promise.

PRs #72 / #73 / #74 tried to recover the silent path by reading the
System Keychain ourselves via private `CWKeychain` selectors; PR #75
switched to public `Security.framework` `SecItemCopyMatching` against
`kSecAttrService = "AirPort"`. Both paths reach the same wall: the
System keychain's `system.keychain.modify` Authorization right uses
the `authenticate-admin-nonshared` rule, which forces a fresh admin
password every call and **does not accept Touch ID**, regardless of
the calling app's capabilities. The dialog the user sees is the system
admin-credential prompt, not "Always Allow". Unusable.

The right design is to **stop trying to read Apple-owned AirPort
items** and instead persist diting's own copy in the user's **login
keychain** under our own service namespace, with a
`SecAccessControlCreateWithFlags(..., .userPresence, ...)` ACL. macOS
unlocks `.userPresence` items with Touch ID on capable hardware (and
falls back to the login password — not the admin password — when
biometric is unavailable). First join of a secured SSID still goes
through our `NSPanel` sheet, but every subsequent join becomes a
single Touch ID tap.

## What Changes

### `macos-helper` — Wi-Fi password persistence moves to login keychain with biometric ACL

- **BREAKING (behaviour, not transport):** the saved-credential path no longer
  relies on `CWInterface.associate(toNetwork:password:nil)` "just working"
  via macOS auto-Keychain. The helper SHALL explicitly fetch the
  password from its own login-keychain entry via `SecItemCopyMatching`
  and pass it to `associate(toNetwork:password:error:)`. The
  legacy `password: nil` fast path is retained only for **open
  networks**.
- Read path: `SecItemCopyMatching` with
  `kSecClass = kSecClassGenericPassword`,
  `kSecAttrService = "com.chenchaoyi.diting.tianer"`,
  `kSecAttrAccount = <SSID>`. The helper SHALL NOT query
  `kSecAttrService = "AirPort"` (System keychain, requires admin
  every call — confirmed unusable). Read failures fold to
  "no saved password" and fall through to the sheet.
- Write path: `SecItemAdd` to the same service namespace with
  `kSecAttrAccessControl` =
  `SecAccessControlCreateWithFlags(nil,
  kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, nil)`.
  On `errSecDuplicateItem` the helper SHALL call `SecItemUpdate`
  with the same query, preserving the ACL from the original add so
  password rotations don't re-prompt Touch ID for ACL setup.
- Read calls SHALL pass `kSecUseOperationPrompt` with a localized
  string explaining context (EN: `diting wants to join Wi-Fi
  "<SSID>"`; ZH: `diting 想要连接 Wi-Fi "<SSID>"`). The OS renders
  this in the Touch ID / login-password dialog so the user sees
  why authentication is being requested.
- Existing Keychain-write failure tolerance is retained: if
  `SecItemAdd`/`Update` fails, the associate itself still succeeds
  and the response carries `keychain_saved: false`.
- The `keychain_read` diagnostic field added in PR #74 / #75 is
  retained for debugging but its value space changes:
  `"diting"` (cached read succeeded), `"miss"` (no cache),
  `"denied"` (user cancelled the Touch ID prompt or biometric failed
  and the user dismissed the passcode fallback).

### `wifi-detail-modal` — confirmation modal text gains a Touch ID hint (no spec change)

- The Wi-Fi-side `JoinConfirmScreen` body will mention that previously-saved
  SSIDs may prompt for Touch ID. This is information density inside an existing
  i18n string; no new requirement, no new binding, no new dispatched call.
  Tracked as an implementation task, not a spec delta.

### Test plan additions (`tests/TESTING.md`, EN + ZH)

- Manual: first `j` on a new secured SSID → sheet → user submits
  password → Touch ID gesture confirms write to login keychain.
- Manual: second `j` on the same SSID (no rebuild) → Touch ID prompt
  → silent associate succeeds.
- Manual: cancel Touch ID prompt → helper exits with the existing
  `cancelled` code; Python falls back to sheet.
- Manual: stale cached password (user rotated the AP key elsewhere)
  → associate fails with `auth_failed` → sheet pops → new password
  via `SecItemUpdate` overwrites the stale value in place.
- Manual on a non-Touch-ID Mac: `.userPresence` falls back to the
  login password prompt (NOT admin password). Same data path.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `macos-helper`: the `associate` subcommand's Keychain interaction
  requirements change — replace the "macOS auto-reads from System
  Keychain via `password: nil`" model with explicit `SecItem*` reads
  / writes against a diting-owned service namespace in the login
  keychain, plus a `.userPresence` access-control flag. Public-API
  exit codes and response shape are unchanged.

## Impact

- `helper/Sources/diting-tianer/main.swift`:
  - `attemptKeychainRead(ssid:)` — drop the `"AirPort"` service
    probe (left over from PR #75 — fold to no-op); keep the
    `"com.chenchaoyi.diting.tianer"` service probe; add
    `kSecUseOperationPrompt`.
  - `attemptKeychainWrite(ssid:password:)` — build a
    `SecAccessControlCreateWithFlags(...userPresence...)` and pass
    it as `kSecAttrAccessControl` on the add path. `SecItemUpdate`
    path is untouched (ACL inherits from the original add).
  - The associate worker SHALL read the cached password before the
    `associate(toNetwork:password:error:)` call (today the code
    relies on `password: nil`); pass the read result through to
    CoreWLAN.
- `src/diting/_helper.py`: no surface change — same JSON contract
  (`ok`, `bssid`, `keychain_saved`, `keychain_read`).
- `src/diting/i18n.py`: new EN keys `keychain.touchid.prompt.ssid`
  (used by helper via `LANG` environment hand-off) + ZH translation.
  Note: the helper has its own narrow i18n surface for OS-rendered
  dialogs; the existing Location / Bluetooth permission strings are
  the template.
- `tests/`: unit-level — the helper JSON parser in
  `test_helper_associate.py` already tolerates unknown
  `keychain_read` values; add a regression assertion for the new
  `"denied"` value. No new Swift-side unit tests (the SecItem path
  needs a real Keychain).
- `tests/TESTING.md` (EN + ZH) — append the manual steps from the
  test plan above as a new "wifi-keychain-touch-id" sub-section
  inside the macos-helper test plan.
- `README.md` / `docs/zh/README.md`: the `j` hotkey row note
  ("已存 Keychain 的网络无感加入") becomes "Touch ID 后无感加入" /
  "Touch ID after a tap" once this lands — small wording edit, EN +
  ZH together.
- Helper schema: no field added or renamed. `keychain_read` gains
  a new accepted string value (`"denied"`) but its type and
  presence are unchanged — no schema bump.
- Privacy / security:
  - Read prompts surface the localized SSID; the SSID is already
    user-visible elsewhere, so this is not a new disclosure.
  - The login-keychain store is per-user, encrypted at rest, and
    not iCloud-synced (we never set `kSecAttrSynchronizable`).
  - The cached password is held in a local `String` for the
    duration of the associate call and is not logged or echoed —
    same posture as PR #69.
- Out of scope:
  - Reading macOS-owned `AirPort/<SSID>` System keychain entries
    (confirmed unusable for non-Apple processes).
  - Per-BSSID password caching (on roadmap, see PR #76).
  - Touch ID for Enterprise / 802.1X (still rejected upstream per
    PR #69; this change does not relax that).
  - Migration of any items previously written by PRs #72-75 (which
    landed without `.userPresence`): those entries will continue
    to read silently (no Touch ID prompt) until naturally
    overwritten on the next `auth_failed → re-enter → SecItemUpdate`
    cycle. Acceptable — no user-visible regression, just a
    one-time gradual upgrade.
