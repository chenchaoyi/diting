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

# ---- output tier detection ----
#
# `install.sh` renders via one of three tiers depending on the runtime
# environment. TIER LOG is byte-identical to the pre-v1.8.0 output and
# is what every non-TTY consumer sees (Homebrew cask shell, CI, pipes,
# `tests/test_install.py`). TIER PLAIN / TIER FULL polish the output
# for interactive macOS terminals — same script behaviour, different
# rendering. See `openspec/specs/installation/spec.md` for the full
# selection rules.

# Tier detection runs at the top level so `[ -t 1 ]` queries the
# script's actual stdout — NOT the pipe of a command substitution.
# We assign TIER directly rather than capturing via `$(detect_tier)`
# because the `$()` form redirects fd 1 inside the subshell, which
# makes `[ -t 1 ]` always report non-TTY (silently dropping every
# interactive run to TIER LOG).

# 1. Explicit user override always wins. Documented escape hatch for
#    Homebrew formula maintainers / downstream consumers who want the
#    machine-grep-friendly LOG format on an interactive terminal.
case "${DITING_INSTALL_FORMAT:-}" in
  log|plain|full)
    TIER="${DITING_INSTALL_FORMAT}"
    ;;
  *)
    if ! [ -t 1 ]; then
      # 2. Non-TTY: pipes, cron, CI runners, Homebrew cask shell.
      TIER="log"
    elif [ -n "${NO_COLOR:-}" ]; then
      # 3. NO_COLOR convention (https://no-color.org/) — any non-empty
      #    value disables color, forcing TIER PLAIN even on a TTY.
      TIER="plain"
    else
      case "${TERM:-}" in
        dumb|"")
          # 4. Dumb / unset terminals can't render ANSI cleanly.
          TIER="plain"
          ;;
        *)
          # 5+6. UTF-8 detection: LC_ALL > LC_CTYPE > LANG. Default
          #     macOS shells set `en_US.UTF-8`; explicit `LC_ALL=C`
          #     sessions drop to PLAIN.
          _DITING_LOCALE="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
          case "${_DITING_LOCALE}" in
            *UTF-8*|*UTF8*|*utf-8*|*utf8*) TIER="full" ;;
            *)                              TIER="plain" ;;
          esac
          unset _DITING_LOCALE
          ;;
      esac
    fi
    ;;
esac

# ANSI escape constants. Only populated in TIER FULL; empty strings
# elsewhere so the renderers can interpolate them unconditionally
# without leaking escape bytes into PLAIN / LOG output. 24-bit color
# (the `\033[38;2;R;G;B;m` form) is universally supported by every
# modern macOS terminal — iTerm2, Terminal.app, Alacritty, kitty,
# WezTerm — which is the only platform diting installs onto.
if [ "$TIER" = "full" ]; then
  ORANGE="$(printf '\033[38;2;254;166;43m')"
  GREEN="$(printf '\033[32m')"
  RED="$(printf '\033[31m')"
  DIM="$(printf '\033[2m')"
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  ORANGE="" GREEN="" RED="" DIM="" BOLD="" RESET=""
fi

# MIRROR resolution happens later, AFTER the helpers section,
# because the `die()` it calls on invalid values is defined there.
# Kept near the top conceptually — see the `---- mirror resolution
# ----` block below the helpers.

# ---- helpers ----

die() {
  echo "diting install: error: $*" >&2
  exit 1
}

# die_with_marker prints a tier-appropriate failure marker for the
# named step before delegating to die(). Step-bound failure sites use
# this; non-step failures (platform check, version resolve) keep
# calling die() directly because they have no step number.
die_with_marker() {
  local step_n="$1"
  shift
  case "$TIER" in
    full)
      printf '%s[%s/6] %-10s%s %s%b%s\n' \
        "" "$step_n" "FAIL" "" "${RED}" "✗${RESET}" "" >&2
      ;;
    plain)
      printf '[%s/6] %-10s [FAIL]\n' "$step_n" "FAIL" >&2
      ;;
    log)
      : # die() will emit the existing prefix line; no extra marker
      ;;
  esac
  die "$*"
}

note() {
  echo "diting install: $*"
}

# validate_download — return 0 iff `<file>` is a plausible `<kind>`,
# guarding against a proxy that answers HTTP 200 with an HTML error /
# landing page (the failure mode that killed the dead ghproxy.com).
#   shasums — must yield a 64-hex hash for $TARBALL_NAME (rejects HTML)
#   tarball — must be a valid gzip stream
validate_download() {
  local file="$1" kind="$2"
  [ -s "$file" ] || return 1
  case "$kind" in
    shasums)
      awk -v name="$TARBALL_NAME" \
        '$2 == name && $1 ~ /^[0-9a-fA-F]{64}$/ { ok=1 } END { exit ok?0:1 }' \
        "$file"
      ;;
    tarball)
      gzip -t "$file" 2>/dev/null
      ;;
    *) return 0 ;;
  esac
}

# build_candidates — emit "src url" lines (one per attempt) for `<url>`
# in priority order, per the resolved MIRROR mode. `src` is `github`
# or a proxy prefix (sans trailing slash). When `force_github_first`
# is 1, GitHub-direct is prepended even in modes that otherwise skip
# it (used for SHASUMS so its trust stays anchored on GitHub).
build_candidates() {
  local url="$1" force_gh="$2" p
  if [ "$MIRROR" = github ] || [ "$MIRROR" = auto ] || \
     [ "$MIRROR" = custom ] || [ "$force_gh" = 1 ]; then
    printf 'github %s\n' "$url"
  fi
  if [ "$MIRROR" != github ]; then
    printf '%s\n' "$MIRROR_PROXIES" | while IFS= read -r p; do
      [ -z "$p" ] && continue
      printf '%s %s%s\n' "${p%/}" "$p" "$url"
    done
  fi
}

# download_with_fallback downloads `<url>` to `<dest>`, walking the
# candidate chain and accepting the first attempt that BOTH transfers
# AND passes the `<kind>` content check. The third arg names a global
# that receives the winning `src` (`github` or a proxy prefix), read
# by the completion-notice flow. Optional 5th arg forces GitHub-first.
#
# curl's `--max-time 20` is the per-attempt wall-clock budget: the
# slowest healthy international GitHub-asset download is ~5 s; the CN
# failure mode completes the handshake then stalls, so 20 s fails fast
# on broken routes. `eval` is the pre-bash-4.3 indirection pattern
# (macOS ships bash 3.2, no `declare -n`). Returns 0 on the first
# valid source, 1 when the whole chain is exhausted.
download_with_fallback() {
  local url="$1" dest="$2" used_var="$3" kind="${4:-plain}" force_gh="${5:-0}"
  local src curl_url
  while IFS=' ' read -r src curl_url; do
    [ -z "$curl_url" ] && continue
    if [ "$src" != github ]; then
      note "$(mirror_fallback_notice "$src")"
    fi
    if curl --max-time 20 -fsSL --output "$dest" "$curl_url" 2>/dev/null \
       && validate_download "$dest" "$kind"; then
      eval "${used_var}=\"\$src\""
      return 0
    fi
    rm -f "$dest"
  done <<EOF
$(build_candidates "$url" "$force_gh")
EOF
  return 1
}

# _mirror_host — strip scheme + path from a proxy prefix to its bare
# host, for human-readable notices (`https://ghfast.top/` → `ghfast.top`).
_mirror_host() {
  local h="${1#http://}"; h="${h#https://}"; echo "${h%%/*}"
}

# mirror_fallback_notice / mirror_completion_notice — locale-aware
# copy. `detect_locale` derives EN vs ZH from `defaults read -g
# AppleLanguages`; cached in MIRROR_NOTICE_LOCALE so it runs once.
# mirror_fallback_notice <proxy-prefix> fires per proxy attempt and
# names the host being tried.
mirror_fallback_notice() {
  local host; host="$(_mirror_host "$1")"
  if [ -z "${MIRROR_NOTICE_LOCALE:-}" ]; then
    MIRROR_NOTICE_LOCALE="$(detect_locale)"
  fi
  case "$MIRROR_NOTICE_LOCALE" in
    zh) echo "GitHub 下载失败（网络可能受限）；切换到 ${host} 镜像重试..." ;;
    *)  echo "GitHub download failed (likely CN network); retrying via ${host} mirror..." ;;
  esac
}

# mirror_completion_notice <tarball_src> <shasums_src> — honest about
# the trust anchor: when SHASUMS came from GitHub-direct the anchor is
# GitHub even if the tarball was mirrored; when SHASUMS itself was
# proxied, that proxy is the anchor (SHA256 still verified against it).
mirror_completion_notice() {
  local tsrc="$1" ssrc="$2" thost shost
  thost="$(_mirror_host "$tsrc")"; shost="$(_mirror_host "$ssrc")"
  if [ -z "${MIRROR_NOTICE_LOCALE:-}" ]; then
    MIRROR_NOTICE_LOCALE="$(detect_locale)"
  fi
  if [ "$ssrc" = github ]; then
    case "$MIRROR_NOTICE_LOCALE" in
      zh) echo "tarball 通过 ${thost} 镜像下载；SHASUMS 从 GitHub 直连，信任锚定于 GitHub" ;;
      *)  echo "tarball fetched via ${thost} mirror; SHASUMS direct from GitHub — trust anchored on GitHub" ;;
    esac
  else
    case "$MIRROR_NOTICE_LOCALE" in
      zh) echo "SHASUMS 通过 ${shost} 镜像下载；信任锚定于该镜像（SHA256 仍校验）" ;;
      *)  echo "SHASUMS fetched via ${shost} mirror; trust anchored on that mirror (SHA256 still verified)" ;;
    esac
  fi
}

# step emits a numbered progress row in TIER FULL / TIER PLAIN, or
# the existing `diting install: <log_text>` line in TIER LOG. Keeps
# every existing test (which captures non-TTY → LOG) byte-equal.
#
# Usage: step <N> <label> <value> <log_text>
#
# When `log_text` is empty, the LOG branch SHALL emit nothing — used
# by TESTONLY blocks where the corresponding `note "TESTONLY: would
# …"` line already covers the LOG-tier output and emitting both
# would break the byte-identical contract.
step() {
  local n="$1" label="$2" value="$3" log_text="$4"
  case "$TIER" in
    full)
      printf '%b[%d/6]%b %-10s %s %b✓%b\n' \
        "${DIM}" "$n" "${RESET}" "$label" "$value" "${GREEN}" "${RESET}"
      ;;
    plain)
      printf '[%d/6] %-10s %s [OK]\n' "$n" "$label" "$value"
      ;;
    log)
      # Empty log_text means the caller has already covered LOG-tier
      # output (typically a `note "TESTONLY: …"` line right after).
      # Use `if` (not `&&`) so an empty value doesn't trip `set -e`.
      if [ -n "$log_text" ]; then note "$log_text"; fi
      ;;
  esac
}

# step_continuation prints an indented continuation line under the
# preceding step row (used for the helper-prime guidance lines). In
# LOG tier it delegates to `note` so existing log shape is preserved.
step_continuation() {
  local text="$1"
  case "$TIER" in
    full|plain)
      printf '       %b%s%b\n' "${DIM}" "$text" "${RESET}"
      ;;
    log)
      note "$text"
      ;;
  esac
}

# log_only_note prints a `note` line only in TIER LOG. Used where the
# old script had two `note` calls for one logical step — the second
# call's content moves into the summary block in FULL / PLAIN.
log_only_note() {
  if [ "$TIER" = "log" ]; then note "$1"; fi
}

# print_header renders the pixel-beast brand mark + tagline at the
# very top of the install. TIER FULL only — TIER PLAIN drops the
# logo to keep ASCII purity; TIER LOG keeps the old prefix-only feel.
print_header() {
  [ "$TIER" = "full" ] || return 0
  printf '\n'
  # Three-row Unicode half-block art, byte-equal to _LOGO_MARK_ART
  # in src/diting/tui.py and the canonical splash frame.
  printf '  %s█%s\n'         "${ORANGE}" "${RESET}"
  printf '  %s█▀██████▄%s\n'  "${ORANGE}" "${RESET}"
  printf '  %s▀██▀▀▀▀██%s\n'  "${ORANGE}" "${RESET}"
  printf '\n'
  printf '  %sditing installer%s · %s\n' "${BOLD}" "${RESET}" "${VERSION:-(version pending)}"
  printf '\n'
}

# print_summary renders the end-of-install "Installed." block in
# TIER FULL / TIER PLAIN. No-op in TIER LOG — the existing PATH-hint
# tail keeps its role as the closer there.
print_summary() {
  case "$TIER" in
    full|plain) ;;
    log) return 0 ;;
  esac
  printf '\n'
  printf '  %sInstalled.%s\n' "${BOLD}" "${RESET}"
  printf '    %-8s %s\n' "binary" "${BIN_DIR}/diting"
  if [ -z "$TESTONLY" ] && [ -n "${DST_BUNDLE:-}" ]; then
    printf '    %-8s %s\n' "bundle" "${DST_BUNDLE}"
  fi
  # `next` line varies by PATH state — wired in the PATH-hint block
  # at the script tail, which calls back into this helper via the
  # SUMMARY_NEXT global.
  if [ -n "${SUMMARY_NEXT:-}" ]; then
    printf '    %-8s %s\n' "next" "${SUMMARY_NEXT}"
  fi
  printf '\n'
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

# ---- mirror resolution ----
#
# DITING_INSTALL_MIRROR controls the download ladder for the tarball
# and SHASUMS256.txt. GitHub Releases stays the trust anchor; the
# fallback is for CN networks where direct GitHub asset downloads
# stall on `objects.githubusercontent.com`.
#
#   auto    — GitHub first; on failure walk the live proxy chain.
#             SHASUMS is always tried GitHub-direct first. Default.
#   github  — GitHub only; no proxies.
#   ghproxy — back-compat keyword: skip the GitHub-first attempt for
#             the tarball and go straight to the proxy chain (CN users
#             who know GitHub is unreachable). SHASUMS still tries
#             GitHub-direct first.
#   <url>   — an http(s):// custom/self-hosted proxy prefix, used as
#             the sole proxy in the `<prefix><github-url>` convention
#             (GitHub-first, then this proxy).
#
# `ghproxy.com` was removed — it was discontinued and now answers with
# an HTML landing page, which the content validator would reject anyway.
# The chain is kept in one place so it can be tuned without touching the
# download logic.
#
# Invalid values abort before any download work — the install must not
# silently fall back when the user typed an unsupported mirror.
_MIRROR_PROXY_CHAIN='https://ghfast.top/
https://gh-proxy.com/
https://ghproxy.net/'

case "${DITING_INSTALL_MIRROR:-auto}" in
  auto)    MIRROR=auto;   MIRROR_PROXIES="$_MIRROR_PROXY_CHAIN" ;;
  github)  MIRROR=github; MIRROR_PROXIES="" ;;
  ghproxy) MIRROR=ghproxy; MIRROR_PROXIES="$_MIRROR_PROXY_CHAIN" ;;
  http://*|https://*)
    MIRROR=custom
    MIRROR_PROXIES="${DITING_INSTALL_MIRROR%/}/"
    ;;
  *)
    die "unknown DITING_INSTALL_MIRROR value: ${DITING_INSTALL_MIRROR} (expected auto|github|ghproxy|<http(s)://proxy/>)"
    ;;
esac

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

# ---- resolve version (must happen before print_header so the
# tagline can show which version we're installing) ----

# resolve_latest_version — print the latest release tag, or nothing.
# The GitHub API is the fast path; on networks that reset GitHub TLS
# (the same ones the asset mirror chain exists for) it fails, so fall
# back to following the `releases/latest` redirect through the same
# candidate chain — proxies relay the redirect, and the final URL ends
# in `/tag/<version>`. Only a version-shaped tag is accepted, so a
# proxy answering with a landing page can't poison the resolve. Trust
# is unchanged either way: resolution only picks WHICH tag to fetch;
# the tarball is still SHA256-verified against a GitHub-first SHASUMS.
resolve_latest_version() {
  local v src curl_url final
  v="$(
    curl --max-time 10 -fsSL \
      "https://api.github.com/repos/${REPO_SLUG}/releases/latest" \
      2>/dev/null \
    | awk -F'"' '/"tag_name"/ { print $4; exit }'
  )" || true
  if [ -n "$v" ]; then
    printf '%s\n' "$v"
    return 0
  fi
  while IFS=' ' read -r src curl_url; do
    [ -z "$curl_url" ] && continue
    if [ "$src" != github ]; then
      note "$(mirror_fallback_notice "$src")" >&2
    fi
    final="$(
      curl --max-time 20 -fsSL -o /dev/null -w '%{url_effective}' \
        "$curl_url" 2>/dev/null
    )" || continue
    case "$final" in
      */tag/*)
        v="${final##*/tag/}"
        # Version-shape gate: optional `v` + leading digit. Rejects a
        # proxy that 200s a landing page at some non-release URL.
        case "$v" in
          v[0-9]*|[0-9]*)
            printf '%s\n' "$v"
            return 0
            ;;
        esac
        ;;
    esac
  done <<EOF
$(build_candidates "https://github.com/${REPO_SLUG}/releases/latest" 0)
EOF
  return 1
}

if [ -n "${DITING_VERSION:-}" ]; then
  VERSION="$DITING_VERSION"
  VERSION_LOG_TEXT="pinned version: $VERSION (DITING_VERSION env override)"
  VERSION_DISPLAY="$VERSION (pinned)"
else
  if [ -n "$TESTONLY" ]; then
    VERSION="v0.0.0-testonly"
  else
    VERSION="$(resolve_latest_version)" || true
  fi
  if [ -z "$VERSION" ]; then
    die "could not resolve latest release (api.github.com and the releases/latest mirror chain all failed); pin a version with DITING_VERSION=vX.Y.Z, or see DITING_INSTALL_MIRROR in the README for mirror options"
  fi
  VERSION_LOG_TEXT="latest release: $VERSION"
  VERSION_DISPLAY="$VERSION"
fi

# Header + step 1 + step 2 land here so the user sees brand + first
# two steps as soon as the version is resolved. The host arch is
# already known from the platform check above.
print_header
step 1 "Host"    "darwin-${ARCH}"   "host detected: darwin-${ARCH}"
step 2 "Release" "$VERSION_DISPLAY" "$VERSION_LOG_TEXT"

# Strip the leading "v" for filenames: tag `v0.10.0` → tarball
# `diting-0.10.0-darwin-arm64.tar.gz`.
NUM_VERSION="${VERSION#v}"
TARBALL_NAME="diting-${NUM_VERSION}-darwin-${ARCH}.tar.gz"
TARBALL_URL="https://github.com/${REPO_SLUG}/releases/download/${VERSION}/${TARBALL_NAME}"
SHASUMS_URL="https://github.com/${REPO_SLUG}/releases/download/${VERSION}/SHASUMS256.txt"

# ---- download + verify ----

if [ -n "$TESTONLY" ]; then
  # FULL / PLAIN render the polished step rows; LOG keeps the
  # existing TESTONLY markers below (and `step "" log_text=""` is a
  # no-op in LOG by contract).
  step 3 "Download" "$TARBALL_NAME (testonly)" ""
  step 4 "Verify"   "sha256 (testonly)"        ""
  note "TESTONLY: would download $TARBALL_URL"
  note "TESTONLY: would verify against $SHASUMS_URL"
else
  TMP_DIR="$(mktemp -d -t diting-install.XXXXXX)"
  step 3 "Download" "$TARBALL_NAME" "downloading $TARBALL_NAME"
  TARBALL_MIRROR=""
  SHASUMS_MIRROR=""
  # tarball walks the mode's chain (validated as gzip); SHASUMS is
  # forced GitHub-first (5th arg=1) so its trust stays anchored on
  # GitHub even when the tarball came from a proxy, and is validated
  # as a real checksums file (rejects an HTML 200 from a dead proxy).
  download_with_fallback "$TARBALL_URL" "${TMP_DIR}/${TARBALL_NAME}" TARBALL_MIRROR tarball 0 \
    || die_with_marker 3 "tarball download failed — GitHub and every mirror exhausted or returned invalid content: $TARBALL_URL"
  download_with_fallback "$SHASUMS_URL" "${TMP_DIR}/SHASUMS256.txt" SHASUMS_MIRROR shasums 1 \
    || die_with_marker 4 "SHASUMS256.txt download failed — GitHub and every mirror exhausted or returned invalid content: $SHASUMS_URL"
  # The shasums validator already guaranteed a 64-hex entry exists.
  EXPECTED_SHA="$(
    awk -v name="$TARBALL_NAME" '$2 == name { print $1 }' \
      "${TMP_DIR}/SHASUMS256.txt"
  )"
  ACTUAL_SHA="$(shasum -a 256 "${TMP_DIR}/${TARBALL_NAME}" | awk '{print $1}')"
  if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    die_with_marker 4 "sha256 mismatch on $TARBALL_NAME (expected $EXPECTED_SHA, got $ACTUAL_SHA)"
  fi
  # Step 4 display: truncate to first 8 hex chars + ellipsis so the
  # row stays scannable; the full hash is still in $ACTUAL_SHA for
  # any debug needs. LOG tier keeps the full hash for grep parity.
  step 4 "Verify" "sha256 ${ACTUAL_SHA:0:8}…" "sha256 verified: $ACTUAL_SHA"
  # When a proxy served either asset, surface the honest trust notice
  # AFTER SHA verification — it names the real anchor (GitHub when
  # SHASUMS was direct, otherwise the serving mirror).
  if [ "$TARBALL_MIRROR" != "github" ] || [ "$SHASUMS_MIRROR" != "github" ]; then
    note "$(mirror_completion_notice "$TARBALL_MIRROR" "$SHASUMS_MIRROR")"
  fi
fi

# ---- extract ----

if [ -n "$TESTONLY" ]; then
  step 5 "Install" "${INSTALL_PREFIX} (testonly)" ""
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
    die_with_marker 5 "extracted tarball missing libexec/diting/diting"
  fi
  if [ -d "$INSTALL_PREFIX" ]; then
    rm -rf "${INSTALL_PREFIX}.old"
    mv "$INSTALL_PREFIX" "${INSTALL_PREFIX}.old"
  fi
  mv "$STAGE_DIR" "$INSTALL_PREFIX"
  rm -rf "${INSTALL_PREFIX}.old"
  ln -snf "${INSTALL_PREFIX}/libexec/diting/diting" "${BIN_DIR}/diting"
  step 5 "Install" "${INSTALL_PREFIX}" "installed to ${INSTALL_PREFIX}"
  # Symlink path goes into the summary block (FULL/PLAIN); LOG keeps
  # the original second note line so its byte shape is unchanged.
  log_only_note "symlinked ${BIN_DIR}/diting"
fi

# ---- prime helper bundle ----

DITING_LOCALE="$(detect_locale)"
DITING_LOCALE_TAG="$(bundle_locale_tag "$DITING_LOCALE")"

if [ -n "$TESTONLY" ]; then
  step 6 "Helper" "${APP_SUPPORT_DIR}/diting-tianer.app (testonly)" ""
  note "TESTONLY: detected locale=${DITING_LOCALE} (tag=${DITING_LOCALE_TAG})"
  note "TESTONLY: would copy helper to ${APP_SUPPORT_DIR}"
  note "TESTONLY: would xattr -dr com.apple.quarantine"
  note "TESTONLY: would run diting setup with DITING_LANG=${DITING_LOCALE} -AppleLanguages (${DITING_LOCALE_TAG})"
else
  mkdir -p "$APP_SUPPORT_DIR"
  SRC_BUNDLE="${INSTALL_PREFIX}/share/diting-tianer.app"
  DST_BUNDLE="${APP_SUPPORT_DIR}/diting-tianer.app"
  if [ ! -d "$SRC_BUNDLE" ]; then
    die_with_marker 6 "extracted tarball missing share/diting-tianer.app"
  fi
  rm -rf "$DST_BUNDLE"
  cp -R "$SRC_BUNDLE" "$DST_BUNDLE"
  # Strip the quarantine xattr macOS attaches to anything that came
  # in via curl. Without this Gatekeeper would block first launch.
  # Same trick Homebrew uses for unsigned casks.
  xattr -dr com.apple.quarantine "$DST_BUNDLE" 2>/dev/null || true
  step 6 "Helper" "${DST_BUNDLE}" "helper bundle primed at ${DST_BUNDLE}"
  # Drive AND verify the TCC grants now, so first launch is clean
  # instead of re-prompting. `diting setup` owns the open + poll +
  # System-Settings routing; it opens the bundle with the matching
  # DITING_LANG / -AppleLanguages so the helper UI and macOS prompts
  # share one locale. On an interactive terminal it blocks-and-verifies
  # (the user clicks Allow on each prompt); on a non-TTY install
  # (CI / pipe) `setup` auto-detects and runs non-blocking. `|| true`
  # so an incomplete grant never fails the install.
  if [ "$DITING_LOCALE" = "zh" ]; then
    step_continuation "正在请求 macOS 权限（定位 → 蓝牙 → 通知）— 逐个点击 Allow"
  else
    step_continuation "granting macOS permissions (Location → Bluetooth → Notifications) — click Allow on each"
  fi
  DITING_LANG="${DITING_LOCALE}" "${BIN_DIR}/diting" setup || true
fi

# ---- PATH hint + summary block ----
#
# In TIER LOG we keep the existing prose-style closer that downstream
# tests pin via substring match. In TIER FULL / TIER PLAIN we compute
# the SUMMARY_NEXT message and let print_summary render the indented
# `Installed.` block — the PATH-hint substance is identical, only the
# layout differs.

case ":$PATH:" in
  *":${BIN_DIR}:"*)
    if [ "$TIER" = "log" ]; then
      note "diting is on your PATH — run \`diting\`"
    else
      SUMMARY_NEXT="run \`diting\` (the splash will guide you through the TCC prompts)"
    fi
    ;;
  *)
    # Detect the user's interactive shell to print the right hint.
    SHELL_NAME="$(basename "${SHELL:-/bin/zsh}")"
    case "$SHELL_NAME" in
      zsh)
        if [ "$TIER" = "log" ]; then
          echo "Add to ~/.zshrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
        else
          SUMMARY_NEXT="add to ~/.zshrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        ;;
      bash)
        if [ "$TIER" = "log" ]; then
          echo "Add to ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
        else
          SUMMARY_NEXT="add to ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        ;;
      fish)
        if [ "$TIER" = "log" ]; then
          echo "Add to ~/.config/fish/config.fish:  fish_add_path \$HOME/.local/bin"
        else
          SUMMARY_NEXT="add to ~/.config/fish/config.fish:  fish_add_path \$HOME/.local/bin"
        fi
        ;;
      *)
        if [ "$TIER" = "log" ]; then
          echo "Add ${BIN_DIR} to your PATH (shell: ${SHELL_NAME})"
        else
          SUMMARY_NEXT="add ${BIN_DIR} to your PATH (shell: ${SHELL_NAME})"
        fi
        ;;
    esac
    ;;
esac

# Print the polished summary block (no-op in TIER LOG).
print_summary
