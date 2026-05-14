# Releasing diting

How to cut a new version that the curl-bash one-liner installs.

> Chinese mirror: [`docs/zh/RELEASE.md`](zh/RELEASE.md). Edits to
> either file MUST land with a matching edit to the other.

## What gets released

Each tagged version produces three release assets on GitHub:

| Asset | Built by | Consumed by |
|---|---|---|
| `diting-X.Y.Z-darwin-arm64.tar.gz` | matrix job `macos-14` | install.sh on Apple Silicon |
| `diting-X.Y.Z-darwin-x86_64.tar.gz` | matrix job `macos-13` | install.sh on Intel |
| `SHASUMS256.txt` | `shasums` job after both matrix builds | install.sh SHA verification |

Each tarball contains a PyInstaller-frozen `diting` binary plus a
copy of the Swift helper bundle (`diting-tianer.app`). Layout:

```
diting-X.Y.Z/
├── bin/diting             # relative symlink → libexec/diting/diting
├── libexec/diting/        # PyInstaller --onedir output
│   ├── diting
│   └── _internal/
└── share/diting-tianer.app/
```

## Cutting a release

1. **Bump the version.** Edit `pyproject.toml` `version = "X.Y.Z"`
   and `uv.lock` (run `uv sync` to refresh). Commit on `main` —
   per the v0.9.0 CHANGELOG policy the release notes are derived
   from the OpenSpec archive at release time, not per-PR.

2. **Tag.**
   ```bash
   git tag -a vX.Y.Z -m "release X.Y.Z"
   git push origin vX.Y.Z
   ```
   The tag push triggers `.github/workflows/release.yml`.

3. **Watch the workflow.** Both matrix jobs (`macos-14` and
   `macos-13`) build the helper, freeze the Python binary, run
   `scripts/package_release.sh`, and upload the tarball + `.sha256`
   sidecar to the release. The `shasums` job runs after both, pulls
   the tarballs back down via `gh release download`, computes
   `SHASUMS256.txt`, and uploads it as a sibling asset.

4. **Smoke-test the install.** On a clean macOS account (or a Mac
   without the source tree), run:
   ```bash
   DITING_VERSION=vX.Y.Z curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
   diting --help
   diting
   ```
   First launch should prompt for Location Services and Bluetooth.

5. **Update the GitHub Release notes** (web UI). Pull bullets from
   the merged OpenSpec proposals under
   `openspec/changes/archive/<since-last-tag>/`. Group as
   Added / Changed / Fixed / Removed.

## Manual / dry-run builds

To verify the frozen-binary build without cutting a real tag,
trigger the workflow manually via `workflow_dispatch`:

- Actions tab → **release** → **Run workflow**
- Set `version` to e.g. `v0.10.0-rc1`
- Tarballs upload as workflow artefacts (NOT release assets) so
  you can inspect them in isolation.

Local arm64-only dry-run:

```bash
uv sync --group release
bash scripts/package_release.sh 0.10.0-rc1
# produces dist/diting-0.10.0-rc1-darwin-arm64.tar.gz
```

## Troubleshooting

- **PyInstaller misses a pyobjc framework.** Add another
  `--collect-all pyobjc_framework_<Name>` line to
  `scripts/build_frozen.py`. The frozen binary will fail to import
  the missing framework at first run if a `--collect-all` is
  absent.

- **Helper bundle Gatekeeper warning persists** after install.sh.
  Confirm `xattr -dr com.apple.quarantine` ran successfully (you
  can re-run `xattr` manually on the installed bundle). Long-term
  fix is Phase 3 of the install plan: Apple Developer signing +
  notarization. Until then the warning fires only once per
  cdhash — re-installing the same release doesn't re-trigger it.

- **`macos-13` runner deprecation.** GitHub will eventually retire
  the Intel hosted runners. When that happens we either move
  x86_64 builds to whatever the latest x86_64 runner is, or drop
  x86_64 (Apple Silicon adoption is >70% of new Macs as of 2026).

- **Upgrade users get re-prompted for Location and Bluetooth after a
  release.** Expected when the helper bundle's cdhash changes —
  macOS TCC keys grants by cdhash. The release notes should call this
  out explicitly when the bundle gains a new file (e.g. v1.0.x
  shipped `AppIcon.icns` for the first time, bumping the cdhash).
  Future installs of the same release at the same path retain grants.

- **`diting` (installed) hangs at "需要以下权限：定位服务" while
  `uv run diting` works.** This is the macOS 26 TCC-vs-LaunchServices
  asymmetry — pinned by the v1.0.7 fix. If you regress it (e.g. by
  simplifying the helper's `scan` subcommand back to a single
  direct-exec subprocess), the symptom returns. Recipe to verify the
  fix is intact:
  ```bash
  rm -rf ~/Library/Application\ Support/diting/diting-tianer.app
  cp -R helper/diting-tianer.app ~/Library/Application\ Support/diting/diting-tianer.app
  pkill -f diting-tianer; sleep 10
  ~/Library/Application\ Support/diting/diting-tianer.app/Contents/MacOS/diting-tianer scan \
    | python3 -c "import sys,json;n=json.load(sys.stdin)['networks'];print(f'with_bssid={sum(1 for r in n if r.get(\"bssid\"))}')"
  ```
  Must print `with_bssid=>0`. If it prints `with_bssid=0`, the
  LaunchServices outer/inner split in
  `helper/Sources/diting-tianer/main.swift:runScanAndDumpJSON` has
  been broken. See the function's leading comment for the full
  background — direct-exec subprocesses don't inherit the bundle's
  Location TCC grant on macOS 26, so the helper has to re-launch
  itself via `/usr/bin/open` to be LaunchServices-attributed.
