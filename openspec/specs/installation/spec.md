# installation Specification

## Purpose
TBD - created by archiving change installable-cli. Update Purpose after archive.
## Requirements
### Requirement: A one-line installer SHALL drop a working `diting` onto a user's macOS without requiring Python, uv, or Xcode
A first-time end-user SHALL be able to install diting by running a
single shell command:

```bash
curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
```

The installer MUST NOT require the user to have Python, `uv`,
`brew`, or Xcode Command Line Tools installed beforehand. It MUST
NOT require sudo. On completion, `diting` SHALL be on the user's
PATH (directly, or via a hint the script prints to stderr) and the
Swift helper bundle SHALL be in place at
`~/Library/Application Support/diting/diting-tianer.app`.

#### Scenario: First-time install on Apple Silicon
- **WHEN** a user on a macOS 14+ arm64 Mac runs the curl-bash one-liner with no diting toolchain previously installed
- **THEN** `~/.local/bin/diting` exists and is executable; `~/Library/Application Support/diting/diting-tianer.app` exists; `diting --help` exits 0 after the user adds `~/.local/bin` to PATH (or follows the printed hint to do so)

#### Scenario: First-time install on Intel
- **WHEN** a user on a macOS 13+ x86_64 Mac runs the same one-liner
- **THEN** the installer downloads the `darwin-x86_64` tarball variant (not arm64), and the rest of the flow proceeds identically

#### Scenario: Repeat install / upgrade
- **WHEN** the user runs the installer a second time on the same machine
- **THEN** the installer downloads the current latest release, replaces `~/.local/share/diting/`, refreshes the helper at `~/Library/Application Support/diting/`, and prints "upgraded from <old> to <new>"

### Requirement: The installer SHALL refuse to run on non-macOS hosts with a clear error
The installer MUST detect non-Darwin / non-arm64-or-x86_64 hosts
and exit with a non-zero status and a one-line error message
naming the unsupported OS / arch. It MUST NOT partially install,
leave files behind, or attempt to "best-effort" the install.

#### Scenario: Run on Linux
- **WHEN** the user pipes the install.sh through bash on a Linux machine
- **THEN** the script exits non-zero with stderr containing "diting is macOS-only" and no files are written outside `/tmp`

#### Scenario: Run on Apple Silicon iPad-on-Mac emulation or other unsupported uname
- **WHEN** `uname -s` is not `Darwin`
- **THEN** the script exits non-zero with a clear error and writes no files

### Requirement: The installer SHALL fetch the matching release tarball from GitHub Releases and verify its SHA256
The installer SHALL download the platform-matching tarball from the project's GitHub Releases and SHALL refuse to proceed when the SHA256 does not match the published hash. For each supported arch (`darwin-arm64`, `darwin-x86_64`) a GitHub Release SHALL provide:

- `diting-X.Y.Z-darwin-{arch}.tar.gz` — the platform tarball
- `SHASUMS256.txt` — a sibling asset listing SHA256 hashes for
  each tarball, one per line, in `sha256sum`-compatible format

The installer SHALL resolve the latest release via the GitHub API
(`api.github.com/repos/chenchaoyi/diting/releases/latest`) with a bounded
timeout; when the API attempt fails, it SHALL fall back to following the
`https://github.com/<repo>/releases/latest` redirect through the same
candidate chain used for asset downloads (GitHub-direct first, then the
mirror proxies), reading the version tag from the redirect's final URL
(`…/tag/<version>`). A tag parsed from the redirect SHALL be accepted only
when it matches a version shape (optional `v` + leading digit). When every
resolution path fails, the installer SHALL abort with guidance naming both
escapes — `DITING_VERSION=vX.Y.Z` to skip resolution, and
`DITING_INSTALL_MIRROR` for the asset mirrors. The installer SHALL then
download the right tarball, compute its SHA256, and abort if the hash does
not match the `SHASUMS256.txt` entry.

Version resolution does not move the trust anchor: it only selects *which*
tag to fetch; the tarball is still verified against a `SHASUMS256.txt`
that is attempted GitHub-direct first.

The README (EN + ZH) SHALL document the bootstrap mirror form for networks
where `raw.githubusercontent.com` itself is blocked (the script cannot help
before it runs): prefixing the raw script URL with a chain proxy, e.g.
`curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash`.

#### Scenario: Tarball matches SHASUMS256.txt
- **WHEN** the download completes and the computed SHA256 matches the entry in SHASUMS256.txt
- **THEN** the installer proceeds to extract and install

#### Scenario: Tarball SHA256 mismatch
- **WHEN** the computed SHA256 does NOT match the recorded entry
- **THEN** the installer aborts with a non-zero exit and stderr message naming the expected vs actual hash; no files are extracted

#### Scenario: Tag-locked install via DITING_VERSION env var
- **WHEN** the user runs `DITING_VERSION=v0.10.0 curl … | bash`
- **THEN** the installer fetches `v0.10.0` specifically rather than the latest tag

#### Scenario: API blocked, redirect fallback resolves the version
- **WHEN** `api.github.com` is unreachable but the `releases/latest` redirect succeeds (direct or via a chain proxy)
- **THEN** the installer resolves the version from the redirect's final `/tag/<version>` URL and proceeds to the download step

#### Scenario: Resolution fails everywhere with actionable guidance
- **WHEN** the API and every redirect candidate fail
- **THEN** the installer aborts non-zero with a message naming `DITING_VERSION` to pin a version and `DITING_INSTALL_MIRROR` for mirrors

#### Scenario: A non-version redirect is rejected
- **WHEN** a proxy answers the `releases/latest` redirect with a final URL that does not end in a version-shaped `/tag/<version>`
- **THEN** that candidate is rejected and the next one tried

### Requirement: The installer SHALL download via a validated mirror chain with GitHub as the trust anchor
When a GitHub Releases download fails (the chronic CN-network stall on `objects.githubusercontent.com`), the installer SHALL fall back through an ordered chain of mirror proxies rather than a single mirror, and SHALL validate the content of every downloaded asset before trusting it. GitHub Releases stays the canonical trust anchor; SHA256 verification of the tarball remains mandatory and unchanged.

**Mirror chain.** For a GitHub asset URL `U`, the candidate order under the default `auto` mode SHALL be: `U` (GitHub direct), then each proxy in the default chain applied as `<proxy>U`. The default chain SHALL be live proxies maintained in one place in the script; at time of writing `https://ghfast.top/`, `https://gh-proxy.com/`, `https://ghproxy.net/`. The dead `https://ghproxy.com/` SHALL NOT be in the chain. Each attempt keeps a bounded per-attempt timeout.

**Content validation.** An attempt SHALL count as successful only when the transfer succeeds AND the body is the expected kind of file:
- `SHASUMS256.txt` SHALL be accepted only if it contains a parseable checksum entry for the target tarball (a `<64-hex>` hash in the row whose second field is the tarball filename). An HTML page, empty body, or rate-limit stub returned with HTTP 200 SHALL be rejected.
- the tarball SHALL be accepted only if it is a valid gzip stream.

A rejected body SHALL be discarded and the next candidate tried. The step SHALL fail only when the whole chain is exhausted, with an error that reflects the real failure (chain exhausted / invalid content) rather than a misleading "missing entry".

**SHASUMS prefers GitHub-direct.** Under `auto`, `SHASUMS256.txt` SHALL always be attempted from GitHub-direct first regardless of where the tarball was obtained; a proxy SHALL serve `SHASUMS256.txt` only if GitHub-direct fails for it too. This narrows the window in which a single proxy could substitute a matching forged tarball+hash pair.

**Mirror selection grammar.** `DITING_INSTALL_MIRROR` SHALL accept:
- `auto` (default) — GitHub-first, then the proxy chain, with SHASUMS GitHub-first.
- `github` — GitHub only; no proxies.
- `ghproxy` — back-compat keyword; skip the GitHub-first attempt and use the proxy chain directly (for users who know GitHub is blocked).
- any value beginning with `http://` or `https://` — use it as the sole custom proxy prefix (e.g. a self-hosted gh-proxy), still GitHub-first under the `auto`-style ladder.

Any other value SHALL abort before downloading with a clear message naming the accepted forms.

**Honest trust notice.** When a proxy serves an asset, the installer SHALL surface a notice naming the proxy used, and the completion notice SHALL distinguish "tarball via mirror, SHASUMS direct from GitHub" (trust anchored on GitHub) from "SHASUMS also via mirror" (trust anchored on that mirror's bytes).

#### Scenario: GitHub fails, first live proxy in the chain serves the tarball
- **WHEN** the GitHub tarball URL fails and the first proxy returns the correct gzip bytes
- **THEN** the installer accepts the tarball from that proxy, proceeds to SHA verification, and the next proxies are not tried

#### Scenario: A dead proxy returning an HTML 200 is skipped, not fatal
- **WHEN** the GitHub URL fails and the first proxy returns HTTP 200 with an HTML landing page for `SHASUMS256.txt`
- **THEN** the installer rejects the HTML (no valid checksum entry), tries the next proxy, and succeeds when a later proxy returns a real `SHASUMS256.txt` — it does NOT die with "missing entry"

#### Scenario: Whole chain exhausted
- **WHEN** GitHub and every proxy fail or return invalid content for the tarball
- **THEN** the installer aborts non-zero at the download step with a message stating the chain was exhausted, naming the asset; no files are extracted

#### Scenario: SHASUMS taken from GitHub even when the tarball came from a proxy
- **WHEN** the tarball is served by a proxy but GitHub-direct succeeds for `SHASUMS256.txt`
- **THEN** `SHASUMS256.txt` is the GitHub-direct copy, the tarball is verified against it, and the completion notice states trust is anchored on GitHub

#### Scenario: Custom mirror via DITING_INSTALL_MIRROR URL
- **WHEN** the user runs `DITING_INSTALL_MIRROR=https://gh.example.test/ curl … | bash` and GitHub fails
- **THEN** the installer retries via `https://gh.example.test/<github-url>` and uses no other proxy

#### Scenario: Back-compat mirror keyword skips GitHub-first
- **WHEN** the user runs `DITING_INSTALL_MIRROR=ghproxy …`
- **THEN** the installer goes straight to the proxy chain for the tarball without the GitHub-first attempt, and still validates content

#### Scenario: Invalid mirror value aborts early
- **WHEN** `DITING_INSTALL_MIRROR=fastgit` is set
- **THEN** the installer aborts before any download with a message naming the accepted forms (`auto` / `github` / `ghproxy` / a URL)

#### Scenario: SHA256 verification still mandatory
- **WHEN** a tarball is obtained (from GitHub or any proxy) whose computed SHA256 does not match the validated `SHASUMS256.txt` entry
- **THEN** the installer aborts non-zero naming expected vs actual hash; no files are extracted

### Requirement: The installer SHALL extract the tarball under `~/.local/share/diting/` and symlink the binary at `~/.local/bin/diting`
The tarball layout MUST be:

```
diting-X.Y.Z/
├── bin/diting
└── share/diting-tianer.app/
    └── Contents/
        ├── Info.plist
        └── MacOS/diting-tianer
```

The installer SHALL extract into `~/.local/share/diting/` (creating
parents as needed), atomically replace any prior install, and
symlink `~/.local/bin/diting` to `~/.local/share/diting/bin/diting`.
The installer MUST NOT use sudo.

#### Scenario: Fresh install with no prior `~/.local/share/diting/`
- **WHEN** the user has no prior diting install
- **THEN** the tarball extracts to `~/.local/share/diting/`, `~/.local/bin/diting` is a symlink to `bin/diting`, and `diting --help` succeeds from a shell where `~/.local/bin` is on PATH

#### Scenario: Upgrade replacing an older install
- **WHEN** an older `~/.local/share/diting/` already exists from a previous install
- **THEN** the installer moves the existing directory aside (rename to `~/.local/share/diting.old/`), extracts the new tarball, removes `.old` only after the new symlink target verifies as executable; on failure mid-flight the old directory is restored

### Requirement: The installer SHALL place the Swift helper bundle under `~/Library/Application Support/diting/` and prime it for TCC
After extracting the tarball, the installer SHALL copy `share/diting-tianer.app/`
to `~/Library/Application Support/diting/diting-tianer.app`, strip the quarantine
xattr so Gatekeeper does not block first launch, and then drive the TCC grants to
completion by invoking the just-installed `diting setup`. `setup` opens the
bundle so macOS surfaces the Location → Bluetooth → Notifications prompts and
verifies the outcome (per the `permission-setup` capability), so the user grants
once at install rather than re-granting at first launch.

In the framed render tiers (FULL / PLAIN) the installer SHALL present the
permission grant as its own numbered step — the final step, labelled
`Permissions` — and SHALL render `diting setup`'s output as the body of that
step (indented under the step header via `DITING_SETUP_INDENT`). The helper-copy
step (`Helper`) and the grant step (`Permissions`) SHALL be distinct numbered
steps, so the displayed step total reflects the grant as its own step.

The installer SHALL render the helper / prompt language in the user's
macOS-preferred locale: it SHALL pass `DITING_LANG=<en|zh>` to `setup` (derived
from `defaults read -g AppleLanguages` first entry; `zh` when it starts with
`zh`, otherwise `en`), and `setup`'s bundle launch SHALL carry the matching
`-AppleLanguages '(<bundle-locale-tag>)'` (`zh-Hans` for `zh`, else `en`) so the
helper status window, the macOS TCC prompt headers, and the prompt bodies all
render in one locale (no mixed-language stack).

On an interactive (TTY) install the `setup` step SHALL block-and-verify the
required grants (Location, Bluetooth); on a non-interactive install (non-TTY / CI
/ piped) it SHALL NOT block — the installer SHALL invoke `setup` in its
non-interactive mode so the install completes without waiting. `setup` owns the
permission-outcome surface; the installer SHALL NOT separately fire a
fire-and-forget `open`.

#### Scenario: First install primes TCC on a Chinese-locale Mac
- **WHEN** the user runs the installer on a Mac whose `defaults read -g AppleLanguages` first entry starts with `zh`
- **THEN** the installer invokes `diting setup` with `DITING_LANG=zh`, and the helper launches with `-AppleLanguages '(zh-Hans)'`
- **AND** the helper's status window text, the macOS Location prompt header (`谛听 · 天耳`), and the prompt body text all render in Simplified Chinese — no mixed-language stack

#### Scenario: First install primes TCC on an English-locale Mac
- **WHEN** the user runs the installer on a Mac whose `defaults read -g AppleLanguages` first entry does not start with `zh` (or `defaults` returns no value)
- **THEN** the installer invokes `diting setup` with `DITING_LANG=en`, and the helper launches with `-AppleLanguages '(en)'`
- **AND** the helper status window text, the macOS Location prompt header (`diting · tianer`), and the prompt body text all render in English

#### Scenario: The permission grant is its own numbered step
- **WHEN** the user runs the installer in a framed tier (FULL / PLAIN)
- **THEN** the grant is shown as the final numbered step labelled `Permissions`, distinct from the `Helper` step, and `diting setup`'s output is indented as that step's body

#### Scenario: Interactive install verifies the grants before finishing
- **WHEN** the user runs the installer in an interactive terminal and clicks Allow on the Location and Bluetooth prompts
- **THEN** the `setup` step confirms both grants are present before the install completes, so the first `diting` launch does not re-prompt

#### Scenario: Non-interactive install does not block
- **WHEN** the installer runs under CI / a pipe (stdout is not a TTY)
- **THEN** the `setup` step runs non-interactively (probe-once, no open, no wait) and the install completes without blocking

#### Scenario: Subsequent installs preserve granted permissions when cdhash is unchanged
- **WHEN** the user has already granted Location Services, Bluetooth, and Notifications in a prior install and re-runs the installer with a same-cdhash helper binary
- **THEN** the new copy lands at the same path; TCC keys by cdhash so the grants persist; `setup` verifies them already-present with no re-prompt

#### Scenario: Subsequent install with cdhash change re-prompts once
- **WHEN** a user upgrades from a release whose helper bundle had a different cdhash
- **THEN** the `setup` step fires the TCC prompts again in order, the user clicks Allow on each, and grants land against the new cdhash
- **AND** future same-version installs at the same path skip the prompts

### Requirement: The installer SHALL print a PATH-update hint when `~/.local/bin` is not on PATH
After installing, the installer SHALL check whether
`~/.local/bin` is on the user's `PATH`. If not, it SHALL print a
single-line hint suggesting the appropriate `export PATH` addition
for the user's detected shell (`zsh`, `bash`, or `fish`).

#### Scenario: PATH already includes `~/.local/bin`
- **WHEN** the user's shell already has `~/.local/bin` on PATH
- **THEN** the installer prints "diting is on your PATH — run `diting`" and no hint

#### Scenario: PATH does NOT include `~/.local/bin` on zsh
- **WHEN** the detected shell is zsh and the PATH check fails
- **THEN** the installer prints exactly: `Add to ~/.zshrc:  export PATH="$HOME/.local/bin:$PATH"`

### Requirement: The frozen-binary install path SHALL coexist with the `uv run diting` developer workflow
Installing via the curl-bash one-liner MUST NOT break the
contributor flow (`git clone` + `uv sync` + `make helper` +
`uv run diting`). A developer can have both installed at once —
the frozen binary on PATH and a working repo checkout — without
the two paths interfering. In particular, `make helper` in the
repo MUST keep working, and `find_helper()` MUST keep finding the
in-repo dev build when invoked through `uv run`.

#### Scenario: Developer has both paths installed
- **WHEN** a contributor has run the curl-bash installer AND has a repo checkout where they run `uv run diting`
- **THEN** `uv run diting` picks up the in-repo helper (priority in `find_helper()` ordering), and standalone `diting` picks up the Application Support helper — neither shadows the other

#### Scenario: Developer uninstalls the frozen binary
- **WHEN** the contributor deletes `~/.local/bin/diting` and `~/.local/share/diting/`
- **THEN** `uv run diting` in the repo continues to work; the in-repo helper bundle is unaffected

### Requirement: The frozen binary SHALL bundle lazy-imported native deps
The PyInstaller-frozen `diting` binary SHALL include every runtime dependency
reachable only via a lazy import — in particular the companion-bridge crypto
path (PyNaCl → libsodium → cffi's `_cffi_backend` C extension), which nothing on
the startup / hot path touches. Opening the companion screen, pairing, or
running `diting companion status` from the frozen binary SHALL NOT crash with a
missing-native-module error (`ModuleNotFoundError: No module named
'_cffi_backend'`). The frozen-build command MUST force-collect such packages
rather than relying on PyInstaller's static import analysis.

#### Scenario: Companion path works in the frozen binary
- **WHEN** a user runs the frozen `diting` and opens the companion screen (`k`) or runs `diting companion status`
- **THEN** the companion crypto imports succeed and no `_cffi_backend` (or other missing-native-module) error is raised

#### Scenario: The build command keeps PyNaCl collected
- **WHEN** the frozen-build command is constructed
- **THEN** it force-collects `nacl` + `cffi` and hidden-imports `_cffi_backend`, so a lazy-imported native dep cannot silently fall out of the bundle

