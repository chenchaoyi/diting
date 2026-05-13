#!/usr/bin/env bash
# Build a per-arch release tarball for the curl-bash installer.
#
# Output:
#   dist/diting-<version>-darwin-<arch>.tar.gz
#
# Tarball layout (extracted under ~/.local/share/diting/ by install.sh):
#   diting-<version>/
#   ├── bin/diting             # relative symlink → libexec/diting/diting
#   ├── libexec/diting/        # PyInstaller --onedir output
#   │   ├── diting             # frozen entry binary
#   │   └── _internal/         # Python interpreter + deps
#   └── share/diting-tianer.app/
#       └── Contents/MacOS/diting-tianer
#
# Usage:
#   scripts/package_release.sh [version]
#
# `version` defaults to the value of `version =` in pyproject.toml.
# Arch is taken from `uname -m` (PyInstaller does not cross-compile;
# the GitHub Actions matrix runs this script once per arch on the
# corresponding hosted runner).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---- args / metadata ----

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  VERSION="$(awk -F'"' '/^version = / { print $2 ; exit }' pyproject.toml)"
fi
if [ -z "$VERSION" ]; then
  echo "could not determine version (pass as $1 or set pyproject.toml [project] version)" >&2
  exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64)  ARCH="x86_64" ;;
  *)
    echo "unsupported arch: $ARCH" >&2
    exit 1
    ;;
esac

OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
  echo "this script targets macOS only (uname -s = $OS)" >&2
  exit 1
fi

STAGE_NAME="diting-${VERSION}"
TARBALL="dist/${STAGE_NAME}-darwin-${ARCH}.tar.gz"

echo "==> building release ${STAGE_NAME} for darwin-${ARCH}"

# ---- build helper bundle ----
# The Swift helper rebuilds on every release so the cdhash matches
# what the user will run. Rebuilding here also catches any helper
# regression before we ship.

echo "==> building Swift helper"
( cd helper && ./build.sh )

if [ ! -d helper/diting-tianer.app ]; then
  echo "helper/build.sh did not produce diting-tianer.app" >&2
  exit 2
fi

# ---- build frozen binary ----

echo "==> freezing Python binary with PyInstaller"
python scripts/build_frozen.py

if [ ! -x dist/diting/diting ]; then
  echo "PyInstaller did not produce dist/diting/diting" >&2
  exit 3
fi

# ---- assemble tarball staging dir ----

STAGE_DIR="dist/${STAGE_NAME}"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/bin" "$STAGE_DIR/libexec" "$STAGE_DIR/share"

# PyInstaller --onedir produces a self-contained tree; move the
# whole thing under libexec/diting/ so the entry binary's relative
# _internal/ resolution still works.
cp -R dist/diting "$STAGE_DIR/libexec/diting"

# Symlink the user-visible entry. Relative target so the tarball
# extracts cleanly into any prefix (the symlink doesn't bake in
# /tmp/staging/...).
( cd "$STAGE_DIR/bin" && ln -sf "../libexec/diting/diting" diting )

# Drop the helper bundle in share/. install.sh copies it onward to
# ~/Library/Application Support/diting/ on the user's machine.
cp -R helper/diting-tianer.app "$STAGE_DIR/share/diting-tianer.app"

# ---- produce tarball ----

# Plain `tar -czf`. We do NOT pass `--owner=0 --group=0
# --numeric-owner` here even though it would produce a more
# reproducible archive — those are GNU-tar-only flags and macOS
# ships bsdtar, which rejects them outright (bsdtar accepts a
# different `--uid`/`--gid` syntax that doesn't ride alongside).
# Per-arch tarballs are built fresh on clean hosted runners, so the
# uid/gid baked into the archive header is whatever the runner uses
# (uid 502 in practice). SHA256 verification of the resulting
# tarball is what the install.sh path actually relies on for
# integrity; a deterministic header would be nice-to-have, not
# load-bearing.
echo "==> tarballing into ${TARBALL}"
tar -czf "$TARBALL" -C dist "${STAGE_NAME}"

# SHA256 sidecar so CI can stitch SHASUMS256.txt together across
# matrix jobs without re-hashing.
SHA="$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
echo "${SHA}  $(basename "$TARBALL")" > "${TARBALL}.sha256"

echo ""
echo "built: ${TARBALL}"
echo "sha256: ${SHA}"
echo "size: $(du -h "$TARBALL" | awk '{print $1}')"
