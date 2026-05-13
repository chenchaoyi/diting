## Context

diting is positioned as a macOS terminal listening post for Wi-Fi /
BLE / Bonjour / link health. The audience is anyone who wants a
better view than the system menu's Wi-Fi list — not just Python
developers. Today the only documented install path is:

```bash
git clone …
cd diting
brew install uv         # if missing
uv sync
make helper
open helper/diting-tianer.app   # grant Location Services + Bluetooth
uv run diting
```

Six steps, three toolchains (git, brew/uv, Xcode CLT). That ceiling
is fine for contributors but rules out most of the target audience.

Claude Code's pattern (`curl -fsSL … | bash`) is the right model
for diting because:

1. **macOS-only target.** We don't have to solve cross-platform
   distribution; a script that detects `darwin-arm64` /
   `darwin-x86_64` covers the entire user base.
2. **Native helper bundle.** The Swift `.app` was always going to
   require a binary distribution step. Packaging it alongside the
   CLI in one tarball makes them version-locked atomically.
3. **No Python in the user's path.** PyInstaller freezes
   interpreter + deps into a single ~60–80 MB binary, so users
   don't need Python 3.11+ on their machine.

The current `_helper.py` discovery logic already supports
multiple install locations (repo dev build, /Applications,
~/Applications). Adding `~/Library/Application Support/diting/` to
the list is a one-line code change; the heavy lift is everything
around it.

## Goals / Non-Goals

**Goals:**

- Single command for end users: paste one curl line, get a working
  `diting` on the PATH plus a granted helper bundle (modulo a
  one-time Gatekeeper dialog + TCC prompts).
- Atomic upgrade story: re-running the installer downloads the new
  tarball and replaces both CLI and helper. No partial-upgrade
  state.
- Developer workflow preserved exactly: `git clone` + `uv sync` +
  `make helper` + `uv run diting` continues to work for
  contributors. The frozen-binary path is strictly additive.
- Tests proving the installer's arch detection + URL format + PATH
  hint don't regress.
- Release flow: tag `vX.Y.Z` on `main`, GitHub Actions builds both
  arch tarballs and attaches them to the GitHub Release.

**Non-Goals:**

- PyPI / `pipx install`. Future change. The frozen tarball is the
  primary install path; pipx is a parallel channel for Python folks.
- Homebrew tap. Future change. Adds a tap repo + Formula, layers
  on top of the frozen tarball.
- Apple Developer signing + notarization. Future change. Removes
  the Gatekeeper "unidentified developer" dialog the user sees on
  first launch of the helper. Until then the install script prints
  a one-line note explaining what to expect.
- Linux / Windows. diting is macOS-only by design (depends on
  CoreWLAN + CoreBluetooth). The installer rejects non-Darwin with
  a clear error.

## Decisions

### Why PyInstaller (vs Nuitka / shiv / pex / uv tool)

PyInstaller is the safest choice for a Textual + pyobjc app:

- **Textual** has community wisdom on PyInstaller packaging
  (works out of the box with the `--collect-all textual` flag).
- **pyobjc** is the harder dep — it lazy-loads ObjC framework
  bridges via `pyobjc-framework-*` distributions. PyInstaller
  has known hooks for `pyobjc_core` and individual framework
  packages; we need `--collect-all pyobjc_framework_CoreWLAN` and
  `--collect-all pyobjc_framework_SystemConfiguration` to make sure
  the bridge metadata files travel.
- **Nuitka** would produce a smaller binary but the pyobjc story
  is less well-trodden.
- **shiv / pex** ship .pyz archives that still require a Python
  interpreter on the user's machine — defeats the "no Python
  needed" goal.
- **uv tool install** needs `uv` on the user's machine, which is
  the very thing we're trying to remove.

**Rejected alternative considered:** universal2 binary. PyInstaller
can produce a universal2 binary on an arm64 mac via the macOS
Python interpreter's universal2 build. But pyobjc's framework
wheels are arch-specific in practice; we'd have to build twice
anyway. Two arch-tagged tarballs is the simpler shape.

### `~/.local/bin` vs `/usr/local/bin` for the symlink

`~/.local/bin` does not require sudo, which preserves the "one
command, no extra prompts" UX. `/usr/local/bin` is on PATH by
default on macOS; `~/.local/bin` typically isn't. The installer
detects whether `~/.local/bin` is on PATH and either prints a
PATH-update hint (`echo 'export PATH="$HOME/.local/bin:$PATH"' >>
~/.zshrc`) or, if a `/usr/local/bin` symlink slot is writable
without sudo (rare on modern macOS), uses that instead.

**Rejected alternative:** require sudo. Breaks the unattended /
laptop-install UX and would need a separate prompt path. Print a
hint instead.

### Where the tarball extracts

`~/.local/share/diting/` — XDG-style user-local install root.
Contains:
- `bin/diting` (the frozen binary)
- `share/diting-tianer.app/` (the helper bundle)

The installer then **copies** the helper to `~/Library/Application
Support/diting/diting-tianer.app`. Two-step because TCC keys by
cdhash AND by the bundle's resolved path; macOS Gatekeeper /
LaunchServices want the bundle to live somewhere it would
expect — `~/.local/share/` confuses macOS, `~/Library/Application
Support/` is the canonical user-local app data location.

The Python `find_helper()` only learns the `~/Library/Application
Support/` path. The XDG copy is just a staging area; on the next
`diting` run we don't look there at all.

**Rejected alternative:** install the helper directly to
`/Applications`. Requires sudo or a Finder drag, breaks the
single-command UX.

### Gatekeeper warning on first launch

Without code signing, macOS Gatekeeper shows a one-time
"diting-tianer cannot be opened because the developer cannot be
verified" dialog the first time the helper runs. The installer
script handles this by:

1. Copying the helper into place.
2. Running `xattr -dr com.apple.quarantine
   ~/Library/Application\ Support/diting/diting-tianer.app` to
   strip the quarantine xattr so Gatekeeper won't show the dialog.
3. `open` the helper once so TCC prompts (Location Services +
   Bluetooth) fire and the user can grant.

Stripping the quarantine xattr is the same trick Homebrew uses
for casks shipping unsigned binaries. It does not bypass code
signing requirements that LaunchServices might add in future macOS
versions (we'd need real signing for that), but it works today
on macOS 13–15.

**Rejected alternative:** print "right-click → Open" instructions.
Bad UX; users will get confused.

### Tarball SHA256 verification in the install script

The installer fetches `install.sh` and the tarball over HTTPS.
HTTPS already guarantees integrity. But:

1. GitHub Releases assets pass through a CDN; SHA verification is
   defence-in-depth.
2. The script reads the SHA from a sibling `SHASUMS256.txt` asset
   on the same release.

Both files come from the same HTTPS origin, so this isn't strong
crypto — it's mostly a guard against partial downloads. We omit
it for simplicity in v1 IF `curl --fail` is enough to catch
broken downloads. Decision: include SHA verification anyway, since
it's a few lines of bash and people copy install scripts to read
them before running.

### GitHub Actions matrix

```yaml
jobs:
  build:
    strategy:
      matrix:
        include:
          - os: macos-14   # M1 hosted runner → arm64
            arch: arm64
          - os: macos-13   # x86_64 hosted runner → x86_64
            arch: x86_64
```

Both runners build the Swift helper from source, run PyInstaller,
tarball, upload to the release. Triggered by `push` of a `v*` tag.

**Caveat:** `macos-13` deprecation. GitHub announced `macos-13`
runners will retire eventually. When it does, we move x86_64 builds
to whatever the latest x86_64 runner is, OR drop x86_64 support
(Apple Silicon adoption rate among Mac users is >70% as of 2026
and rising).

### Why preserve `uv run diting`

The contributor flow needs to keep working — both because
contributors are still our most reliable feedback loop, and
because the OpenSpec workflow assumes a working repo checkout.
Concretely:

- The `helper/diting-tianer.app` dev build still gets found first
  in `find_helper()`'s search order.
- `pyproject.toml`'s `[project.scripts]` entry stays put, so
  `uv run diting` keeps invoking `diting.cli:main`.
- Tests run via `uv run pytest` exactly as before.
- The frozen-binary install path adds new files (install.sh, the
  PyInstaller spec, the release workflow); it does not modify the
  source layout the contributor flow depends on.

The README's "Install" section gets the curl one-liner; "From
source / Contributing" keeps the `uv sync` + `make helper` flow.

## Risks / Trade-offs

- **PyInstaller + pyobjc edge cases.** pyobjc loads ObjC framework
  bridges lazily; PyInstaller's static analysis can miss some
  imports. → Mitigation: use `--collect-all pyobjc_framework_*`,
  add a smoke test that runs the frozen binary and asserts the
  Wi-Fi panel renders without an ImportError. The test runs in
  CI on every release-build PR.
- **Textual terminal-detection inside a frozen binary.** Textual
  reads terminal capabilities; sometimes PyInstaller's tempdir
  isolation interferes. → Mitigation: include a smoke test that
  launches the frozen binary with `--help` and checks it exits 0
  cleanly. Real TUI rendering is harder to test in CI; we cover
  it with the existing snapshot regression on the un-frozen path
  and trust that the install path doesn't change behaviour.
- **Binary size.** ~60–80 MB compressed is large for a CLI but
  reasonable given the helper bundle ships with it. → Mitigation:
  acknowledged as a trade-off vs the "no Python needed" benefit.
  PyInstaller's `--strip` shaves a few MB; we apply it.
- **macOS 26 / future TCC tightening.** If a future macOS release
  refuses to run unsigned binaries entirely, the frozen tarball
  path breaks. → Mitigation: documented as the trigger condition
  for the Phase-3 signing / notarization change. Until then,
  Gatekeeper accepts unsigned binaries when the quarantine xattr
  is stripped.
- **Stale install script.** If the user's `install.sh` was cached
  by their proxy / corporate filter and points at an old tag, they
  get an old release. → Mitigation: the script reads the *latest*
  release via the GitHub API (`api.github.com/repos/.../releases/latest`)
  rather than embedding a version. Tag-locking is opt-in via
  `DITING_VERSION=v0.10.0 curl ... | bash`.

## Migration Plan

No migration for existing users — they keep using `uv run diting`.
The new install path is purely additive.

**Rollback:** drop the install.sh + release workflow. The new
search-path entry in `find_helper()` is harmless even if no helper
lives there.

## Open Questions

- Cosmetic: do we want a custom domain (`diting.dev` /
  `install.diting.dev`) for the curl URL, or live with the
  `raw.githubusercontent.com` URL? Custom domain is one more thing
  to maintain; the GitHub URL is fine for v1. → Decision deferred
  to release time.
