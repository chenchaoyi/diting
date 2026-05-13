## ADDED Requirements

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

The installer SHALL fetch the latest release via the GitHub API
(`api.github.com/repos/chenchaoyi/diting/releases/latest`),
download the right tarball, compute its SHA256, and abort if the
hash does not match the `SHASUMS256.txt` entry.

#### Scenario: Tarball matches SHASUMS256.txt
- **WHEN** the download completes and the computed SHA256 matches the entry in SHASUMS256.txt
- **THEN** the installer proceeds to extract and install

#### Scenario: Tarball SHA256 mismatch
- **WHEN** the computed SHA256 does NOT match the recorded entry
- **THEN** the installer aborts with a non-zero exit and stderr message naming the expected vs actual hash; no files are extracted

#### Scenario: Tag-locked install via DITING_VERSION env var
- **WHEN** the user runs `DITING_VERSION=v0.10.0 curl … | bash`
- **THEN** the installer fetches `v0.10.0` specifically rather than the latest tag

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
After extracting the tarball, the installer SHALL copy
`share/diting-tianer.app/` to
`~/Library/Application Support/diting/diting-tianer.app`, strip
the quarantine xattr so Gatekeeper does not block first launch,
and `open` the bundle once so macOS surfaces the Location Services
and Bluetooth TCC prompts to the user.

#### Scenario: First install primes TCC
- **WHEN** the helper bundle did not exist at the target path before this install
- **THEN** after the installer runs, the bundle exists at the target path, has no `com.apple.quarantine` xattr, and a brief background `open` invocation has fired so the user sees TCC prompts on their next interaction

#### Scenario: Subsequent installs preserve granted permissions
- **WHEN** the user has already granted Location Services and Bluetooth in a prior install and re-runs the installer with a same-cdhash helper binary
- **THEN** the new copy lands at the same path; TCC keys by cdhash so the grants persist with no re-prompt

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
