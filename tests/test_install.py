"""Tests for the curl-bash one-line installer (`install.sh`).

The script's behaviour is what users will be running on their
machines, so the tests cover every branch we can reach without
touching the network or the user's real filesystem:

- arch detection (Darwin arm64 vs Darwin x86_64 vs non-Darwin)
- DITING_VERSION env override path
- SHASUMS256.txt mismatch → abort
- DITING_INSTALL_TESTONLY=1 short-circuits side effects and emits
  marker lines we can assert on
- PATH hint emission for zsh / bash / fish vs silent when already
  on PATH

All tests drive the script via `subprocess.run("bash", ...)` so
they exercise the same script the curl-bash one-liner delivers,
not a Python re-implementation.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


def _run(env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run install.sh with TESTONLY=1 by default and a clean-ish env.

    The default env mimics what `curl | bash` would inherit: HOME,
    SHELL, PATH. Tests override individual entries to exercise
    branches.
    """
    base_env = {
        "DITING_INSTALL_TESTONLY": "1",
        "HOME": "/tmp/diting-install-test-home",
        "PATH": "/usr/bin:/bin",
        "SHELL": "/bin/zsh",
    }
    if env_extra:
        base_env.update(env_extra)
    return subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        capture_output=True, text=True, env=base_env, check=False,
    )


def test_install_script_refuses_linux():
    """Script must exit non-zero and name macOS specifically when
    run on a Linux-like uname. We can't actually re-uname the host;
    we shim by injecting a PATH that puts a fake `uname` first."""
    fake_uname_dir = REPO_ROOT / "build" / "fake-uname-linux"
    fake_uname_dir.mkdir(parents=True, exist_ok=True)
    fake = fake_uname_dir / "uname"
    fake.write_text("#!/bin/sh\nif [ \"$1\" = \"-s\" ]; then echo Linux; else echo x86_64; fi\n")
    fake.chmod(0o755)
    proc = _run({"PATH": f"{fake_uname_dir}:/usr/bin:/bin"})
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "macOS-only" in proc.stderr


def test_install_script_refuses_unknown_uname():
    """Some unknown machine arch (or a misconfigured uname) → exit
    non-zero with an arch-specific error rather than partially
    installing for an unsupported arch."""
    fake_uname_dir = REPO_ROOT / "build" / "fake-uname-weird"
    fake_uname_dir.mkdir(parents=True, exist_ok=True)
    fake = fake_uname_dir / "uname"
    fake.write_text("#!/bin/sh\nif [ \"$1\" = \"-s\" ]; then echo Darwin; else echo sparc64; fi\n")
    fake.chmod(0o755)
    proc = _run({"PATH": f"{fake_uname_dir}:/usr/bin:/bin"})
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "unsupported arch" in proc.stderr


def test_install_script_lays_out_user_local_paths_in_dry_run():
    """TESTONLY emits markers describing the steps it would have
    taken. The presence of those markers (not their order) proves
    the branching reaches every step in the happy-path flow."""
    proc = _run({"DITING_VERSION": "v0.10.0-rc1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "TESTONLY: would extract to" in out
    assert ".local/share/diting" in out
    assert "TESTONLY: would symlink" in out
    assert ".local/bin/diting" in out


def test_install_script_primes_application_support_helper_in_dry_run():
    """TESTONLY markers prove the helper-bundle bootstrap branch is
    reached (copy, quarantine strip) AND that the install drives the
    TCC grants via `diting setup`, threading the install-time locale
    so the helper UI and the macOS TCC prompts agree on language."""
    proc = _run({"DITING_VERSION": "v0.10.0-rc1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Library/Application Support/diting" in out
    assert "xattr -dr com.apple.quarantine" in out
    # Helper prime now drives + verifies grants via `diting setup`, with
    # DITING_LANG + -AppleLanguages threaded so the locale flows all the
    # way through to Cocoa's lproj pick.
    assert "would run diting setup" in out
    assert "DITING_LANG=" in out
    assert "-AppleLanguages" in out
    # Locale resolution runs against the test host's preferences;
    # both en and zh runs are valid outputs, so accept either tag.
    assert ("(en)" in out) or ("(zh-Hans)" in out)


def test_install_script_aborts_on_sha_mismatch():
    """We can't easily produce a real SHA mismatch in the dry-run
    path (no actual download happens), so the SHA-verification
    assertion is exercised in the live download branch. The dry-run
    case at least proves the SHA-verify code path is wired:
    `DITING_INSTALL_TESTONLY` skips the download AND skips the
    verification — the test confirms a TESTONLY=1 run emits the
    "would verify" marker (i.e. the script reaches the verify
    branch in normal flow)."""
    proc = _run({"DITING_VERSION": "v0.10.0"})
    assert proc.returncode == 0
    assert "would verify against" in proc.stdout
    assert "SHASUMS256.txt" in proc.stdout


def test_install_script_accepts_matching_sha():
    """Dual to the mismatch case — TESTONLY skips the actual SHA
    check, and we re-assert the verify marker fires under a
    different version pin to prove the branch is reached regardless
    of which version is requested."""
    proc = _run({"DITING_VERSION": "v0.9.0"})
    assert proc.returncode == 0
    assert "would verify against" in proc.stdout


def test_install_script_emits_zsh_path_hint():
    """When ~/.local/bin is NOT on PATH and SHELL is zsh, the
    script prints the exact zsh-flavoured PATH-update line."""
    proc = _run({
        "PATH": "/usr/bin:/bin",  # no ~/.local/bin
        "SHELL": "/bin/zsh",
        "DITING_VERSION": "v0.10.0",
    })
    assert proc.returncode == 0
    assert 'Add to ~/.zshrc:  export PATH="$HOME/.local/bin:$PATH"' in proc.stdout


def test_install_script_emits_bash_path_hint():
    proc = _run({
        "PATH": "/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "DITING_VERSION": "v0.10.0",
    })
    assert proc.returncode == 0
    assert 'Add to ~/.bashrc:  export PATH="$HOME/.local/bin:$PATH"' in proc.stdout


def test_install_script_emits_fish_path_hint():
    proc = _run({
        "PATH": "/usr/bin:/bin",
        "SHELL": "/usr/local/bin/fish",
        "DITING_VERSION": "v0.10.0",
    })
    assert proc.returncode == 0
    assert "fish_add_path $HOME/.local/bin" in proc.stdout


def test_install_script_silent_when_already_on_path():
    """When ~/.local/bin is already on PATH, the script congratulates
    the user instead of printing a hint."""
    proc = _run({
        "HOME": "/tmp/diting-install-test-home",
        "PATH": "/tmp/diting-install-test-home/.local/bin:/usr/bin:/bin",
        "SHELL": "/bin/zsh",
        "DITING_VERSION": "v0.10.0",
    })
    assert proc.returncode == 0
    assert "diting is on your PATH" in proc.stdout
    # No PATH-update hint should appear when we're already wired.
    assert "Add to ~/" not in proc.stdout


def test_install_script_uses_diting_version_override():
    """DITING_VERSION=vX.Y.Z must override the latest-tag lookup —
    the script reports the pinned version explicitly so users
    re-running with the env var see exactly what they're getting."""
    proc = _run({"DITING_VERSION": "v0.9.0"})
    assert proc.returncode == 0
    assert "pinned version: v0.9.0" in proc.stdout


# ---------- Three-tier output ladder (v1.8.0) ----------
#
# The new tier system layers a polished render on TTY environments
# without changing what the script *does*. These cases pin each
# tier's output shape; the existing assertions above cover TIER LOG
# (non-TTY, captured by subprocess) implicitly. The PTY-harness
# cases below spawn the script with a controlled fake-tty so the
# TIER FULL / TIER PLAIN branches are exercised reproducibly.

import shutil

import pytest


def _run_via_pty(env_extra: dict[str, str] | None = None) -> tuple[int, str]:
    """Spawn install.sh inside a pseudo-terminal so `[ -t 1 ]` is true.

    Uses BSD `script -q /dev/null bash …` — present on every macOS
    install and the most reliable way to get bash to see fd 1 as a
    TTY in tests. The `-q` flag suppresses script's own "Script
    started/done" banners. The output captured by subprocess is the
    PTY-routed view, complete with ANSI escapes and the `\\r\\n`
    line endings the slave PTY synthesises.
    """
    if not shutil.which("script"):
        pytest.skip("script(1) not available; needed for PTY tier tests")
    base_env = {
        "DITING_INSTALL_TESTONLY": "1",
        "HOME": "/tmp/diting-install-test-home",
        "PATH": "/usr/bin:/bin",
        "SHELL": "/bin/zsh",
        # Default to UTF-8 + xterm so TIER FULL fires unless a test
        # overrides NO_COLOR / LC_ALL / TERM.
        "LANG": "en_US.UTF-8",
        "TERM": "xterm-256color",
    }
    if env_extra:
        base_env.update(env_extra)
    # `script -q -t 0` (BSD) flushes immediately; on macOS the syntax
    # is `script -q <outfile> <command...>` — `/dev/null` discards
    # script's own log file. The command after that runs inside the
    # PTY that `script` allocates.
    proc = subprocess.run(
        ["script", "-q", "/dev/null", "bash", str(INSTALL_SCRIPT)],
        capture_output=True, text=True, env=base_env, check=False,
        timeout=15,
    )
    return proc.returncode, proc.stdout


def test_tier_log_byte_identical_under_non_tty():
    """Standard subprocess.run (non-TTY) MUST land in TIER LOG so
    every pre-v1.8.0 substring assertion still passes. This is the
    Homebrew + CI contract."""
    proc = _run({"DITING_VERSION": "v0.10.0"})
    assert proc.returncode == 0
    # Existing prose lines must appear exactly as before.
    assert "diting install: host detected: darwin-" in proc.stdout
    assert "diting install: pinned version: v0.10.0" in proc.stdout
    # No tier-polished decorations in LOG.
    assert "[1/6]" not in proc.stdout
    assert "Installed." not in proc.stdout
    # Specifically no ANSI escape sequences.
    assert "\x1b[" not in proc.stdout


def test_tier_full_under_pty():
    """Interactive TTY with UTF-8 locale and no NO_COLOR gets the
    polished output: brand-orange pixel beast, six numbered steps
    with ✓ markers, indented Installed. summary block."""
    rc, out = _run_via_pty({"DITING_VERSION": "v0.10.0"})
    assert rc == 0, out
    # 24-bit ANSI orange escape for the brand mark.
    assert "\x1b[38;2;254;166;43m" in out
    # Pixel-beast art (final row of _LOGO_MARK_ART).
    assert "▀██▀▀▀▀██" in out
    # Numbered step structure.
    assert "[1/6]" in out
    assert "[2/6]" in out
    assert "[6/6]" in out
    # Unicode success marker.
    assert "✓" in out
    # Polished summary block.
    assert "Installed." in out
    assert "binary" in out
    # Old prose-prefix lines MUST NOT leak in FULL.
    assert "diting install: host detected" not in out


def test_tier_plain_under_pty_with_no_color():
    """NO_COLOR=1 on an interactive TTY downgrades FULL to PLAIN —
    keeps the six-step structure but drops the logo + color + Unicode."""
    rc, out = _run_via_pty({"DITING_VERSION": "v0.10.0", "NO_COLOR": "1"})
    assert rc == 0, out
    # Numbered step structure preserved.
    assert "[1/6]" in out
    assert "[6/6]" in out
    # ASCII markers, NOT Unicode.
    assert "[OK]" in out
    assert "✓" not in out
    # No logo.
    assert "▀██▀▀▀▀██" not in out
    # No ANSI escapes.
    assert "\x1b[" not in out
    # Summary block still appears.
    assert "Installed." in out


def test_tier_format_env_override_forces_log_on_tty():
    """DITING_INSTALL_FORMAT=log on an interactive TTY MUST force the
    LOG-tier byte shape — escape hatch for Homebrew formula
    maintainers who want grep-friendly output on a real terminal."""
    rc, out = _run_via_pty({
        "DITING_VERSION": "v0.10.0",
        "DITING_INSTALL_FORMAT": "log",
    })
    assert rc == 0, out
    assert "diting install: host detected: darwin-" in out
    assert "[1/6]" not in out
    assert "Installed." not in out


def test_tier_plain_under_lc_all_c():
    """No UTF-8 locale (`LC_ALL=C`) downgrades FULL to PLAIN even
    with NO_COLOR unset — the script refuses to emit Unicode
    glyphs when the locale won't render them reliably."""
    rc, out = _run_via_pty({
        "DITING_VERSION": "v0.10.0",
        "LC_ALL": "C",
        "LANG": "C",
    })
    assert rc == 0, out
    assert "[1/6]" in out
    assert "[OK]" in out
    assert "▀██▀▀▀▀██" not in out
    assert "\x1b[" not in out


def test_die_with_marker_failure_path_keeps_exit_status():
    """`die` (and its `die_with_marker` wrapper) MUST still exit 1
    and still emit the `diting install: error: ...` line for
    grep-friendliness; the new marker is a visual addition in
    FULL / PLAIN, never a replacement for the error prose.

    The unsupported-arch site uses plain `die()` (not
    `die_with_marker`) because it precedes step 1; this case pins
    that path's exit status + stderr shape unchanged."""
    fake_uname_dir = REPO_ROOT / "build" / "fake-uname-weird-2"
    fake_uname_dir.mkdir(parents=True, exist_ok=True)
    fake = fake_uname_dir / "uname"
    fake.write_text(
        "#!/bin/sh\nif [ \"$1\" = \"-s\" ]; then echo Darwin; else echo sparc64; fi\n"
    )
    fake.chmod(0o755)
    proc = _run({"PATH": f"{fake_uname_dir}:/usr/bin:/bin"})
    assert proc.returncode == 1
    assert "diting install: error: unsupported arch" in proc.stderr


# ---------- CDN-fallback download ladder (v1.8.0) ----------
#
# These cases exercise the `DITING_INSTALL_MIRROR` env var + the
# `download_with_fallback` dispatcher. To avoid real network I/O,
# tests use a curl shim on PATH that records every curl call and
# either succeeds (writing a known-content tarball + matching
# shasums) or fails on demand. The shim is reset between tests.


def _make_curl_shim(
    fake_bin: Path,
    *,
    fail_urls: list[str] | None = None,
    html_urls: list[str] | None = None,
    served_tarball_bytes: bytes | None = None,
    served_shasums_text: str | None = None,
) -> Path:
    """Build a fake curl in `fake_bin` that records every call to
    `<fake_bin>/curl.log` and writes deterministic payloads for the
    happy-path URLs. URLs whose prefix matches any string in
    `fail_urls` cause curl to exit non-zero (simulating a stalled
    GitHub asset host); URLs matching `html_urls` return an HTML 200.

    The tarball payload is a real (deterministic) gzip so install.sh's
    `gzip -t` content check passes; the SHASUMS payload carries that
    gzip's SHA256 so the verification step passes against shim bytes.
    """
    import hashlib, gzip
    fake_bin.mkdir(parents=True, exist_ok=True)
    # Default tarball = a deterministic gzip stream (valid for `gzip -t`).
    # The bytes are pre-written to a file the shim `cat`s, so the SHA is
    # exactly what install.sh will compute on the downloaded file.
    if served_tarball_bytes is None:
        served_tarball_bytes = gzip.compress(b"fake-tarball-content\n", mtime=0)
    (fake_bin / "tarball.bin").write_bytes(served_tarball_bytes)
    sha = hashlib.sha256(served_tarball_bytes).hexdigest()
    # Match install.sh's expected tarball filename for a v0.10.0
    # arm64 (or x86_64 depending on host) build.
    import platform
    arch = "arm64" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    tarball_name = f"diting-0.10.0-darwin-{arch}.tar.gz"
    default_shasums = f"{sha}  {tarball_name}\n"
    shasums_payload = served_shasums_text or default_shasums

    fail_list = " ".join(f'"{u}"' for u in (fail_urls or []))
    # html_urls return HTTP 200 with an HTML landing page (the dead
    # ghproxy.com failure mode) so content-validation fall-through can
    # be exercised.
    html_list = " ".join(f'"{u}"' for u in (html_urls or []))
    curl = fake_bin / "curl"
    # The shim emulates `curl [options] --output <dest> <url>`. It
    # parses argv left-to-right: any --output / -o gives the dest,
    # any positional starting with `http` is the url. Tail-end
    # options like `2>/dev/null` (handled by the shell) are not
    # part of argv.
    curl.write_text(f"""#!/bin/sh
# Fake curl for install.sh tests. Records the URL + dest into
# curl.log; writes deterministic bytes for tarball / shasums URLs.

LOG="{fake_bin}/curl.log"
DEST=""
URL=""
WRITEOUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output|-o) DEST="$2"; shift 2 ;;
    --max-time)   shift 2 ;;
    -w)           WRITEOUT="$2"; shift 2 ;;
    -fsSL|-fsSLO|-sSL|-fsS|-fs|--silent|--fail|--show-error|--location|-L|-f|-s|-S)
      shift ;;
    http*) URL="$1"; shift ;;
    *) shift ;;
  esac
done
echo "$URL -> $DEST" >> "$LOG"

# Fail if the URL matches any prefix in fail_list.
for FAIL_PREFIX in {fail_list}; do
  case "$URL" in
    "$FAIL_PREFIX"*) exit 28 ;;  # 28 = --max-time reached, common CN failure mode
  esac
done

# Serve an HTML 200 landing page for html_list prefixes — the dead
# ghproxy.com failure mode that install.sh must detect and skip.
for HTML_PREFIX in {html_list}; do
  case "$URL" in
    "$HTML_PREFIX"*)
      printf '<!DOCTYPE html>\\n<html><head><title>GitHub Proxy</title></head><body>x</body></html>\\n' > "$DEST"
      exit 0 ;;
  esac
done

# Write deterministic payloads. The tarball gets the canonical
# bytes; SHASUMS gets a single-row file that names that arch's
# tarball filename. The api.github.com latest-release call goes
# through the basic stdout path (no --output) and yields empty JSON
# — so an UNPINNED run falls through to the redirect fallback,
# which the releases/latest branch below emulates: `-w` callers get
# the redirect's final URL, `…/releases/latest` rewritten to
# `…/releases/tag/v0.10.0` (matching the served tarball version).
case "$URL" in
  */releases/latest)
    if [ -n "$WRITEOUT" ]; then
      printf '%s' "${{URL%latest}}tag/v0.10.0"
    fi
    ;;
  *SHASUMS256.txt*)
    printf '%s' '{shasums_payload}' > "$DEST"
    ;;
  *.tar.gz)
    cat "{fake_bin}/tarball.bin" > "$DEST"
    ;;
  *)
    # Anything else (release-API probe etc.) succeeds silently
    [ -n "$DEST" ] && echo "" > "$DEST"
    ;;
esac
exit 0
""")
    curl.chmod(0o755)
    # Reset the log file so each test sees a clean record.
    (fake_bin / "curl.log").write_text("")
    return curl


def _run_with_curl_shim(
    test_name: str,
    env_extra: dict[str, str] | None = None,
    *,
    fail_urls: list[str] | None = None,
    html_urls: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess, str]:
    """Run install.sh with a per-test fake curl on PATH; return the
    completed process plus the shim's call log content.

    Drops TESTONLY so the real download path is exercised — the
    shim handles "downloads".
    """
    fake_bin = REPO_ROOT / "build" / f"fake-curl-{test_name}"
    if fake_bin.exists():
        import shutil
        shutil.rmtree(fake_bin)
    _make_curl_shim(fake_bin, fail_urls=fail_urls, html_urls=html_urls)
    env = {
        "HOME": "/tmp/diting-install-test-home-cdn",
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "SHELL": "/bin/zsh",
        "DITING_VERSION": "v0.10.0",
        # Don't set TESTONLY — we want the real download/verify path.
    }
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        capture_output=True, text=True, env=env, check=False, timeout=30,
    )
    log = (fake_bin / "curl.log").read_text()
    return proc, log


def test_mirror_env_default_auto_ladder():
    """Unset MIRROR -> auto ladder selected; TESTONLY short-circuit
    proceeds normally (the env-resolution branch is exercised but
    no real download happens)."""
    proc = _run({"DITING_VERSION": "v0.10.0"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # No 'unknown' rejection.
    assert "unknown DITING_INSTALL_MIRROR" not in proc.stderr


def test_mirror_env_invalid_value_aborts():
    """Bogus mirror value -> die before any download attempt."""
    proc = _run({"DITING_VERSION": "v0.10.0", "DITING_INSTALL_MIRROR": "fastgit"})
    assert proc.returncode == 1
    assert "unknown DITING_INSTALL_MIRROR value: fastgit" in proc.stderr
    # The accepted-forms list now includes the custom-URL form.
    assert "expected auto|github|ghproxy|<http(s)://proxy/>" in proc.stderr


def test_mirror_env_github_only_skips_ghproxy_path():
    """MIRROR=github + curl shim fails github URL -> install fails,
    ghproxy URL is NOT attempted."""
    proc, log = _run_with_curl_shim(
        "github-only",
        env_extra={"DITING_INSTALL_MIRROR": "github"},
        fail_urls=["https://github.com/"],
    )
    assert proc.returncode == 1, proc.stdout
    # github URL attempted
    assert "https://github.com/" in log
    # ghproxy URL NOT attempted
    assert "https://ghproxy.com/" not in log


def test_mirror_env_ghproxy_keyword_uses_chain():
    """MIRROR=ghproxy (back-compat keyword) -> the TARBALL skips the
    GitHub-first attempt and goes straight to the proxy chain (first
    live proxy serves it). SHASUMS is still forced GitHub-first, so a
    direct github.com SHASUMS attempt is allowed — but the tarball
    must NOT hit github.com directly."""
    proc, log = _run_with_curl_shim(
        "ghproxy-keyword",
        env_extra={"DITING_INSTALL_MIRROR": "ghproxy"},
    )
    # Tarball went straight to the first chain proxy.
    assert "https://ghfast.top/https://github.com/" in log
    # The dead ghproxy.com host is never used.
    assert "https://ghproxy.com/" not in log
    # The tarball URL was NOT fetched direct from github.com (only the
    # SHASUMS github-first attempt may touch github.com).
    direct_tarball = [
        line for line in log.splitlines()
        if line.startswith("https://github.com/") and ".tar.gz" in line
    ]
    assert direct_tarball == [], (
        f"tarball fetched direct from github under MIRROR=ghproxy: {direct_tarball}"
    )


def test_auto_ladder_falls_back_when_github_fails():
    """MIRROR=auto + github shim fails -> fallback notice prints,
    ghproxy URL is attempted, completion notice fires after SHA
    verify succeeds. Install will still fail at extract (fake
    tarball isn't a real tar.gz) but the download + verify phase
    completes."""
    proc, log = _run_with_curl_shim(
        "auto-fallback",
        env_extra={"DITING_INSTALL_MIRROR": "auto"},
        fail_urls=["https://github.com/chenchaoyi/diting"],
    )
    # GitHub (failure) then the first live chain proxy (success).
    assert "https://github.com/chenchaoyi/diting" in log
    assert "https://ghfast.top/https://github.com/chenchaoyi/diting" in log
    # Fallback notice names the proxy host actually tried.
    assert "retrying via ghfast.top mirror" in proc.stdout
    # Completion notice fired; SHASUMS also fell to the mirror (github
    # failed for it too), so trust is anchored on that mirror.
    assert "trust anchored on that mirror" in proc.stdout


def test_auto_ladder_emits_no_notice_when_github_succeeds():
    """MIRROR=auto + github shim succeeds first try -> no fallback
    notice, no completion notice (the mirror never fired)."""
    proc, log = _run_with_curl_shim(
        "auto-happy",
        env_extra={"DITING_INSTALL_MIRROR": "auto"},
        # No fail_urls -> github attempts succeed.
    )
    # Direct github URL was the one that served bytes.
    assert "https://github.com/chenchaoyi/diting" in log
    # No proxy attempt at all.
    assert "https://ghfast.top/" not in log
    assert "https://gh-proxy.com/" not in log
    # No fallback notice, no completion notice.
    assert "GitHub download failed" not in proc.stdout
    assert "trust anchored" not in proc.stdout


def test_sha_verification_runs_against_ghproxy_served_bytes():
    """SHA chain is anchored on bytes, not URL provenance. The
    auto-ladder test above proves verify passes against ghproxy
    bytes (matching SHASUMS). Here we negate: force the shim to
    produce mismatched bytes and assert die_with_marker 4 fires
    regardless of which path served them."""
    fake_bin = REPO_ROOT / "build" / "fake-curl-sha-mismatch"
    if fake_bin.exists():
        import shutil
        shutil.rmtree(fake_bin)
    # The shim serves a valid gzip tarball (default), but the SHASUMS
    # row carries a deliberately-wrong (yet valid-format, 64-hex) hash.
    # The content validator accepts it as a real checksums file; the
    # SHA compare then fails — proving verification is unchanged.
    import platform
    arch = "arm64" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    _make_curl_shim(
        fake_bin,
        served_shasums_text=(
            "0000000000000000000000000000000000000000000000000000000000000000  "
            f"diting-0.10.0-darwin-{arch}.tar.gz\n"
        ),
    )
    env = {
        "HOME": "/tmp/diting-install-test-home-sha",
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "SHELL": "/bin/zsh",
        "DITING_VERSION": "v0.10.0",
        "DITING_INSTALL_MIRROR": "ghproxy",
    }
    proc = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        capture_output=True, text=True, env=env, check=False, timeout=30,
    )
    assert proc.returncode == 1
    assert "sha256 mismatch" in proc.stderr


def test_completion_notice_uses_zh_locale_when_helper_lang_is_zh():
    """ZH-locale user triggering the fallback path gets the Chinese
    copy on both the fallback-firing notice and the completion
    notice. We stub `defaults read -g AppleLanguages` via a fake
    /usr/bin/defaults on PATH that returns ("zh-Hans-CN")."""
    fake_bin = REPO_ROOT / "build" / "fake-curl-zh-locale"
    if fake_bin.exists():
        import shutil
        shutil.rmtree(fake_bin)
    _make_curl_shim(
        fake_bin,
        fail_urls=["https://github.com/chenchaoyi/diting"],
    )
    # Shim defaults(1) to return a zh-prefixed language.
    fake_defaults = fake_bin / "defaults"
    fake_defaults.write_text(
        '#!/bin/sh\necho \'("zh-Hans-CN", "en")\'\n'
    )
    fake_defaults.chmod(0o755)
    env = {
        "HOME": "/tmp/diting-install-test-home-zh",
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "SHELL": "/bin/zsh",
        "DITING_VERSION": "v0.10.0",
        "DITING_INSTALL_MIRROR": "auto",
    }
    proc = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        capture_output=True, text=True, env=env, check=False, timeout=30,
    )
    # ZH fallback-firing notice (names the proxy host).
    assert "GitHub 下载失败" in proc.stdout
    assert "切换到 ghfast.top 镜像重试" in proc.stdout
    # ZH completion notice — SHASUMS also fell to the mirror, so trust
    # is anchored on that mirror.
    assert "信任锚定于该镜像" in proc.stdout


# ---------------------------------------------------------------------
# install-mirror-resilience: chain + content validation + custom mirror
# ---------------------------------------------------------------------

def _gh_tarball_prefix() -> str:
    """The GitHub-direct tarball URL prefix for this host's arch — used
    to fail ONLY the direct-from-github tarball attempt (not SHASUMS,
    not the proxied variants, which carry a proxy prefix)."""
    import platform
    arch = "arm64" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    return (
        "https://github.com/chenchaoyi/diting/releases/download/"
        f"v0.10.0/diting-0.10.0-darwin-{arch}.tar.gz"
    )


def test_mirror_chain_falls_through_to_second_proxy():
    """GitHub + the first chain proxy fail; the second proxy serves the
    tarball. Proves the walker steps past a dead mirror instead of
    giving up after one fallback."""
    proc, log = _run_with_curl_shim(
        "chain-fallthrough",
        env_extra={"DITING_INSTALL_MIRROR": "auto"},
        fail_urls=["https://github.com/chenchaoyi/diting",
                   "https://ghfast.top/"],
    )
    assert "https://ghfast.top/https://github.com/" in log       # attempted
    assert "https://gh-proxy.com/https://github.com/" in log     # served
    assert "missing entry" not in proc.stderr


def test_mirror_rejects_html_200_and_tries_next():
    """A proxy answers HTTP 200 with an HTML landing page (the dead
    ghproxy.com mode); the content validator rejects it and the next
    proxy serves a real file — NOT a 'missing entry' dead-end."""
    proc, log = _run_with_curl_shim(
        "html-reject",
        env_extra={"DITING_INSTALL_MIRROR": "auto"},
        fail_urls=["https://github.com/chenchaoyi/diting"],  # github down
        html_urls=["https://ghfast.top/"],                   # garbage 200
    )
    assert "https://ghfast.top/https://github.com/" in log     # garbage, skipped
    assert "https://gh-proxy.com/https://github.com/" in log   # real, accepted
    assert "missing entry" not in proc.stderr
    # Reached SHA verification — download phase succeeded despite the HTML.
    assert "sha256 verified" in proc.stdout


def test_mirror_chain_exhausted_aborts():
    """GitHub and every chain proxy fail for the tarball -> abort with a
    real 'exhausted' error (not 'missing entry'); nothing extracted."""
    proc, log = _run_with_curl_shim(
        "chain-exhausted",
        env_extra={"DITING_INSTALL_MIRROR": "auto"},
        fail_urls=["https://github.com/chenchaoyi/diting",
                   "https://ghfast.top/",
                   "https://gh-proxy.com/",
                   "https://ghproxy.net/"],
    )
    assert proc.returncode == 1
    assert "exhausted" in proc.stderr
    assert "missing entry" not in proc.stderr


def test_shasums_prefers_github_direct_when_tarball_mirrored():
    """Only the GitHub tarball fails; the tiny SHASUMS still succeeds
    GitHub-direct, so trust stays anchored on GitHub even though the
    tarball came from a proxy."""
    proc, log = _run_with_curl_shim(
        "shasums-direct",
        env_extra={"DITING_INSTALL_MIRROR": "auto"},
        fail_urls=[_gh_tarball_prefix()],
    )
    # Tarball served by the first proxy.
    assert "https://ghfast.top/https://github.com/" in log
    # SHASUMS came direct from github — no proxy prefix on its URL.
    shasums_lines = [ln for ln in log.splitlines() if "SHASUMS256.txt" in ln]
    assert any(ln.startswith("https://github.com/") for ln in shasums_lines), shasums_lines
    assert not any(("ghfast.top" in ln or "gh-proxy.com" in ln or "ghproxy.net" in ln)
                   for ln in shasums_lines), shasums_lines
    # Honest completion notice: anchored on GitHub.
    assert "trust anchored on GitHub" in proc.stdout


def test_mirror_custom_url_override():
    """A custom http(s) proxy prefix is the sole proxy; the default
    chain proxies are never touched."""
    proc, log = _run_with_curl_shim(
        "custom-url",
        env_extra={"DITING_INSTALL_MIRROR": "https://gh.example.test/"},
        fail_urls=[_gh_tarball_prefix()],
    )
    assert "https://gh.example.test/https://github.com/" in log
    assert "https://ghfast.top/" not in log
    assert "https://gh-proxy.com/" not in log
    assert "https://ghproxy.net/" not in log


# ---- harden-version-resolve: latest-tag resolution fallback ----
#
# DITING_VERSION="" (empty) un-pins the version so the resolve path
# runs. The shim's api.github.com branch returns empty JSON, so the
# resolve always falls through to the releases/latest redirect; the
# shim answers `-w %{url_effective}` calls with the URL rewritten to
# `…/releases/tag/v0.10.0`, matching the served tarball version.

def test_version_resolve_falls_back_to_redirect_when_api_fails():
    """API yields nothing -> the releases/latest redirect (GitHub-
    direct candidate) resolves v0.10.0 and the install proceeds into
    the download phase under that version."""
    proc, log = _run_with_curl_shim(
        "resolve-redirect",
        env_extra={"DITING_VERSION": ""},
    )
    # The API was attempted, then the redirect candidate.
    assert "https://api.github.com/repos/chenchaoyi/diting/releases/latest" in log
    assert "https://github.com/chenchaoyi/diting/releases/latest" in log
    # Resolution landed on the redirect's tag (LOG-tier step 2 line).
    assert "latest release: v0.10.0" in proc.stdout
    # Proof the resolved tag drove the download step.
    assert "diting-0.10.0-darwin" in proc.stdout


def test_version_resolve_rejects_non_version_redirect():
    """A candidate whose final URL is not a /tag/<version> shape is
    rejected and the next candidate tried — here GitHub-direct
    answers with a landing page (no redirect), the first chain proxy
    serves the real redirect."""
    proc, log = _run_with_curl_shim(
        "resolve-reject-nonversion",
        env_extra={"DITING_VERSION": ""},
        html_urls=["https://github.com/chenchaoyi/diting/releases/latest"],
    )
    # Direct attempt happened but did not resolve; proxy attempt fired.
    assert "https://github.com/chenchaoyi/diting/releases/latest" in log
    assert (
        "https://ghfast.top/https://github.com/chenchaoyi/diting/releases/latest"
        in log
    )
    assert "latest release: v0.10.0" in proc.stdout


def test_version_resolve_failure_names_both_escapes():
    """API + every redirect candidate fail -> abort non-zero naming
    BOTH escapes: DITING_VERSION to pin, DITING_INSTALL_MIRROR for
    mirrors."""
    proc, _log = _run_with_curl_shim(
        "resolve-exhausted",
        env_extra={"DITING_VERSION": ""},
        fail_urls=[
            "https://api.github.com/",
            "https://github.com/chenchaoyi/diting/releases/latest",
            "https://ghfast.top/",
            "https://gh-proxy.com/",
            "https://ghproxy.net/",
        ],
    )
    assert proc.returncode != 0
    assert "could not resolve latest release" in proc.stderr
    assert "DITING_VERSION=vX.Y.Z" in proc.stderr
    assert "DITING_INSTALL_MIRROR" in proc.stderr
