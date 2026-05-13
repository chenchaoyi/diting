## Why

The only way to install diting today is to clone the repo, install
`uv`, and run `uv sync` plus `make helper`. That gates the audience
to Python developers who already have `uv` (or are willing to install
it) and Xcode Command Line Tools (for the Swift helper build). For
a tool that's positioned as a TUI for people who want to *use* their
Mac's RF / BLE / Wi-Fi data, that install ceiling is too high — the
typical user shouldn't have to set up a Python build environment to
look at their Wi-Fi scan list.

The lift: a one-line installer that drops both the CLI and the
helper bundle in place, no Python toolchain on the user's machine.

## What Changes

- **One-line install** modelled on Claude Code's installer:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
  ```
  Detects arch, downloads the matching tarball from GitHub Releases,
  verifies SHA256, extracts to `~/.local/share/diting/`, symlinks
  `~/.local/bin/diting` to the frozen binary, copies the helper to
  `~/Library/Application Support/diting/`, and `open`s the helper
  once to trigger the TCC prompts.
- **Per-arch release tarballs** built in GitHub Actions:
  - `diting-X.Y.Z-darwin-arm64.tar.gz` (Apple Silicon)
  - `diting-X.Y.Z-darwin-x86_64.tar.gz` (Intel)

  Each tarball contains:
  ```
  diting-X.Y.Z/
  ├── bin/diting               # PyInstaller-frozen single-file binary
  └── share/diting-tianer.app/ # Swift helper bundle
  ```
- **PyInstaller spec** (`pyinstaller/diting.spec` or `scripts/build_frozen.py`)
  that bundles the Python interpreter + Textual + pyobjc-corewlan +
  pyobjc-systemconfiguration + pyyaml + zeroconf into a single binary.
- **`find_helper()` learns the new path**:
  `~/Library/Application Support/diting/diting-tianer.app` joins the
  existing search list (in-repo dev build → /Applications →
  ~/Applications → new Application Support location). The dev build
  stays first so contributors running `uv run diting` from a checkout
  still pick up their freshly-`make helper`ed bundle.
- **GitHub Actions release workflow** triggered by `v*` tags:
  - matrix job: `macos-14` (arm64) + `macos-13` (x86_64)
  - each runner: build Swift helper, run PyInstaller, tar up the
    artefact, upload to the GitHub Release as a versioned asset
  - emits SHA256s for the install script to verify against
- **`install.sh` committed to the repo root.** Hosted at a stable
  `raw.githubusercontent.com/.../main/install.sh` URL so the
  one-liner doesn't break on tag refs.
- **`uv run diting` keeps working unchanged** for contributors —
  the existing developer workflow (clone + `uv sync` + `make helper`
  + `uv run diting`) is preserved exactly. The frozen binary path is
  strictly additive.

**Out of scope this change** (each is its own future change):
- PyPI distribution (`pipx install diting`)
- Homebrew tap (`brew install diting`)
- Apple Developer signing + notarization (would drop the Gatekeeper
  warning on first launch; without this users see a one-time
  "unidentified developer" dialog the first time the helper runs)

## Capabilities

### New Capabilities

- `installation`: how a non-developer end-user gets diting onto
  their Mac — the one-line installer contract, the tarball layout,
  the install paths under `~/.local/` and `~/Library/Application
  Support/`, the helper-bootstrap step that opens the bundle to
  trigger TCC.

### Modified Capabilities

- `macos-helper`: extend the helper-discovery search list to
  include `~/Library/Application Support/diting/diting-tianer.app`
  (where the one-line installer lands the bundle). Existing search
  paths (DITING_HELPER env override, in-repo dev build,
  /Applications, ~/Applications) all keep working.

## Impact

- **Code**:
  - `src/diting/_helper.py` — add the new search-path entry to
    `find_helper()`.
- **Tooling / infra**:
  - `install.sh` at repo root (new).
  - `pyinstaller/diting.spec` or `scripts/build_frozen.py` (new).
  - `.github/workflows/release.yml` (new) — matrix builds + tarball
    upload triggered on `v*` tag push.
  - PyInstaller added as a dev / release-build dependency. Not a
    runtime dep, so `pyproject.toml`'s `[project.dependencies]`
    stays untouched; goes in `[dependency-groups] release` (or a
    new `[tool.uv.optional-dependencies]` group).
- **Tests**:
  - `tests/test_install.py` — pure-shell-only assertions on the
    installer script (arch detection branch, tarball-URL format,
    PATH-hint emission). Driven via `subprocess.run("bash", input=…)`
    so it doesn't need to actually fetch the network.
  - `tests/test_helper.py` — new case verifying the
    `~/Library/Application Support/diting/` path is in the
    `find_helper()` search list.
  - `tests/TESTING.md` (+ ZH mirror) — new `installation` capability
    section.
- **Docs**:
  - `README.md` + `docs/zh/README.md` — new "Install" section
    leading with the one-liner; the existing "clone + `uv sync`"
    instructions move to a "Contributing / from source" subsection.
  - `docs/workflow.md` (+ ZH mirror) — note that `uv run diting`
    is the developer workflow; `diting` (post-installer) is the
    end-user path.
- **Helper bundle**: no schema change. The helper binary inside
  the tarball is the same `make helper` output, just shipped as a
  release asset.
- **No new runtime dependencies.** PyInstaller is a build-time tool
  only.
