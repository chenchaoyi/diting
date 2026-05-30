## 1. Test plan first (TESTING.md before code — hard rule 4)

- [x] 1.1 Add the new install-mirror cases to `tests/TESTING.md` (EN, canonical): mirror chain fall-through, HTML-200 rejection + skip, chain-exhausted error, SHASUMS GitHub-direct-first, custom-mirror URL, `ghproxy` keyword = chain, invalid value aborts, SHA256 mismatch still aborts.
- [x] 1.2 Mirror the same rows into `docs/zh/TESTING.md` (ZH) in the same pass — EN ↔ ZH parity.

## 2. install.sh — mirror chain + grammar

- [x] 2.1 Add a single `_MIRROR_PROXY_CHAIN` constant of live proxy prefixes (`https://ghfast.top/`, `https://gh-proxy.com/`, `https://ghproxy.net/`); remove the dead `ghproxy.com` literal.
- [x] 2.2 Rework `DITING_INSTALL_MIRROR` resolution: accept `auto` / `github` / `ghproxy` (now = chain, skip GitHub-first) / any `http(s)://…` value (custom proxy prefix); abort on anything else with a message naming all accepted forms.

## 3. install.sh — chain walker + content validation

- [x] 3.1 Rewrite `download_with_fallback` to walk an ordered candidate list (built from the resolved mode via `build_candidates`) and stop at the first attempt that BOTH transfers (curl exit 0) AND passes a content check; report which source served it via the `used_var`.
- [x] 3.2 Add content validators (`validate_download`): a SHASUMS check (yields a 64-hex hash for the target tarball; reject HTML/empty) and a tarball check (`gzip -t`). A failed check discards the partial file and continues to the next candidate.
- [x] 3.3 SHASUMS download uses a GitHub-first ladder (5th arg `force_gh=1`) independent of the tarball outcome; tarball uses the mode's ladder (`ghproxy` skips GitHub-first for the tarball only).
- [x] 3.4 Replace the "missing entry" dead-end: chain-exhausted `die_with_marker` names the asset + real failure; the `EXPECTED_SHA`-empty branch is now guaranteed by the SHASUMS validator.

## 4. install.sh — honest notices

- [x] 4.1 Fallback notice fires per proxy attempt, naming the proxy host (`_mirror_host`) actually used (EN + ZH).
- [x] 4.2 Completion notice distinguishes "tarball via mirror, SHASUMS direct from GitHub (trust anchored on GitHub)" vs "SHASUMS via mirror (trust anchored on that mirror)" (EN + ZH).

## 5. Tests (`tests/test_install.py`)

- [x] 5.1 Extend the curl shim so specific URL prefixes can return HTTP-200 garbage (HTML) instead of the real payload, to exercise content validation + fall-through.
- [x] 5.2 Chain fall-through: GitHub + first proxy fail → second proxy serves the tarball; install succeeds.
- [x] 5.3 HTML-200 rejection: a proxy returns an HTML `SHASUMS256.txt` → rejected, next proxy serves a real one → install succeeds (no "missing entry").
- [x] 5.4 Chain exhausted: GitHub + all proxies fail/garbage → non-zero abort naming the asset; no extraction.
- [x] 5.5 SHASUMS GitHub-direct-first: tarball served by a proxy while GitHub-direct SHASUMS succeeds → SHASUMS came from GitHub (assert via curl.log) + GitHub-anchored completion notice.
- [x] 5.6 Custom mirror URL: `DITING_INSTALL_MIRROR=https://gh.example.test/` + GitHub fails → retried via that prefix, no other proxy (assert via curl.log).
- [x] 5.7 Grammar: `ghproxy` skips GitHub-first for the tarball; invalid value aborts with the new message; update the existing `test_mirror_env_invalid_value_aborts` expectation.
- [x] 5.8 Regression: SHA256 mismatch still aborts (existing behaviour preserved).

## 6. Docs

- [x] 6.1 `README.md` + `docs/zh/README.md`: update the install section to describe the mirror chain + `DITING_INSTALL_MIRROR` (incl. custom-proxy URL for self-hosting).
- [x] 6.2 `CHANGELOG.md` + `docs/zh/CHANGELOG.md` under `[Unreleased]`: a Fixed entry (ghproxy.com dead → mirror chain + content validation + SHASUMS-direct + custom mirror).

## 7. CI gates (hard rule 3)

- [x] 7.1 `uv run pytest` green (esp. `tests/test_install.py`).
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression` clean.
- [x] 7.3 `openspec validate --specs --strict` and `openspec validate install-mirror-resilience --type change --strict` both pass.
