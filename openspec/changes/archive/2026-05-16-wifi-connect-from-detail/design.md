## Context

`WifiDetailScreen` (`src/diting/tui.py:3699`) is a read-only inspector
opened with `i` / `enter` on a row in the Nearby BSSIDs panel. The
Swift helper (`helper/Sources/diting-tianer/main.swift`) currently
exposes four subcommands — `scan`, `ble-scan`, `bluetooth-status`,
`notify` — and owns the Location Services TCC grant CoreWLAN needs to
return unredacted SSID / BSSID. CoreWLAN's `CWInterface.associate(...)`
sits unused: nothing in diting writes to the link layer today, only
reads. The closest existing action is `c` / `action_reroam`
(`src/diting/tui.py:5936`), which power-cycles the radio so the OS
re-picks the best BSSID for the **already-saved** SSID — it cannot
move the user to a different network.

The user-facing ask: from a non-current SSID's detail page, press one
key to switch to that network. Use saved Keychain credentials when
they exist; surface a native macOS password prompt when they don't.

Two structural facts shape the design:

1. **The helper is the right place for the AppKit password sheet.**
   The helper bundle is already a foregroundable `.app` with
   `NSApplication` (the `scan` path goes through
   `dispatchMain()` after registering with CoreLocation), and it
   already holds the TCC grants CoreWLAN needs. Rendering an
   `NSPanel` + `NSSecureTextField` in the helper subprocess gives
   the user a real macOS dialog — fonts, focus ring, paste-from-
   Keychain-suggestions, the lot — while the Python TUI keeps
   running and the password never touches Python memory or argv.
2. **CoreWLAN's `associate(toNetwork:password:error:)` is the
   minimum-friction join API for personal Wi-Fi.** Documented
   behaviour: for a network whose SSID has a matching entry in the
   **System** Keychain (the one the user populated by joining
   from the menubar at some point in the past), passing
   `password: nil` causes the lower layers of the Wi-Fi stack to
   pull the saved password and complete the association. For an
   open network, `password: nil` also works. For Enterprise /
   802.1X, there is a separate `associate(toEnterpriseNetwork:...)`
   API that demands EAP identity, certificates, and the rest —
   not something we can usefully prompt for in a one-shot helper
   call. We refuse Enterprise loudly.

## Goals / Non-Goals

**Goals:**

- One key (`j`) on the Wi-Fi detail page initiates a join of the
  inspected SSID, gated by a yes/no confirmation modal.
- "If a saved password exists, just use it" — leverage Keychain
  via `CWInterface.associate(toNetwork:password:nil error:)`.
- "If no saved password, use system behaviour to input it" —
  helper renders an AppKit `NSSecureTextField` sheet that is, by
  every observable property, the macOS native password dialog.
- On successful first-time password entry, write the credential
  back to the System Keychain so subsequent joins of the same
  SSID hit the saved-password fast path.
- Existing `c` (`action_reroam`) stays exactly as is. The two
  bindings address different user intents and stay distinct.

**Non-Goals:**

- BSSID-pinned joins. `CWInterface.associate(toNetwork:password:)`
  takes a `CWNetwork` whose SSID it uses; the OS picks the BSSID.
  We log the user's intended BSSID for the event ring but do not
  promise we'll land on it.
- Enterprise / 802.1X association. The helper refuses with a
  structured error; the TUI tells the user to join from the
  system Wi-Fi menu once, after which the saved-Keychain fast
  path works.
- Disconnect / forget-network / re-order preferred-networks.
  Those are separate user intents and should be a follow-up
  change if asked for.
- Multi-interface support. macOS laptops with two Wi-Fi
  interfaces are vanishingly rare; we operate on
  `CWWiFiClient.shared().interface()` (the default), same as
  every other path in the helper.
- A custom "password remembered" toggle in the TUI. The default
  is "save to Keychain"; the sheet itself carries a native
  "Remember this network" checkbox (standard `NSSecureTextField`
  + checkbox pattern) so the user can opt out per-join without
  the TUI needing a UI surface for it.

## Decisions

### D1 — `j` opens a confirmation modal before any association call

`WifiDetailScreen.BINDINGS` gains `Binding("j", "join", t("Join"))`
which dispatches `DitingApp.action_wifi_join()`. That action does
**not** call `associate` directly; it pushes a new
`JoinConfirmScreen(ModalScreen)` with `Switch to <SSID>?` and
yes/no buttons (default focus = no, to make the destructive
default the safer one). Only after the user confirms does the App
spawn the helper subprocess.

**Alternatives considered:**

- *No confirmation, just join.* Rejected. Pressing `j` reflexively
  while reading a neighbouring AP's detail would tear down the
  current connection. The cost of the extra Enter press is one
  keystroke; the cost of a wrong-key disconnect is 5-30 s of
  re-association on the user's actual network.
- *Toast notification with undo.* Rejected. macOS Wi-Fi doesn't
  have an "undo" — once you've switched, switching back is
  another full association cycle. Confirmation up front is the
  honest UX.

### D2 — Helper exposes one `associate` subcommand; password flows on stdin

The Python backend spawns the helper as
`diting-tianer associate --ssid <ssid> [--bssid <bssid>]` with
stdin **piped**. If the helper's `associate(password: nil)`
call succeeds (open network or Keychain hit), it exits 0 with
`{"ok": true, "bssid": "...", "keychain_saved": false}` on stdout.
If `associate(password: nil)` fails with a "password required"
error code, the helper shows the AppKit sheet on the main run
loop; the password the user types is fed into a second
`associate(toNetwork:password:error:)` call **inside the helper**
— it never crosses the subprocess boundary back to Python.

If the user had piped a password in on stdin (Python could in
principle do that for "join the SSID I have a password for that
isn't yet in Keychain" flows — not in this change's UI, but
keeps the API honest), the helper uses it directly and skips the
sheet. The Python backend for *this* change always passes empty
stdin and lets the helper either succeed via Keychain or render
the sheet.

**Why stdin, not argv:** the helper's command line is visible in
`ps` output, in `/proc/*/cmdline` (Linux-style; macOS exposes
similar through `ps -eww`), and in any audit logging. Passwords
in argv are a 101-level security mistake. Stdin is private to
the parent/child pair.

**Why a fresh subprocess instead of one long-running helper:**
matches every other helper subcommand (`scan` is also one-shot;
`ble-scan` is the only streaming one). The helper's exit code is
the unambiguous success / failure signal — no protocol
versioning, no "what state am I in" tracking.

### D3 — Native AppKit sheet rendered by the helper, not a TUI password input

When `associate(password: nil)` reports
`kCWAssociationError` / "password required", the helper hands
control to its `dispatchMain()` loop with an
`NSApplication`-backed `NSPanel` window holding:

- An `NSImageView` with the helper's bundle icon (matches
  every other native Wi-Fi password sheet on the system).
- An `NSTextField` reading `Enter the password for "<SSID>"`.
- An `NSSecureTextField` for the password.
- A `NSButton` checkbox `Remember this network` (default ON).
- "Join" + "Cancel" buttons (Join is default; Cancel maps to
  Escape).

On Join, helper:

1. Calls `CWInterface.associate(toNetwork:password:<typed>
   error:)` with the typed string.
2. If success and checkbox ON → calls
   `+[CWKeychain setWiFiPassword:forSSID:]` (the same private
   class CoreWLAN uses internally — public-ish via bridging
   headers; the helper already does TCC-gated CoreWLAN work).
3. Emits `{"ok": true, "bssid": "...", "keychain_saved":
   <bool>}` on stdout, exits 0.

On Cancel: exits 6 with `{"error": "user cancelled", "code":
"cancelled"}`.

On wrong password: exits 7 with `{"error": "...", "code":
"auth_failed"}`. The TUI's notify rendering distinguishes
`auth_failed` from cancellation so the user knows whether their
typing or the password was the problem.

**Alternatives considered:**

- *Render the password prompt in Textual.* Rejected. Textual has
  `Input(password=True)` but it lives inside a TUI on macOS
  Terminal — no Touch ID autofill, no Keychain integration, no
  paste-from-1Password sheet, no native focus ring. The whole
  point of "use system behaviour" is to get the user macOS's
  password UX, not a 1990s-style hidden-text prompt.
- *Shell out to `osascript` to render a Standard Additions
  dialog.* Rejected. Standard Additions password dialogs return
  the password to the parent process, which puts the password
  back in Python memory and into the AppleEvent transport — the
  exact thing stdin-piping was designed to avoid.
- *`NEHotspotConfiguration`* (iOS-style). Rejected. macOS marks
  the API as available but the implementation is gated behind
  entitlements the helper bundle doesn't have and that are
  reserved for Apple's own clients.

### D4 — Enterprise networks refused with a structured error

Detection: the `CWNetwork` we look up in scan results exposes
`supportsSecurity_(...)` for each `CWSecurity` enum value. If
the network reports any Enterprise variant (`wpa2Enterprise`,
`wpa3Enterprise`, `wpa2WPA3Enterprise`, etc.) and no
non-Enterprise variant, the helper exits 5 immediately with
`{"error": "Enterprise / 802.1X — use the system Wi-Fi menu to
join once; subsequent joins will use the saved credential",
"code": "enterprise_unsupported"}`. The TUI renders the message
text as a notify.

Why not silently fall through to `associate(password: nil)`
anyway: it would either no-op or pop the OS's own credential
prompt outside the helper's window, which is confusing — the
user pressed `j` in our TUI, they should get a clear refusal in
our TUI, not a system dialog that floats up from nowhere.

### D5 — `(joining…)` annotation rendered against the local intent, not a backend state

Between confirm and the next 1 Hz poller tick, the App has no
new `Connection` to render. We could either:

a) Spin the modal title with `(joining…)` for a fixed ~3 s
   timeout regardless of helper status, then resync when the
   poller catches up.
b) Track an `_app_joining_to: tuple[str, datetime] | None` on
   the App and clear it when (i) the next poll's connection
   BSSID matches the joined SSID, or (ii) the helper subprocess
   reports failure, or (iii) 10 s elapse (whichever first).

We pick (b). It's more honest (the annotation reflects intent +
backend signal), and crucially the failure path clears the
annotation immediately rather than letting it hang past the
notify.

### D6 — Tests stay deterministic via a `FakeAssociator` injectable

`Backend.associate(ssid, bssid)` is the seam. Tests inject a
`FakeAssociator` returning canned outcomes (success,
auth_failed, enterprise_unsupported, cancelled, ssid_not_in_scan)
to drive the App / modal behaviour without spawning a real
helper subprocess. A separate parser test covers the JSON
response decoder. We do **not** stand up a fake macOS network
stack — the CoreWLAN call itself is exercised only in manual
real-environment QA (`/tui-audit`).

### D7 — Lossless / hitless cross-SSID switching is explicitly not a goal

A single Wi-Fi radio cannot be associated to two BSSIDs at once
(802.11 fundamental). A cross-SSID join therefore has a
mandatory L2 disassociate→authenticate→associate window —
typically 2-5 s for WPA2-Personal, 5-10 s for the
saved-Enterprise fast path. On top of that, the new SSID's DHCP
lease almost always yields a different IPv4 (different VLAN /
subnet), which forcibly resets every TCP connection bound to
the old address. macOS has no per-flow IP-migration primitive
we could lean on, and bringing up a second Wi-Fi station on the
same radio is not exposed by CoreWLAN.

What this means for the design:

- The implementation SHALL skip any explicit
  `iface.disassociate()` and let `CWInterface.associate(...)`
  drive the L2 transition. This is the minimum-window path:
  CoreWLAN sends the deauth frame and the new auth+assoc burst
  back-to-back, without the radio-power-cycle latency that
  `force_reroam` incurs (and without `disassociate`'s known
  failure mode on 802.1X, called out in `macos_backend.py:249`).
- The `JoinConfirmScreen` prompt SHALL warn the user explicitly
  that existing TCP connections will be torn down for the
  duration of the gap. This is the consent the modal exists to
  collect — the user pressed `j`, but they may not have thought
  through the SSH / call / upload they have open right now.
- If a future change wants truly hitless behaviour, the
  realistic paths are (i) operate over a second active
  interface (Ethernet / USB-Ethernet / iPhone tethering) so IP
  traffic stays alive across the Wi-Fi gap — but that is a
  system-level routing concern outside diting's scope, and (ii)
  same-ESS roaming via 802.11r/k/v, which is `c` / `force_reroam`
  territory, not `j` / cross-SSID join. Both are out of scope
  here.

## Risks / Trade-offs

- **[CWInterface.associate with `password: nil` doesn't, in
  practice, pull from Keychain on every macOS version]** →
  Mitigation: the helper's response carries a
  `tried_keychain_fallback: bool` and the implementation tasks
  call out an early manual-test gate (Tasks §1.5) to validate
  on macOS 14 / 15 / 26. If Keychain auto-fill turns out to be
  unreliable, fall back to: helper checks Keychain via
  `+[CWKeychain findWiFiPasswordForSSID:]` first, then passes
  the result through `associate(...)` as a normal password
  call. Same security properties (password never leaves the
  helper), one extra system call.
- **[User taps `j` on an Enterprise network and is mildly
  surprised by the refusal]** → Mitigation: the modal's
  Identity section already knows the security type (we render
  it). When security is Enterprise, the footer (currently
  `Esc / i to close`) gains an extra line:
  `j: join — unavailable for Enterprise networks (join from
  system Wi-Fi menu)`. Pressing `j` still produces a notify,
  but the user has already been told.
- **[Password written to Keychain ends up in the **user**
  Keychain instead of System, so other users on the Mac can't
  use it]** → Acceptable. diting is a single-user TUI; we
  don't need cross-user credential sharing.
- **[Helper's AppKit sheet pops up "from nowhere" because the
  TUI is in the foreground]** → macOS auto-focuses the sheet
  (it's a real `NSPanel.makeKeyAndOrderFront`); the helper
  also calls `NSApp.activate(ignoringOtherApps: true)` before
  showing it. The terminal goes to background, the sheet is
  modal, the user types, the sheet closes, focus returns. Same
  behaviour as the existing helper-bundle launch path. Confirm
  in `/tui-audit` smoke test that the sheet is reachable
  without a click — keyboard-only flow MUST work.
- **[`+[CWKeychain setWiFiPassword:forSSID:]` is private API]**
  → It is. The helper bundle is unsandboxed and `.app`-scoped;
  using a private CoreWLAN class won't change that. If a future
  macOS deprecates the symbol, the helper will fail to
  associate the new-Keychain-write step but the associate
  itself succeeds — the user just has to type the password
  again next time. We catch a `nil`/throw from that call and
  set `keychain_saved: false` in the response rather than
  failing the whole join.
- **[Operating on the wrong interface in a dual-Wi-Fi Mac]** →
  Non-goal. The helper uses
  `CWWiFiClient.shared().interface()` (default interface), same
  as scan. If someone reports a dual-interface bug, that's a
  separate change.
