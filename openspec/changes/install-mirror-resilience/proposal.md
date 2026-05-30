## Why

The v1.8.0 CN-network install fallback is broken. It hardcodes a single mirror, `ghproxy.com`, which has since been discontinued — the domain now answers `https://ghproxy.com/<github-url>` with **HTTP 200 and its own HTML landing page** (`<title>GitHub Proxy 代理加速</title>`) instead of proxying the file. Because `install.sh` fetches with `curl -fsSL` (which only checks the HTTP status, not the body), it accepts that HTML as a "successful" download, writes it into `SHASUMS256.txt`, and then dies with a misleading `SHASUMS256.txt missing entry for diting-X.Y.Z-darwin-arm64.tar.gz`.

A real v1.9.0 install attempt hit exactly this. The release itself is fine (the GitHub-hosted `SHASUMS256.txt` has the correct entries) — the installer's mirror layer is the failure.

Root causes:
1. **Single hardcoded mirror, now dead.** No alternative when `ghproxy.com` fails.
2. **No content validation.** Any HTTP 200 is trusted, so an HTML error/landing page is written as if it were the real asset.
3. **No custom-mirror override.** `DITING_INSTALL_MIRROR` only accepts `auto|github|ghproxy`, so a user can't point at a working or self-hosted proxy without editing the script.
4. **Weak trust anchoring.** When the fallback fires, both the tarball AND `SHASUMS256.txt` are fetched through the same proxy, so that proxy — not GitHub — is effectively the trust anchor, despite the completion notice claiming "trust anchored on SHA256".

## What Changes

- **Mirror chain instead of one mirror.** Replace the dead single `ghproxy.com` fallback with an ordered chain of currently-live proxies, tried in turn after GitHub: `ghfast.top`, `gh-proxy.com`, `ghproxy.net` (all verified live 2026-05-29; `ghproxy.com` and `mirror.ghproxy.com` are dead/down).
- **Validate every downloaded file before trusting it.** `SHASUMS256.txt` must parse as a checksums file (an entry for the target tarball, i.e. a `<64-hex>␠␠<name>` row — never HTML); the tarball must be a real gzip. A source that returns garbage with HTTP 200 is treated as a *failed* attempt and the next source in the chain is tried — no more "missing entry" dead-end.
- **`SHASUMS256.txt` prefers GitHub-direct.** Regardless of where the tarball comes from, `SHASUMS256.txt` is always fetched from GitHub first; a proxy serves it only if GitHub truly fails for it too. This narrows the trust window — a single proxy cannot forge a matching tarball+SHASUMS pair unless GitHub-direct `SHASUMS256.txt` *also* fails — and the completion notice becomes honest about which source anchored trust.
- **Custom / self-hosted mirror override.** `DITING_INSTALL_MIRROR` additionally accepts a URL prefix (e.g. `https://gh.my-vps.example/`), used as the proxy in the `<prefix><github-url>` convention. `auto` / `github` keep their meaning; `ghproxy` is kept as a back-compat keyword that now means "skip the GitHub-first attempt, go straight to the proxy chain."

Out of scope: standing up the user's own VPS proxy (infra, not this repo); changing the three-tier installer output; bumping the version or cutting a release (separate step).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `installation`: the GitHub-Releases fetch requirement gains mirror-chain + content-validation + SHASUMS-direct-first + custom-mirror behaviour. **Note:** the v1.8.0 "GitHub-first ghproxy fallback" delta (archived under `2026-05-26-install-cn-cdn-fallback`) was never synced into the canonical `installation` spec, so this change ADDS the (corrected) mirror requirement rather than modifying a non-existent one. The pre-existing canonical SHA-verification requirement is referenced but not weakened.

## Impact

- **Code:** `src/.. ` — actually `install.sh` only: `download_with_fallback` becomes a chain walker with per-attempt content validation; a new SHASUMS-direct-first path; `DITING_INSTALL_MIRROR` resolution accepts a URL; the fallback/completion notices name the actual source.
- **Tests:** `tests/test_install.py` — extend the curl shim to serve per-URL garbage (HTML) so validation + chain fall-through can be exercised; add cases for chain fall-through, HTML-rejection, SHASUMS-direct-first, custom-mirror URL, and the updated `DITING_INSTALL_MIRROR` grammar.
- **Docs:** `tests/TESTING.md` + `docs/zh/TESTING.md` (test plan first); `README.md` + `docs/zh/README.md` install section (CN mirror behaviour + custom mirror env); `CHANGELOG.md` + `docs/zh/CHANGELOG.md` under `[Unreleased]`.
- **No JSONL / permission / helper-schema impact.** Trust model is *improved* (SHASUMS-direct-first); SHA256 verification stays mandatory and unchanged.
- **Separate follow-up (flagged, not in this change):** sync the orphaned v1.8.0 install deltas (three-tier output) into the canonical `installation` spec.
