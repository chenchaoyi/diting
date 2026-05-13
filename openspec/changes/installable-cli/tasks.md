## 1. Test plan first (per SDD discipline)

- [x] 1.1 Add a new `installation` capability section to `tests/TESTING.md` covering: arch detection branch, GitHub-Release-URL format, SHA256 verification path, PATH-hint emission, helper-bundle landing under Application Support, `xattr -dr` quarantine strip, refusal on non-Darwin
- [x] 1.2 Mirror the new section in `docs/zh/TESTING.md`
- [x] 1.3 Add a new row to the `macos-helper` section in both `tests/TESTING.md` and `docs/zh/TESTING.md` capturing the new `find_helper()` search-path entry

## 2. Update helper discovery (smallest behaviour change first)

- [x] 2.1 Add `~/Library/Application Support/diting/diting-tianer.app` to the `find_helper()` candidate list in `src/diting/_helper.py` AFTER the in-repo dev build and `/Applications` / `~/Applications` (last in the search order so a dev build always shadows the installer copy)
- [x] 2.2 Update the module docstring at the top of `_helper.py` to list the new search location
- [x] 2.3 New tests in `tests/test_helper.py`: `test_find_helper_picks_up_application_support_bundle` + `test_find_helper_repo_dev_build_shadows_application_support` plus a `_redirect_search_locations` helper that steers the resolver away from the real repo / real `~`

## 3. PyInstaller build spec

- [x] 3.1 Added `pyinstaller` to `[dependency-groups]` (new `release` group) in `pyproject.toml`. NOT in runtime `[project.dependencies]`
- [x] 3.2 Wrote `scripts/build_frozen.py` invoking PyInstaller `--onedir` with `--collect-all` for `pyobjc_core` / `pyobjc_framework_Cocoa` / `pyobjc_framework_CoreWLAN` / `pyobjc_framework_SystemConfiguration` / `textual` / `rich` / `zeroconf` / `ifaddr`; ships `src/diting/data/` as `--add-data`; entry-point binary named `diting`
- [ ] 3.3 Local-verify the frozen binary boots: `dist/diting/diting --help` exits 0 with the usage text. Manual smoke against the dev machine on arm64 — no CI test yet (deferred until release-flow dry-run; non-blocking for the PR)
- [x] 3.4 Local build steps documented inline in `scripts/build_frozen.py` + `scripts/package_release.sh` docstrings; full release runbook lives in `docs/RELEASE.md` (Task 6.4)

## 4. Tarball + install script

- [x] 4.1 Wrote `scripts/package_release.sh` that builds the helper via `helper/build.sh`, runs `build_frozen.py`, assembles `diting-X.Y.Z/{bin,libexec,share}` layout (bin/diting → libexec/diting/diting relative symlink), and produces `diting-X.Y.Z-darwin-{arch}.tar.gz` + `.sha256` sidecar
- [x] 4.2 Wrote `install.sh` at the repo root. `set -euo pipefail`, detects arch via `uname -m`, refuses on non-Darwin, fetches latest release via `api.github.com`, honours `DITING_VERSION` override, downloads tarball + `SHASUMS256.txt`, verifies SHA256, extracts to `~/.local/share/diting/` with atomic .new/.old rename swap, symlinks `~/.local/bin/diting`, copies helper to `~/Library/Application Support/diting/`, strips quarantine xattr, `open -g`s the helper to prime TCC, prints PATH hint when applicable
- [x] 4.3 Added `tests/test_install.py` (11 tests) driving the script via `subprocess.run(["bash", "install.sh"], ...)` under `DITING_INSTALL_TESTONLY=1` short-circuit; covers arch detection (Darwin / Linux / sparc64), version override, SHA-verify branch reach, helper-prime branch reach, PATH-hint emission for zsh / bash / fish + the silent already-on-PATH case

## 5. GitHub Actions release workflow

- [x] 5.1 New `.github/workflows/release.yml` triggered on `push: tags: ['v*']`. Matrix: `{os: macos-14, arch: arm64}` and `{os: macos-13, arch: x86_64}`. Each job: checkout, install uv, install Python 3.11, sync `--group release` (PyInstaller), build Swift helper via `helper/build.sh`, run `scripts/package_release.sh`, upload `diting-X.Y.Z-darwin-{arch}.tar.gz` + `.sha256` as release assets via `softprops/action-gh-release@v2`
- [x] 5.2 Separate `shasums` job (needs `build`) downloads both arch tarballs from the release via `gh release download`, runs `sha256sum *.tar.gz`, uploads the aggregated `SHASUMS256.txt` as a sibling asset
- [x] 5.3 `workflow_dispatch` trigger present with a `version` input; dispatch runs upload tarballs as workflow artifacts (not release assets) for manual inspection
- [ ] 5.4 Verify CI green via a test tag push (`v0.10.0-rc1` or similar) — confirm both tarballs upload and SHASUMS256.txt is correct (deferred: validating an Actions workflow before merge would require pushing to a fork or dry-running; flag for the post-merge `v0.10.0` release cut to validate end-to-end)

## 6. Docs

- [x] 6.1 README.md "Quick start" leads with the curl one-liner; the `uv sync` + `make helper` flow moves under a new "From source (for contributors)" subsection. Notes that the two paths coexist
- [x] 6.2 Mirrored in `docs/zh/README.md`
- [x] 6.3 `docs/workflow.md` (+ `docs/zh/workflow.md` mirror) — new "Developer flow vs end-user install" section pointing at the curl one-liner and `docs/RELEASE.md`
- [x] 6.4 `docs/RELEASE.md` (+ `docs/zh/RELEASE.md`) — release-cutting runbook: version bump, tag, watch workflow, manual smoke, GitHub Release notes; dispatch dry-run instructions; troubleshooting (PyInstaller hooks, Gatekeeper, macos-13 retirement)

## 7. Validation gates before PR

- [x] 7.1 `uv run pytest` — **499 passed** (13 new install tests + 2 new helper-search tests, 0 failures)
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression --check` — **13 scenarios, 29 asserts, 0 failed**
- [x] 7.3 `openspec validate --specs --strict` — **19/19 passed**
- [x] 7.4 `openspec validate installable-cli --strict` — **change validates**
- [x] 7.5 Local manual: `DITING_INSTALL_TESTONLY=1 DITING_VERSION=v0.10.0 bash install.sh` exits 0 and emits the expected sequence of TESTONLY markers (download, SHA verify, extract, symlink, helper copy, xattr strip, `open` prime, PATH hint)

## 8. Post-merge release cut (NOT part of this PR)

- [ ] 8.1 After merge, cut `v0.10.0` tag on main → triggers the release workflow → tarballs land on the GitHub Release
- [ ] 8.2 Manual install on a clean machine (or a fresh user account) to validate end-to-end the one-line flow
- [ ] 8.3 Update README badges if needed (download count, etc.) — separate chore PR
