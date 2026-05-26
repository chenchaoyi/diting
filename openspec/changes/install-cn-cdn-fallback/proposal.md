## Why

`curl … install.sh | bash` from inside Chinese networks routinely times out or stalls when pulling tarballs from `github.com/.../releases/download/…`. The asset host (`objects.githubusercontent.com`) is reachable but consistently slow / packet-lossy from CN ISPs — multi-minute downloads on a 22 MB tarball, occasional hangs that exceed `curl`'s default timeout. Today the install bricks for CN users until they retry or set up a VPN.

The fix that doesn't make us an operator: keep GitHub Releases as canonical (single source of truth, trust anchor for the SHA), but add an automatic fallback to a public GitHub proxy when the GitHub download itself fails or stalls. We're not redirecting all traffic through the proxy — global users keep their direct GitHub path with no behaviour change. Only when the GitHub download fails do we try the mirror.

`ghproxy.com` is the established public proxy for this use case in the CN open-source community. It's a URL-rewrite mirror: `https://ghproxy.com/https://github.com/.../tarball` proxies the request through CN-reachable infrastructure. Free, no API key, no signup. Risk: third-party proxies can go down or get blocked, in which case the install fails over to whatever the user's network can reach next. We pin the proxy to a single host (no chain) to keep the failure mode auditable.

## What Changes

### New download dispatcher in `install.sh`

`download_with_fallback <url> <dest>` replaces the two raw `curl -fsSL --output … <url>` call sites:

1. Try GitHub URL with `curl --max-time 20 -fsSL --output <dest> <url>`. 20s is generous enough for a healthy international download of the 22 MB tarball and short enough that a stalled CN connection surfaces quickly.
2. On non-zero curl exit, print `note "GitHub download failed (likely CN network); retrying via ghproxy.com mirror..."` and try `https://ghproxy.com/<url>` with the same `--max-time 20`.
3. On still-failing, `die_with_marker <step_n> "both GitHub and ghproxy.com unreachable for <url>"`.

### Trust chain stays anchored on GitHub

- The tarball SHA256 verification step is **unchanged**. Bytes from ghproxy.com are validated against `SHASUMS256.txt` exactly the same way bytes from GitHub are.
- `SHASUMS256.txt` flows through the SAME fallback ladder. A compromised ghproxy could in theory serve a coordinated (tarball, shasums) pair, but the public Git history on GitHub makes that detectable: a compromised release surfaces against the canonical repo's `gh release view <tag>` SHA the user can audit independently.
- When the fallback fires for EITHER tarball or shasums, `install.sh` prints a notice on completion (`note "tarball or SHASUMS fetched via ghproxy.com mirror; trust anchored on SHA256"`) so the user sees that the mirror path was taken.

### Env overrides

| Value | Behaviour |
|---|---|
| `DITING_INSTALL_MIRROR=auto` (default) | GitHub first, ghproxy.com fallback — the new ladder |
| `DITING_INSTALL_MIRROR=github` | GitHub only; fail fast if it's down (current pre-change behaviour) |
| `DITING_INSTALL_MIRROR=ghproxy` | ghproxy.com only; useful for CN users who know GitHub is unreachable and want to skip the 20 s timeout on every install |
| any other value | invalid; `die "unknown DITING_INSTALL_MIRROR value: <value>"` |

### Helper-bundle TCC prompt flow

Unchanged. The helper-bundle copy + `open` flow runs against the local-disk extracted tarball regardless of which URL served the bytes.

### Output / install.sh tier ladder

Unchanged. The new fallback notes fire through the existing `note` helper, which renders correctly under TIER LOG / PLAIN / FULL per the prior `install-script-polish` change.

## Capabilities

### New Capabilities

(none — all changes land in the existing `installation` capability.)

### Modified Capabilities

- `installation`: new requirement that the installer SHALL try GitHub first and fall back to `ghproxy.com` on failure for both tarball and `SHASUMS256.txt` downloads, with `DITING_INSTALL_MIRROR=auto|github|ghproxy` env overrides and the SHA256 verification step unchanged.

## Impact

- **Code**: `install.sh` gains a `download_with_fallback` helper (~30 lines) and a `DITING_INSTALL_MIRROR` resolver (~10 lines). The existing two `curl … --output …` call sites are replaced; the SHA-verification block is untouched.
- **Tests**: `tests/test_install.py` adds 4 cases — env override resolution (jsdelivr / github / auto / invalid value rejected), ladder dispatch order (github URL attempted first), fallback-on-failure dispatch (stub curl that fails the github URL still completes install via the ghproxy URL), and the trust-anchored-on-SHA invariant (SHA verification fires regardless of which URL served the bytes).
- **TESTING.md** + **docs/zh/TESTING.md**: new row under the `installation` capability table.
- **README** + **docs/zh/README.md**: one-line note added to the install section — "*From inside China? The installer automatically falls back to a public GitHub mirror (ghproxy.com) if the direct GitHub download stalls.*"
- **Snapshot regression** (`scripts/tui_snapshot.py`): unaffected.
- **Dependencies**: none. `curl` is already required; the proxy is HTTP-only via URL rewrite.
- **Permissions / privacy**: none. Same byte stream, just via a different network path when the primary fails. SHA-verification means a hostile mirror is detected and aborted.
- **Spec deltas**: `installation`.

## Out of scope

- Hosting on personal `ccy.dev` infra (Cloudflare R2 + custom domain). Would make us the operator with SLA / TLS / abuse-handling burden; revisit only if `ghproxy.com` becomes consistently unreliable.
- Chain of multiple CN proxies (fastgit.org, ghproxy.net). Single-mirror dispatch keeps the failure mode auditable; chain would obscure which mirror succeeded.
- Region detection (geolocate the user, pick the right primary). The GitHub-first ladder is correct globally — non-CN users get GitHub fast path, CN users get GitHub-attempt-then-fallback. No need to guess where the user is.
- Mirroring `SHASUMS256.txt` from a different source than the tarball (e.g. always GitHub for shasums). Considered, rejected: if GitHub is completely down for the user, requiring GitHub for shasums makes the install fail in the exact case the fallback was supposed to fix. The SHA chain still detects a compromised mirror via the SHA-verification step.
