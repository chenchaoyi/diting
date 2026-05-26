## Context

`install.sh` today downloads the release tarball + `SHASUMS256.txt` from `github.com/<owner>/<repo>/releases/download/<tag>/…` via two `curl -fsSL --output …` calls at lines 139–142. The URLs are constructed once near the top (`TARBALL_URL`, `SHASUMS_URL`) and consumed unconditionally.

In practice the GitHub asset host (`objects.githubusercontent.com`) routes badly from CN networks — multi-minute downloads, occasional hangs that exceed `curl`'s default no-timeout behaviour. The pre-v1.8.0 user experience for CN users is "the install hangs". They reach for a VPN, retry, or give up.

The constraint pinning our design space:

- **No new operator surface.** Personal Cloudflare R2 / ccy.dev hosting moves the SLA onto us. The user explicitly wanted to avoid that.
- **GitHub stays the trust anchor.** SHA256 verification anchors on `SHASUMS256.txt`; that file's public Git history on GitHub is what makes the release tamper-evident.
- **Global users keep their fast path.** Don't redirect everyone through a proxy "just in case" — that adds a hop and a third-party dependency for users who don't need it.
- **Compatibility envelope.** The existing `install.sh` three-tier output (LOG / PLAIN / FULL) must keep working; the existing `DITING_INSTALL_TESTONLY=1` short-circuit, the existing `die_with_marker` failure-path. No new bash features (must run on macOS-default bash 3.2 if anyone has SIP-disabled `/bin/bash`; we target `/usr/bin/env bash` which is typically 3.2+).
- **Auditable failure mode.** When something fails, the user should see *which* URL was tried and which one succeeded, so they can debug.

`ghproxy.com` is the established CN public mirror. It's a simple URL-prefix proxy: `https://ghproxy.com/https://github.com/<owner>/<repo>/releases/download/<tag>/<file>` returns the same bytes the GitHub URL would return, just through Cloudflare PoPs that route well from CN. The service is free, has been running stably for years in the CN open-source community, but it CAN go down or get blocked — historically the project has changed domains a couple of times (originally `ghproxy.com`, now also `gh-proxy.com`). We pin to a single host (`ghproxy.com`) and treat its failure as the user's network failure — at that point both primary and mirror are unreachable and the install legitimately can't proceed.

## Goals / Non-Goals

**Goals:**

- Fix the CN-from-GitHub download hang without changing the global-user experience.
- Keep the SHA256 chain anchored on GitHub-canonical bytes regardless of which network path delivered them.
- Make the fallback path visible — the user sees "GitHub failed; trying ghproxy.com mirror" rather than a silent reroute.
- Give CN users a one-keystroke escape hatch (`DITING_INSTALL_MIRROR=ghproxy`) to skip the 20 s GitHub timeout on every install once they know their network can't reach GitHub.
- Zero new infra. No new dependencies. No new costs.

**Non-Goals:**

- Region detection. We don't try to guess if the user is in China. GitHub-first is correct for everyone; the fallback only fires when GitHub actually fails.
- Multiple-proxy chain (fastgit → gh-proxy → ghproxy → …). Obscures the failure mode; pin to one mirror.
- Hosting the tarballs ourselves (R2, ccy.dev). User explicitly out-of-scope.
- Bittorrent / IPFS / signed-manifests-on-blockchain etc. Overkill for a fallback that needs to work today.
- Touching the helper-bundle copy/launch flow. That works against local-disk bytes regardless of how they got there.
- Changing the output tier rendering. The new notes flow through the existing `note` helper.

## Decisions

### Single fallback host (`ghproxy.com`), not a chain

A two-step ladder (`github → ghproxy`) is auditable: when the user sees "GitHub failed; trying ghproxy.com" they know exactly which path served their bytes. A three-or-more-step chain (github → ghproxy → fastgit → gh-proxy) would muddy the debug story and add latency to every CN install (each timeout is 20 s × number of failed hops).

If `ghproxy.com` itself goes down for a sustained period, the right response is to ship a new `install.sh` pointing at whichever mirror is alive — a one-line change. We don't future-proof against mirror death by chaining, because mirror death is rare enough that a one-line PR-and-release is cheaper than carrying a chain on every install.

### Timeout = 20 s for the GitHub primary

20 s on `curl --max-time` is the upper end of "healthy international download" for a 22 MB tarball. Real-world numbers:

- US/EU → GitHub asset host: typically <3 s
- JP/SG → GitHub asset host: typically <5 s
- CN → GitHub asset host: 30 s – multi-minute, frequently stalled

20 s gives non-CN users plenty of headroom (we won't false-positive on a slow-but-working network). For CN users the failure is fast — usually a TCP RST or stalled handshake within the first 10 s, but the 20 s ceiling guarantees we don't sit forever.

The fallback gets the same 20 s budget; if ghproxy is also down or slow, total worst case is 40 s before `die_with_marker` fires.

### Trust anchor: SHA256, not URL provenance

The SHA256 verification step at `install.sh:150-152` runs against the downloaded bytes regardless of which URL produced them. A malicious ghproxy could in theory serve a (tarball, shasums) pair that's internally consistent but differs from the canonical GitHub release. Two layers of defence:

1. **SHA256 cross-check possibility.** Users who care can run `gh release view <tag>` (against the canonical GitHub API, separate transport) to fetch the expected SHA and compare. This is a manual check; we don't automate it because the GitHub API itself has the same CN-reachability problem.
2. **Public Git history.** A consistent (tarball, shasums) pair from a hostile mirror diverges from the public release attestation that GitHub serves to non-CN users; one cross-region report surfaces the discrepancy quickly. For a personal project with ~hundreds of users, this is sufficient threat modelling.

We don't bake in TUF / sigstore / SBOM signature verification — overkill for the threat model and out of scope.

### Notice when the fallback fired

When EITHER the tarball or the shasums was downloaded via ghproxy, `install.sh` prints a single notice line on completion:

```
note "tarball or SHASUMS fetched via ghproxy.com mirror; trust anchored on SHA256"
```

The notice is informational — the SHA already verified, so we know the bytes match canonical. But the user benefits from seeing "ah, I went through the mirror today" so they can debug routing issues, or set `DITING_INSTALL_MIRROR=ghproxy` to skip the GitHub-attempt timeout on subsequent installs.

In TIER LOG the notice is a regular `diting install: …` line; in TIER FULL / PLAIN it appears as a step-continuation row.

### `DITING_INSTALL_MIRROR` env override

Three values + invalid-value handling:

- `auto` (default): GitHub-first ladder, ghproxy fallback.
- `github`: GitHub only. Fail fast at the existing `die` site when curl fails. Matches pre-change behaviour, useful for users who don't trust the mirror or want to deterministically test the GitHub path.
- `ghproxy`: ghproxy only. Skip the GitHub-first attempt entirely. Useful for CN users who already know GitHub will time out — saves 20 s per install.
- anything else: `die "unknown DITING_INSTALL_MIRROR value: <value> (expected auto|github|ghproxy)"` BEFORE any download attempt.

The env var is resolved once near the top of `install.sh`, alongside the existing `DITING_VERSION` / `DITING_REPO` reads. No mid-script reconfiguration.

### `download_with_fallback` helper shape

```bash
download_with_fallback() {
  local url="$1" dest="$2" used_mirror_var="$3"
  case "$MIRROR" in
    github)
      curl --max-time 20 -fsSL --output "$dest" "$url" \
        || return 1
      eval "$used_mirror_var=github"
      ;;
    ghproxy)
      curl --max-time 20 -fsSL --output "$dest" "https://ghproxy.com/${url}" \
        || return 1
      eval "$used_mirror_var=ghproxy"
      ;;
    auto)
      if curl --max-time 20 -fsSL --output "$dest" "$url" 2>/dev/null; then
        eval "$used_mirror_var=github"
      else
        note "GitHub download failed (likely CN network); retrying via ghproxy.com mirror..."
        curl --max-time 20 -fsSL --output "$dest" "https://ghproxy.com/${url}" \
          || return 1
        eval "$used_mirror_var=ghproxy"
      fi
      ;;
  esac
}
```

The `$used_mirror_var` parameter lets callers know which path actually served the bytes — used by the "fetched via ghproxy.com mirror" notice on completion. We use `eval` for the indirection (the standard pre-`bash 4.3 declare -n` form, since macOS-default bash 3.2 lacks nameref).

Caller pattern:

```bash
download_with_fallback "$TARBALL_URL" "${TMP_DIR}/${TARBALL_NAME}" TARBALL_MIRROR \
  || die_with_marker 3 "tarball download failed via github AND ghproxy.com: $TARBALL_URL"
download_with_fallback "$SHASUMS_URL" "${TMP_DIR}/SHASUMS256.txt" SHASUMS_MIRROR \
  || die_with_marker 3 "SHASUMS256.txt download failed via github AND ghproxy.com: $SHASUMS_URL"

if [ "$TARBALL_MIRROR" = "ghproxy" ] || [ "$SHASUMS_MIRROR" = "ghproxy" ]; then
  note "tarball or SHASUMS fetched via ghproxy.com mirror; trust anchored on SHA256"
fi
```

### Why curl `--max-time` and not `--connect-timeout`

`--connect-timeout` bounds only the TCP handshake; CN→GitHub-assets failures often complete the handshake but then stall on the download body. `--max-time` bounds total wall-clock, which is what we actually want. The 20 s budget covers the slowest healthy case while still failing fast on stalled CN routes.

`-fsSL` semantics from today are preserved:
- `-f`: HTTP-error response → curl exits non-zero
- `-s`: silent (no progress meter — important for the polished tier output)
- `-S`: show errors even when silent
- `-L`: follow redirects (jsDelivr / ghproxy issue 30x sometimes)

## Risks / Trade-offs

[Risk] **`ghproxy.com` goes down or gets blocked**. → Mitigation: the fallback was always best-effort. When ghproxy fails too, we land on `die_with_marker` with a clear "both github and ghproxy unreachable" message that points the user at `DITING_INSTALL_MIRROR=ghproxy` to skip the github-first attempt, or at a manual download path. We commit to shipping a new `install.sh` pointing at the next mirror (fastgit.org / gh-proxy.com / etc.) within ~24 h if ghproxy stays down — a one-line PR.

[Risk] **Malicious ghproxy serves a coordinated (tarball, shasums) pair**. → Mitigation: SHA256 verifies against whichever bytes came down. A hostile mirror would need to substitute BOTH files consistently. The threat model is a personal project with a small audience; matching against canonical GitHub-served SHA is the cross-check (manual today, automatable later if needed). Detection latency = "one user runs `gh release view` and compares" which surfaces within hours.

[Risk] **CN users with working GitHub still pay the 20 s timeout sometimes**. → Mitigation: 20 s is the upper bound; healthy CN→GitHub routes finish in <10 s usually. For users who consistently see slow GitHub, `DITING_INSTALL_MIRROR=ghproxy` skips the github-first attempt entirely. Documenting that env var in the README is part of this change.

[Risk] **Mirror's bandwidth limit hits**. → Mitigation: `ghproxy.com` doesn't publish a rate limit and hasn't historically rate-limited at the small scale a personal project generates. If it does, fail-mode is "fallback fails, install fails" — same as primary failure today.

[Risk] **HTTPS cert / TLS issues on the proxy**. → Mitigation: `curl -fsSL` validates cert by default. If ghproxy serves a bad cert, curl fails, fallback fails, install legitimately fails. We don't add `-k` (insecure skip).

[Risk] **Some user wants to PIN the mirror for compliance reasons** (e.g. corp policy says "no third-party CDNs"). → Mitigation: `DITING_INSTALL_MIRROR=github` explicitly disables fallback and matches pre-change behaviour. Documented in README.

## Migration Plan

No migration. The change is purely additive on the download dispatcher. New installs automatically pick up the GitHub-first-with-fallback ladder. Existing installations are unaffected — `install.sh` is run at install time only, and re-installs honour the new behaviour the next time the user runs the curl-bash one-liner.

Rollback: revert the change. No state to migrate; no installed-on-disk artefact depends on which URL served it.

## Open Questions

- Should we also surface `DITING_INSTALL_MIRROR` as a documented env var in README (yes — included in tasks), and should it appear in `--help` output? **There's no `--help` on `install.sh`**; the one-liner is curl-bash, so README is the doc surface. Just README.
- Do we add a `DITING_INSTALL_TIMEOUT` env to override the 20 s budget? **Defer**: a follow-up if 20 s turns out to be wrong for some user's network. Not landing it here keeps surface small.
- Should the notice line "fetched via ghproxy.com mirror" appear in ZH locale too? **Yes** — `install.sh` already has the EN/ZH branch for the helper-prompt guidance lines; the notice should follow the same pattern. Single ZH string addition.
