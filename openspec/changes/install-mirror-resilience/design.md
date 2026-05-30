## Context

`install.sh` downloads two assets per install: the platform tarball and `SHASUMS256.txt`. Today both go through `download_with_fallback url dest used_var` (`install.sh:~150`), which switches on `$MIRROR` (`auto|github|ghproxy`):

- `auto`: try `curl --max-time 20 -fsSL <github-url>`; on non-zero exit, retry `https://ghproxy.com/<github-url>`.
- `github`: GitHub only.
- `ghproxy`: ghproxy.com only.

`ghproxy.com` is dead — it returns HTTP 200 with an HTML landing page. `curl -fsSL`'s `-f` only fails on 4xx/5xx, so a 200-with-HTML is accepted, written to `dest`, and the caller proceeds. For the tarball, SHA verification would later catch the garbage; for `SHASUMS256.txt`, the `awk` parse simply yields an empty `EXPECTED_SHA`, and the installer dies "missing entry" (`install.sh:451`).

Probe data (2026-05-29, from a CN-adjacent network), fetching the real v1.9.0 `SHASUMS256.txt` URL through each proxy:

| proxy | result |
|---|---|
| `ghproxy.com` | HTML landing page (dead) |
| `mirror.ghproxy.com` | no response (down) |
| `ghfast.top` | correct file |
| `gh-proxy.com` | correct file |
| `ghproxy.net` | correct file |
| `gh.ddlc.top` | correct file |

## Goals / Non-Goals

**Goals:**
- A CN install survives any single mirror being dead by walking a chain.
- A mirror that returns garbage (HTML/error with 200) is detected and skipped, never written as the real asset.
- `SHASUMS256.txt` trust is anchored to GitHub whenever GitHub is reachable for it, independent of where the (large) tarball came from.
- Users can point the installer at a working or self-hosted proxy without editing the script.

**Non-Goals:**
- Standing up the user's VPS proxy (infra).
- Reworking the three-tier installer output, the helper-bundle priming, or the SHA-verification algorithm itself.
- Guaranteeing security when GitHub is *fully* unreachable — see Risks.

## Decisions

### D1 — Mirror chain, not a single fallback
`download_with_fallback` becomes a chain walker. The ordered candidate list for a github asset URL `U`:
- `auto` (default): `U` (GitHub direct), then `https://ghfast.top/U`, `https://gh-proxy.com/U`, `https://ghproxy.net/U`.
- `github`: `U` only.
- `ghproxy` (back-compat keyword): the proxy entries only (skip GitHub-direct) — for users who know GitHub is blocked and want to save the 20 s GitHub timeout.
- a `http(s)://…` value: `U` (GitHub direct), then `<value>U` — the user's custom/self-hosted proxy is the only proxy tried.

The default proxy list lives in one shell array constant (`_MIRROR_PROXIES`) so the set is tuned in one place. Each attempt keeps the existing `--max-time 20` budget. Alternatives considered: a single "best" proxy — rejected, that is exactly today's failure mode; an online proxy-health probe — rejected as too slow/fragile for an installer.

### D2 — Content validation gates acceptance
A download attempt is "successful" only when curl exits 0 **and** the body passes a content check for its kind:
- `SHASUMS256.txt`: after writing, the file MUST contain a valid entry for the target tarball — i.e. `awk '$2==name {print $1}'` yields a 64-hex string. (An HTML page, an empty file, or a rate-limit stub fails this.) This check doubles as the existing `EXPECTED_SHA` extraction, so it is free.
- tarball: `gzip -t <file>` (or a gzip magic-byte check `\x1f\x8b`) MUST pass before the file is accepted. SHA verification still runs afterward against the validated SHASUMS.

If validation fails, the attempt is discarded (the partial file removed) and the walker proceeds to the next candidate, exactly as if curl had failed. Only when the whole chain is exhausted does the step die — with a message that names the kinds of failure seen, not "missing entry".

### D3 — `SHASUMS256.txt` is fetched GitHub-first, always
The two assets get *separate* chain walks, and `SHASUMS256.txt` always starts at GitHub-direct regardless of the tarball's outcome or the `DITING_INSTALL_MIRROR` mode (except `github`, which is already GitHub-only, and an explicit custom-URL/`ghproxy` mode, where the user has opted into proxying everything). Rationale: `SHASUMS256.txt` is a few hundred bytes — it succeeds on flaky links where the multi-MB tarball times out — and keeping it on GitHub means a proxy in the tarball path cannot substitute a forged tarball+hash pair. When SHASUMS *does* fall through to a proxy, the completion notice states that explicitly.

### D4 — `DITING_INSTALL_MIRROR` grammar, back-compatible
Resolution (`install.sh:365`) accepts: `auto` (default), `github`, `ghproxy` (now = proxy-chain-only), or any string beginning with `http://` / `https://` (custom proxy prefix). Anything else still `die`s with a clear "expected auto|github|ghproxy|<url>" message. Existing scripts passing `auto|github|ghproxy` keep working; `ghproxy` no longer means the dead single host but the live chain.

### D5 — Honest notices
The fallback notice fires per asset when a proxy is used, naming the proxy host actually hit. The completion notice distinguishes "tarball via <proxy>, SHASUMS direct from GitHub (trust anchored on GitHub)" from "both via <proxy> (trust anchored on that mirror's SHA256)" so the user knows the real trust posture.

## Risks / Trade-offs

- **[All default proxies third-party and rotating]** → they can die like ghproxy.com did. Mitigation: a chain (multiple must die simultaneously) + content validation (a dead proxy is skipped, not fatal) + the custom/self-host override for users who want control. The constant is trivially updatable.
- **[GitHub fully blocked → SHASUMS also via proxy]** → the serving proxy becomes the trust anchor; a malicious proxy could serve a matching forged pair. Mitigation: validation guarantees it is at least a *real* checksums file; the notice is explicit; self-hosting is the answer for the security-conscious. This is strictly no worse than today and usually better (SHASUMS-direct-first).
- **[`gzip -t` not catching a valid-gzip-but-wrong-tarball]** → SHA256 verification (unchanged) still catches that. gzip-test only guards against accepting an HTML body as a tarball before hashing.

## Migration Plan

Pure `install.sh` change; no persisted state, no version bump in this change. Rollback = revert the branch. Old one-liners (`curl … | bash`) keep working; `DITING_INSTALL_MIRROR=auto|github|ghproxy` keep working with improved behaviour.

## Open Questions

- Final default proxy ordering — start with `ghfast.top, gh-proxy.com, ghproxy.net` (all verified live). Revisit if real installs show one consistently faster/more-reliable. (Resolved for v1; the chain + override make this low-stakes.)
