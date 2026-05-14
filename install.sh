#!/usr/bin/env bash
# diting one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
#
# Or to pin a specific version:
#   DITING_VERSION=v0.10.0 curl -fsSL ... | bash
#
# What this script does:
#   1. Confirms host is macOS arm64 or x86_64
#   2. Resolves the target release version (default: latest tag)
#   3. Downloads the matching tarball + SHASUMS256.txt from the
#      GitHub Release, verifies SHA256
#   4. Extracts under ~/.local/share/diting/ (atomic rename swap)
#   5. Symlinks ~/.local/bin/diting → libexec/diting/diting
#   6. Copies the helper bundle to ~/Library/Application Support/diting/,
#      strips quarantine, `open`s once to trigger TCC prompts
#   7. Prints a PATH-update hint if ~/.local/bin isn't on PATH
#
# DITING_INSTALL_TESTONLY=1 short-circuits the download / extract /
# helper-prime / open steps so the test suite can exercise the
# branching logic without touching the network or the user's
# Application Support directory.

set -euo pipefail

REPO_SLUG="${DITING_REPO:-chenchaoyi/diting}"
INSTALL_PREFIX="${HOME}/.local/share/diting"
BIN_DIR="${HOME}/.local/bin"
APP_SUPPORT_DIR="${HOME}/Library/Application Support/diting"
TMP_DIR=""

# Test-only short circuit: when set, every "side-effectful" step
# emits a single descriptive marker line to stdout and returns
# without doing the side effect. The test harness scrapes those
# markers to assert branching coverage.
TESTONLY="${DITING_INSTALL_TESTONLY:-}"

# ---- helpers ----

die() {
  echo "diting install: error: $*" >&2
  exit 1
}

note() {
  echo "diting install: $*"
}

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

# detect_locale prints `zh` if the user's macOS-preferred language
# starts with zh, otherwise `en`. The first-launch helper run has no
# DITING_LANG signal yet (the user hasn't run `diting --lang ...`),
# so the macOS preference is the only locale signal available — and
# the one macOS itself uses to pick the TCC prompt's lproj. Falling
# open to `en` keeps the install path safe when `defaults` errors.
detect_locale() {
  local pref
  pref="$(defaults read -g AppleLanguages 2>/dev/null \
    | tr -d '(),"' \
    | awk 'NF { print $1; exit }')"
  case "$pref" in
    zh*) echo "zh" ;;
    *)   echo "en" ;;
  esac
}

# bundle_locale_tag maps a DITING_LANG value to the matching macOS
# bundle locale identifier. The Cocoa -AppleLanguages launch arg
# uses these tags to pick which Resources/<tag>.lproj/ to load.
bundle_locale_tag() {
  case "$1" in
    zh) echo "zh-Hans" ;;
    *)  echo "en" ;;
  esac
}

# ---- platform check ----

OS="$(uname -s)"
ARCH_RAW="$(uname -m)"

if [ "$OS" != "Darwin" ]; then
  die "diting is macOS-only (uname -s = $OS)"
fi

case "$ARCH_RAW" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64)  ARCH="x86_64" ;;
  *)
    die "unsupported arch: $ARCH_RAW (diting ships arm64 + x86_64 builds only)"
    ;;
esac

note "host detected: darwin-${ARCH}"

# ---- resolve version ----

if [ -n "${DITING_VERSION:-}" ]; then
  VERSION="$DITING_VERSION"
  note "pinned version: $VERSION (DITING_VERSION env override)"
else
  if [ -n "$TESTONLY" ]; then
    VERSION="v0.0.0-testonly"
  else
    VERSION="$(
      curl -fsSL "https://api.github.com/repos/${REPO_SLUG}/releases/latest" \
      | awk -F'"' '/"tag_name"/ { print $4; exit }'
    )"
  fi
  if [ -z "$VERSION" ]; then
    die "could not resolve latest release; set DITING_VERSION to override"
  fi
  note "latest release: $VERSION"
fi

# Strip the leading "v" for filenames: tag `v0.10.0` → tarball
# `diting-0.10.0-darwin-arm64.tar.gz`.
NUM_VERSION="${VERSION#v}"
TARBALL_NAME="diting-${NUM_VERSION}-darwin-${ARCH}.tar.gz"
TARBALL_URL="https://github.com/${REPO_SLUG}/releases/download/${VERSION}/${TARBALL_NAME}"
SHASUMS_URL="https://github.com/${REPO_SLUG}/releases/download/${VERSION}/SHASUMS256.txt"

# ---- download + verify ----

if [ -n "$TESTONLY" ]; then
  note "TESTONLY: would download $TARBALL_URL"
  note "TESTONLY: would verify against $SHASUMS_URL"
else
  TMP_DIR="$(mktemp -d -t diting-install.XXXXXX)"
  note "downloading $TARBALL_NAME"
  curl -fsSL --output "${TMP_DIR}/${TARBALL_NAME}" "$TARBALL_URL" \
    || die "tarball download failed: $TARBALL_URL"
  curl -fsSL --output "${TMP_DIR}/SHASUMS256.txt" "$SHASUMS_URL" \
    || die "SHASUMS256.txt download failed: $SHASUMS_URL"
  EXPECTED_SHA="$(
    awk -v name="$TARBALL_NAME" '$2 == name { print $1 }' \
      "${TMP_DIR}/SHASUMS256.txt"
  )"
  if [ -z "$EXPECTED_SHA" ]; then
    die "SHASUMS256.txt missing entry for $TARBALL_NAME"
  fi
  ACTUAL_SHA="$(shasum -a 256 "${TMP_DIR}/${TARBALL_NAME}" | awk '{print $1}')"
  if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    die "sha256 mismatch on $TARBALL_NAME (expected $EXPECTED_SHA, got $ACTUAL_SHA)"
  fi
  note "sha256 verified: $ACTUAL_SHA"
fi

# ---- extract ----

if [ -n "$TESTONLY" ]; then
  note "TESTONLY: would extract to ${INSTALL_PREFIX}"
  note "TESTONLY: would symlink ${BIN_DIR}/diting"
else
  mkdir -p "$(dirname "$INSTALL_PREFIX")" "$BIN_DIR"
  # Atomic-ish swap: extract into a sibling .new/, validate, then
  # move the old install aside, rename .new/ into place. If anything
  # blows up mid-way, we leave the old install intact rather than
  # half-clobbering the user's working setup.
  STAGE_DIR="${INSTALL_PREFIX}.new"
  rm -rf "$STAGE_DIR"
  mkdir -p "$STAGE_DIR"
  tar -xzf "${TMP_DIR}/${TARBALL_NAME}" -C "$STAGE_DIR" --strip-components=1
  if [ ! -x "${STAGE_DIR}/libexec/diting/diting" ]; then
    die "extracted tarball missing libexec/diting/diting"
  fi
  if [ -d "$INSTALL_PREFIX" ]; then
    rm -rf "${INSTALL_PREFIX}.old"
    mv "$INSTALL_PREFIX" "${INSTALL_PREFIX}.old"
  fi
  mv "$STAGE_DIR" "$INSTALL_PREFIX"
  rm -rf "${INSTALL_PREFIX}.old"
  ln -snf "${INSTALL_PREFIX}/libexec/diting/diting" "${BIN_DIR}/diting"
  note "installed to ${INSTALL_PREFIX}"
  note "symlinked ${BIN_DIR}/diting"
fi

# ---- prime helper bundle ----

DITING_LOCALE="$(detect_locale)"
DITING_LOCALE_TAG="$(bundle_locale_tag "$DITING_LOCALE")"

if [ -n "$TESTONLY" ]; then
  note "TESTONLY: detected locale=${DITING_LOCALE} (tag=${DITING_LOCALE_TAG})"
  note "TESTONLY: would copy helper to ${APP_SUPPORT_DIR}"
  note "TESTONLY: would xattr -dr com.apple.quarantine"
  note "TESTONLY: would open --env DITING_LANG=${DITING_LOCALE} --args -AppleLanguages (${DITING_LOCALE_TAG})"
else
  mkdir -p "$APP_SUPPORT_DIR"
  SRC_BUNDLE="${INSTALL_PREFIX}/share/diting-tianer.app"
  DST_BUNDLE="${APP_SUPPORT_DIR}/diting-tianer.app"
  if [ ! -d "$SRC_BUNDLE" ]; then
    die "extracted tarball missing share/diting-tianer.app"
  fi
  rm -rf "$DST_BUNDLE"
  cp -R "$SRC_BUNDLE" "$DST_BUNDLE"
  # Strip the quarantine xattr macOS attaches to anything that came
  # in via curl. Without this Gatekeeper would block first launch.
  # Same trick Homebrew uses for unsigned casks.
  xattr -dr com.apple.quarantine "$DST_BUNDLE" 2>/dev/null || true
  # Open the bundle foreground (no -g) so macOS surfaces the TCC
  # prompts ON TOP and the helper's status window stays visible.
  # `--env DITING_LANG=...` makes the helper's Swift UI render in
  # the matching language; `--args -AppleLanguages (...)` forces
  # Cocoa's NSUserDefaults for the launched process to pick the
  # matching .lproj so the macOS TCC prompt headers + bodies use
  # the same locale. Without -AppleLanguages, Bundle.preferred-
  # Localizations and Locale.preferredLanguages can disagree under
  # LaunchServices and the user sees a mixed-language stack.
  open --env "DITING_LANG=${DITING_LOCALE}" \
       "$DST_BUNDLE" \
       --args -AppleLanguages "(${DITING_LOCALE_TAG})" \
       2>/dev/null || true
  note "helper bundle primed at ${DST_BUNDLE}"
  if [ "$DITING_LOCALE" = "zh" ]; then
    note "macOS 会依次弹出 3 个权限请求（定位 → 蓝牙 → 通知）— 请逐个点击 Allow"
    note "helper 窗口在第 3 个授权完成后约 4 秒自动关闭"
    note "升级用户：bundle cdhash 已变更，定位与蓝牙会重新询问一次"
  else
    note "macOS will prompt for Location → Bluetooth → Notifications in order — click Allow on each"
    note "the helper window auto-closes ~4s after the third grant lands"
    note "upgrading from v1.0.x: the bundle's cdhash changed, so Location + Bluetooth re-prompt once"
  fi
fi

# ---- PATH hint ----

case ":$PATH:" in
  *":${BIN_DIR}:"*)
    note "diting is on your PATH — run \`diting\`"
    ;;
  *)
    # Detect the user's interactive shell to print the right hint.
    SHELL_NAME="$(basename "${SHELL:-/bin/zsh}")"
    case "$SHELL_NAME" in
      zsh)
        echo "Add to ~/.zshrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
      bash)
        echo "Add to ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
      fish)
        echo "Add to ~/.config/fish/config.fish:  fish_add_path \$HOME/.local/bin"
        ;;
      *)
        echo "Add ${BIN_DIR} to your PATH (shell: ${SHELL_NAME})"
        ;;
    esac
    ;;
esac
