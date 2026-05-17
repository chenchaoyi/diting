## Context

### Where we are after PR #75

The `associate` subcommand was specified (PR #69) on the assumption
that `CWInterface.associate(toNetwork:password:nil error:)` would
quietly succeed for any SSID whose password macOS had already saved
— matching what the OS Wi-Fi menu does. Empirically that path only
works for Apple's own processes (`WiFiAgent`, System Settings); a
third-party helper bundle hits an internal authorization gate and the
call fails with a "password required" error every time. PRs #72-#75
walked through escalating remediation:

| PR | Approach | Outcome |
|---|---|---|
| #72 | Add Python-side `keychain_saved` plumbing | Never tripped — helper never reached the success path |
| #73 | Call private `CWKeychain` selectors to read | `class_getClassMethod` returned non-nil but the read returned empty |
| #74 | Try three CWKeychain signatures (data/domain/legacy) | All three returned empty — ACL denies us |
| #75 | Switch to public `SecItemCopyMatching` against `kSecAttrService = "AirPort"` | macOS pops the System keychain admin dialog every time — Touch ID is not even offered |

The wall hit at #75 is structural: macOS's System keychain access for
non-allowlisted apps goes through Authorization Services rule
`authenticate-admin-nonshared`, which is the strictest rule Apple
ships — it disallows credential caching, disallows biometric
substitution, and demands a fresh admin password each invocation. We
cannot lower that bar from inside our app, and lowering it
system-wide (`security authorizationdb write`) is a security
trade-off we won't make for our users.

### What the user wants

User feedback distilled across PRs #69 / #72-75 / #76:

1. First join of a secured SSID: typing the password once into our
   sheet is fine.
2. Subsequent joins: anything that does not require typing the Wi-Fi
   password again. **Touch ID is acceptable.** Admin password every
   time is not.
3. Stale-cache recovery should be self-healing, not a destructive
   reset.
4. No new system-wide configuration the user has to apply on every
   Mac.

## Goals / Non-Goals

**Goals:**

- A secured SSID joined once via diting's sheet rejoins on subsequent
  `j` invocations with a single Touch ID gesture (or login password
  on Macs without a sensor / paired Apple Watch).
- Zero admin-password prompts in the steady-state flow.
- Stale-cache recovery routes back through the sheet and updates the
  existing item in place — no orphaned entries, no Touch ID re-grant.
- No system-wide configuration mutation. No private APIs.

**Non-Goals:**

- Reading macOS's own `AirPort/<SSID>` entries from the System
  keychain. Apple has explicitly closed that door for non-allowlisted
  apps; we accept that.
- Per-BSSID caching. SSID-keyed only for this change; BSSID-pinned
  flow is a separate roadmap entry (PR #76).
- Enterprise / 802.1X join. Still upstream-rejected per PR #69.
- Cross-device sync via iCloud Keychain. Explicit `kSecAttrSynchronizable
  = false` (default).
- Migrating items written by PRs #72-#75. Acceptable because those
  items read silently today; users will re-establish the Touch ID
  ACL only on the next password rotation.

## Decisions

### D1. Storage location: login keychain, diting's own service

`kSecAttrService = "com.chenchaoyi.diting.tianer"`, written via
`SecItemAdd` / `SecItemUpdate` against the default keychain (the
user's login keychain on every macOS workstation install).

**Alternatives considered:**

- **System keychain under `"AirPort"`** — what PR #75 tried. Rejected:
  forces `authenticate-admin-nonshared` admin prompt every read; no
  Touch ID path.
- **System keychain under our own service** — same gate as above.
  Storage location, not service name, is what triggers the admin
  rule. Rejected.
- **JSON file on disk under `~/Library/Application Support/diting/`** —
  feasible (and originally my recommendation). Rejected for this
  iteration because user asked for a Keychain-based solution that
  benefits from biometric protection. We can fall back to this if
  the Touch ID path turns out to have unforeseen UX issues; the
  file-on-disk path is strictly simpler.

### D2. Access control: `.userPresence`, not `.biometryAny` / `.biometryCurrentSet`

`SecAccessControlCreateWithFlags(nil,
kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, nil)`.

`.userPresence` is "Touch ID OR Apple Watch OR device passcode" —
the most permissive of the biometric-gated options. macOS picks the
right modality at runtime based on hardware.

**Alternatives considered:**

- `.biometryAny` — Touch ID only, no passcode fallback. Rejected:
  locks out Macs without Touch ID and breaks the helper if the
  sensor fails (sweat, gloves, sensor failure).
- `.biometryCurrentSet` — invalidates the item when fingerprints
  change. Rejected: users adding a new finger to Touch ID would
  have to re-type the Wi-Fi password the next time, which is
  exactly the friction we're trying to remove.
- No `kSecAttrAccessControl` (just `kSecAttrAccessible`) — what
  PR #75 currently does. Items read silently after the first
  "Always Allow" prompt. Rejected for this change because the
  user specifically asked for biometric protection — and "Always
  Allow" doesn't survive `make helper` rebuilds for contributors
  (cdhash changes), while `.userPresence` does (the ACL is
  user-presence-gated, not cdhash-gated).

### D3. Read flow: explicit `SecItemCopyMatching` before `associate(...)`, not `password: nil`

Today (post-#69) the helper calls `associate(toNetwork:password:nil)`
on the optimistic path and relies on CoreWLAN's lower layers to find
the saved password. That assumption is dead. The helper SHALL:

1. For open networks (`security == .none`): keep `password: nil`. No
   keychain involvement.
2. For secured networks: call `SecItemCopyMatching` against our
   service namespace first. On hit, pass the password explicitly to
   `associate(toNetwork:password:error:)`. On miss, drive the
   existing sheet flow.

**Alternative considered:** keep `password: nil` first, fall back to
`SecItemCopyMatching` on auth failure. Rejected — `associate(password:
nil)` on a secured network without saved creds takes ~3-5 seconds to
fail and the user sees the OS Wi-Fi indicator spin during the wait.
Explicit Keychain-first is faster.

### D4. Prompt text: localized via `kSecUseOperationPrompt`

The Touch ID / login-password dialog rendered by the OS has a
"Reason" string the calling app provides. The helper SHALL set this
to:

- EN: `diting wants to join Wi-Fi "<SSID>"`
- ZH: `diting 想要连接 Wi-Fi "<SSID>"`

The helper picks the locale from the `LANG` / `LC_ALL` env vars (same
as the Python TUI's locale autodetection). The string is the only
helper-rendered text in this flow — every other surface (NSPanel sheet
text, notify body) is rendered by Python.

### D5. Stale cache: existing fall-through path

PR #69's behaviour: cached/typed password fails → helper exits with
`auth_failed` → Python re-invokes the helper, this time piping an
empty stdin → sheet pops → user types → `SecItemAdd` returns
`errSecDuplicateItem` → `SecItemUpdate` rewrites the data in place,
preserving the existing ACL. No code change needed in this change —
the SecItemUpdate path is already correct in PR #75.

**Subtle point:** `SecItemUpdate` does not require re-authenticating
through `.userPresence` (modifying an item is governed by the keychain
unlock state, not by the item's access control flags; ACL gates *read*
access to the password material). So rotation is silent on the write
side.

### D6. Empty / nil result handling

`SecItemCopyMatching` returns:

- `errSecSuccess` + Data → success, decode to UTF-8 String
- `errSecItemNotFound` → no saved password → emit `keychain_read:
  "miss"` and fall through to sheet
- `errSecUserCanceled` → user dismissed Touch ID prompt → emit
  `keychain_read: "denied"` and fall through to sheet. **The user
  may have intentionally cancelled** to force re-entry of the
  password (e.g. AP password rotated) — we treat it the same as
  miss, not as an error.
- Other status → fold to miss with the status code in
  `keychain_read` for debug surfacing (e.g. `"err:-25291"`)

## Risks / Trade-offs

[**R1.** Touch ID is asked once per join, not once per process / session]
The user gets a prompt every `j`. Versus "Always Allow once, then
silent forever" this is more friction. → **Mitigation:** the gesture is
sub-second on modern Macs; the user explicitly opted in to this
trade-off when picking Touch ID over Always Allow. We document it
in the README hotkey row.

[**R2.** On a Mac without Touch ID and without a paired Apple Watch,
`.userPresence` falls back to the login password prompt]
On a Mac mini with no biometric hardware, every `j` prompts for the
login password. This is *worse* than current PR #75 behaviour (which
would prompt for the *admin* password via the System keychain dialog
— still worse, but) and *similar* to typing the Wi-Fi password into
the sheet. → **Mitigation:** for users on non-Touch-ID Macs, the
file-on-disk fallback (mentioned in D1 alternatives) is the better
path; we leave that as a future option if the friction is reported.

[**R3.** Items written before this change (PRs #72-#75) lack the
`.userPresence` ACL]
Existing items will read silently — a security regression relative to
the new posture. → **Mitigation:** accepted. The cost of a forced
migration (`SecItemDelete` + re-prompt) exceeds the benefit; users who
care will rotate their AP password at some point, which routes through
the SecItemUpdate path and inherits the original ACL (which is None
for pre-existing items). True upgrade requires the user to delete the
entry in Keychain Access.app or `security delete-generic-password -s
com.chenchaoyi.diting.tianer -a <SSID>` and re-join through diting.
Documented in the test plan.

[**R4.** Touch ID dialog dismissal is indistinguishable from "no entry"
in our response]
Both surface as fall-through to sheet. A user who *meant* to cancel the
whole join sees the sheet, which is wrong. → **Mitigation:** the sheet
itself has a Cancel button that exits with the existing `cancelled`
code, so the worst case is one extra Esc press. Not worth distinguishing.

[**R5.** `LANG` propagation from Python to helper is not 100% reliable
for AppKit-rendered text]
The Touch ID prompt is rendered by `loginwindow` / `coreauthd`, which
respects the *system* locale, not the calling process's `LANG`. So a
user running diting with `--lang en` on a `zh_CN` macOS will see the
ZH prompt regardless of our string choice. → **Mitigation:** acceptable.
The prompt is rendered consistently with everything else the user sees
on macOS, which is the user's expectation. We still pass the
appropriate localized `kSecUseOperationPrompt` because some macOS
versions / dialog styles do honour it.

[**R6.** `kSecUseOperationPrompt` is documented as deprecated on macOS
since 10.11; replacement is `kSecUseAuthenticationContext` with an
`LAContext`]
Apple's docs steer toward `LAContext` for new code. → **Mitigation:**
`kSecUseOperationPrompt` is documented-deprecated but still functional
through macOS Sequoia (15). Migration to `LAContext` is straightforward
when we need to. Keeping the simpler path here.

## Migration Plan

No data migration. The change is forward-only: new writes carry the
`.userPresence` ACL, old writes don't. Old writes will be upgraded
opportunistically on the next password rotation (when `SecItemUpdate`
replaces the data — though, per D5, this does NOT re-apply
`kSecAttrAccessControl` because `SecItemUpdate` only writes the
attributes you pass). For a true upgrade the user has to delete the
old entry; this is documented in the test plan as the optional
"upgrade existing entries" step but not enforced.

Rollback: the change is contained in `attemptKeychainRead` and
`attemptKeychainWrite` in `main.swift`. Reverting the commit is safe;
items already written with the ACL will continue to read with a Touch
ID prompt, but the helper will neither break nor produce confusing
errors.

## Open Questions

- **Q1.** Should we expose a `--no-keychain` flag on `associate` for
  users who explicitly never want diting to cache passwords?
  → **Position:** out of scope. The existing "Remember this network"
  NSButton checkbox in the sheet (PR #69 spec) already gives the user
  that opt-out per-SSID; a global flag is redundant.

- **Q2.** On `make helper` rebuilds, does the user re-grant
  `.userPresence` ACL each rebuild? → No. `.userPresence` ACL is
  user-presence-gated, not cdhash-gated. The Touch ID prompt repeats
  per *read*, but the cdhash invalidation problem from PR #75
  ("Always Allow doesn't survive rebuilds") does not apply here.
  Confirmed via `SecAccessControlGetAccessControlFlags` docs.

- **Q3.** What about Macs with Touch ID hardware where the user has
  disabled "Use Touch ID to unlock" in System Settings? → macOS
  routes `.userPresence` through the configured authentication method
  (login password), so the user sees the same prompt as a non-biometric
  Mac. Acceptable.
