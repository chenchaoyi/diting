## Context

The project began as a Wi-Fi-only TUI ("wifiscope"). Over the last
few releases the scope expanded — BLE deep identification, BLE
detail modal, link-health probes (gateway / WAN beyond RF), an
RSSI-variance environment monitor as the seed for room-level
sensing. The roadmap adds mDNS / Bonjour / IoT discovery,
cellular (where Apple silicon supports it), and longer-term
sensing flagship work.

The current name has stopped describing the product. The 15
canonical capability specs already split roughly half / a third /
infrastructure between Wi-Fi, BLE, and shared. The decision to
rename was made before any public release: no installed users,
no PyPI / Homebrew listing, no domain or trademark filings to
preserve.

The new name is **谛听 (Diting)**. Tagline (locked in the
deciding session):

- EN: "Your Mac hears more than it tells you."
- ZH: "你的 Mac 听见了什么，告诉你。"

## Goals / Non-Goals

**Goals:**

- Rename every user-facing surface — CLI binary, helper bundle, env
  vars, JSONL log filename pattern, package directory, repo, all
  docs (EN + ZH) — to `diting` / 谛听
- Update the four canonical specs whose Requirements explicitly
  cite the old name (`cli`, `macos-helper`, `i18n`, `event-log`)
- Land in a single coordinated change so test green / spec strict
  / regression all pass at the same commit
- Preserve git history; CHANGELOG entry records the rename point
- Leave the door open for the future Linux backend by keeping
  Wi-Fi-specific class names (`WiFiBackend`, `WiFiPoller`) intact

**Non-Goals:**

- Behaviour changes beyond names. No new flags, no new Requirements,
  no new capabilities. Scope drift here would be hard to review.
- Spec name changes. `wifi-scanning`, `bluetooth-scanning`, etc.
  describe what the tool does, not what it's called; they stay.
- Logo design. Deferred to its own pass once domains are secured.
- Migration tooling. The maintainer is the only existing user of
  the helper bundle; a one-shot re-grant of TCC after rebuilding
  the helper is acceptable. No migration script needed.
- Domain registration. Tracked in user-side memory; not a code
  artifact.
- Updating archived `openspec/changes/archive/*/` proposals or
  delta specs that reference `wifiscope`. Those are historical
  records and intentionally frozen.

## Decisions

### Helper bundle name: `diting-tianer` (谛听之天耳)

The helper is the privileged Swift bundle that holds Location
Services + Bluetooth TCC grants and brokers the unredacted
CoreWLAN / CoreBluetooth signals back to Python. In the brand
metaphor, it is the *ear* of 谛听 — the part that does the
listening. Naming it `helper` (or `diting-helper`) is generic;
the entire system *is* a helper, so the word adds nothing.

**`天耳 (tiān'ěr)`** — the Buddhist supernatural power of hearing
all sounds in ten directions (`天耳通`, one of the 六神通 / six
abhijñā) — is precisely what 谛听 the creature *has*. The
mythology pairs them naturally: 谛听 is the listener; 天耳 is
the faculty by which it listens. This carries through cleanly
to the architecture:

- Brand front: **谛听 (Diting)** — the TUI, the CLI binary, the
  product
- Privileged sensor: **diting-tianer** — the Swift bundle, the
  TCC anchor, the subprocess Python shells out to

So:
- bundle: `helper/diting-tianer.app`
- binary: `helper/diting-tianer.app/Contents/MacOS/diting-tianer`
- bundle ID: `com.chenchaoyi.diting.tianer`
- subcommand invocations in spec / docs: `diting-tianer wifi-scan`,
  `diting-tianer ble-scan`, `diting-tianer bluetooth-status`

Conflict check: `tianer` is not occupied as a software name
(verified by GitHub / macOS / general software search at
decision time). The only adjacent issue is that the search term
"天耳通" in Chinese pulls up phone-monitoring / wiretap-app
topics — this is irrelevant for an internal bundle name that
never appears in user-facing brand prose, only in TCC settings,
build scripts, and the architecture explanation in
`DEVELOPMENT.md`.

### Rename the helper bundle ID, accept TCC re-grant

The Mac helper bundle's TCC grants are anchored by cdhash, which
is computed from the bundle's identifier + executable layout. A
new bundle ID (`com.chenchaoyi.diting.tianer`) means a new cdhash
means TCC treats it as a different app. The user has to click
Allow on Location Services and Bluetooth prompts again.

Alternative considered: keep the old bundle ID
(`com.chenchaoyi.wifiscope.helper`) and only rename the bundle
folder + executable. Rejected: the bundle ID surfaces in
`Info.plist` and shows up to the user in `tccutil reset`, log
output, and any future `osascript`/`openspec` integration. A
half-renamed bundle is worse than a fully-renamed one.

### Keep Wi-Fi-specific class names; rename only the app-level identifiers

`WiFiBackend`, `WiFiPoller`, `MacOSWiFiBackend`, `WiFiScanResult`
etc. describe a *capability*, not the app. A future
`LinuxWiFiBackend` would slot in next to `MacOSWiFiBackend`
unchanged. Renaming them to `DitingBackend` etc. would obscure
that.

Rule: anything whose meaning is "this is the Wi-Fi capability"
keeps its `WiFi` prefix. Anything whose meaning is "this is the
app named wifiscope" gets renamed.

### Don't rewrite git history

Old commits stay as `wifiscope`. The CHANGELOG entry under
`[Unreleased]` records the rename point. `git log --grep
wifiscope` will keep finding the historical context. Rewriting
history to retroactively rename everything would invalidate every
PR review on every existing commit and lose nothing in return.

### Default JSONL log filename pattern moves with the binary name

The existing default is `wifiscope-<YYYYMMDD-HHMMSS>.jsonl`. The
new default is `diting-<YYYYMMDD-HHMMSS>.jsonl`. The `.gitignore`
pattern (`/wifiscope-*.jsonl` per session) updates to match. Old
log files don't auto-migrate; they keep working as analyzer input
because the schema is locale-stable and binary-agnostic.

### `WIFISCOPE_*` env var migration is hard-cut, not graceful

For a project with no installed users, supporting both
`WIFISCOPE_LANG` and `DITING_LANG` simultaneously adds backwards-
compat code that would never get exercised. Hard-cut: rename all
seven env vars (`WIFISCOPE_LANG`, `WIFISCOPE_HELPER`,
`WIFISCOPE_INVENTORY`, `WIFISCOPE_GATEWAY`, `WIFISCOPE_WAN`,
`WIFISCOPE_SCAN_INTERVAL`, `WIFISCOPE_LATENCY_WAN_TARGET`) to
`DITING_*` in one commit and call it done. Add a release note in
CHANGELOG covering the rename in case anyone has a script with
the old name.

### One PR; one commit (or short squash)

The mechanical replacement spans seven docs (× 2 for ZH), 15
specs, every test file, the helper Swift sources, and the package
directory. Splitting it across PRs would mean intermediate
commits where some files use `diting` and others still use
`wifiscope` — broken builds, broken test runs, painful rebasing.
Land it as one coordinated change on `chore/rename-to-diting`,
squash on merge.

## Risks / Trade-offs

- **Risk**: a string slips through (CHANGELOG narrative, error
  message, docstring) and ships referring to `wifiscope` after
  rename.
  → **Mitigation**: `grep -rn 'wifiscope\|WIFISCOPE_'` clean
  except for `openspec/changes/archive/*` (historical records),
  CHANGELOG entries documenting the rename, and `git log` output.

- **Risk**: re-granting TCC permissions interrupts the
  maintainer's daily-driver flow if they happen to test on the
  same Mac mid-rename.
  → **Mitigation**: do the rename when convenient, not under
  time pressure; the helper bundle's first run after rename will
  show the standard macOS prompts.

- **Risk**: `openspec validate` strict-mode complaints about delta
  specs because we're MODIFYING requirements whose headers also
  change (`wifiscope` → `diting` in the requirement title).
  → **Mitigation**: use `MODIFIED Requirements` with full new
  content (header included). If validate complains, fall back to
  the RENAMED + MODIFIED pattern (header rename via FROM/TO,
  body via MODIFIED).

- **Risk**: the GitHub repo URL change breaks any external link
  to the codebase.
  → **Mitigation**: GitHub auto-redirects old URLs (`chenchaoyi/
  wifiscope` → `chenchaoyi/diting`) for the lifetime of the new
  repo. Old PRs / issues stay accessible.

- **Trade-off**: the rename inflates the diff substantially
  (every file in the package directory moves, every doc changes).
  PR review becomes "is the find-and-replace clean?" rather than
  meaningful behavioral review.
  → **Acceptance**: that's intentional. This change is structural,
  not behavioural; the test suite is the actual review surface
  ("did this break anything?"), not a human reading the diff.

## Migration Plan

1. Cut `chore/rename-to-diting` from latest `main`
2. `git mv src/wifiscope src/diting`
3. Update `pyproject.toml` (package name + console-script entry)
4. Mechanical replace `wifiscope` → `diting` and `WIFISCOPE_` →
   `DITING_` across `src/`, `tests/`, `helper/`, `scripts/`,
   `docs/`, `openspec/specs/`, `Makefile`, root markdown files.
   Skip `openspec/changes/archive/`, `CHANGELOG.md` historical
   sections, and any `.git/` paths.
5. Rename helper sources / build script / `Info.plist` /
   `helper/wifiscope-helper.app` → `helper/diting-tianer.app`,
   update bundle ID to `com.chenchaoyi.diting.tianer`
6. Update `.gitignore` log filename pattern
7. Re-build helper (`./helper/build.sh`), re-grant TCC
8. Run the four CI gates (pytest / regression / spec strict /
   change-validate). Iterate until all green.
9. CHANGELOG entry + commit + push + PR
10. **Post-merge**: rename the GitHub repo via the GitHub UI,
    accept the auto-redirect

Rollback: revert the merge commit on `main`. Helper TCC grants
for the old bundle linger but are harmless (just extra entries
in System Settings → Privacy).

## Open Questions

- **Bundle ID prefix** (`com.chenchaoyi.diting.tianer` vs
  `io.diting.tianer` vs `app.diting.tianer`)? Default for now:
  match the existing `com.chenchaoyi.wifiscope.helper` shape →
  `com.chenchaoyi.diting.tianer`. Maintainer can override
  during implementation.
- **Whether to also pre-emptively claim `diting-tools` /
  `diting-cli` etc as alternate console-script aliases**? Default:
  no — single binary `diting`, single namespace. Cleaner.
