## 1. Test plan (test-first, per CLAUDE.md hard rule)

- [x] 1.1 Add a "CDN fallback download ladder" row to `tests/TESTING.md` under the `installation` capability table — pin the env-override matrix + the github-first / ghproxy-fallback ordering + the SHA-anchored-on-canonical invariant.
- [x] 1.2 Mirror into `docs/zh/TESTING.md`.

## 2. `install.sh` — dispatcher + env override

- [x] 2.1 Near the top of `install.sh`, resolve `DITING_INSTALL_MIRROR` once into a `MIRROR` global. Accept `auto` (default if unset), `github`, `ghproxy`. Any other value → `die "unknown DITING_INSTALL_MIRROR value: <value> (expected auto|github|ghproxy)"` BEFORE any download work.
- [x] 2.2 Add `download_with_fallback <url> <dest> <used_mirror_var>` helper that dispatches per the `MIRROR` resolution. Uses `curl -fsSL --max-time 20 --output <dest> <url>` (note `--max-time`, NOT `--connect-timeout`). The `<used_mirror_var>` parameter sets a caller-provided global to `github` or `ghproxy` indicating which path actually served the bytes; the standard pre-bash-4.3 `eval` indirection is used (macOS bash 3.2 compatibility).
- [x] 2.3 In the `auto` branch, on GitHub failure print `note "GitHub download failed (likely CN network); retrying via ghproxy.com mirror..."` before retrying.

## 3. Wire existing two `curl … --output …` sites through the helper

- [x] 3.1 Replace the tarball curl at `install.sh:139-140` (`curl -fsSL --output "${TMP_DIR}/${TARBALL_NAME}" "$TARBALL_URL" || die …`) with `download_with_fallback "$TARBALL_URL" "${TMP_DIR}/${TARBALL_NAME}" TARBALL_MIRROR || die_with_marker 3 "tarball download failed via github AND ghproxy.com: $TARBALL_URL"`.
- [x] 3.2 Replace the SHASUMS curl at `install.sh:141-142` with the analogous call wired to `SHASUMS_MIRROR` and `die_with_marker 4 …`.
- [x] 3.3 After the SHA verification step succeeds, conditionally print the completion notice: `if [ "$TARBALL_MIRROR" = "ghproxy" ] || [ "$SHASUMS_MIRROR" = "ghproxy" ]; then note "..."; fi`. Use EN copy in the EN branch, ZH copy in the ZH branch (`detect_locale` is already computed elsewhere in the script for the helper-prompt-language flow; reuse that variable).

## 4. i18n / copy

- [x] 4.1 Add the EN notice string: `tarball or SHASUMS fetched via ghproxy.com mirror; trust anchored on SHA256`.
- [x] 4.2 Add the ZH notice string: `tarball 或 SHASUMS 通过 ghproxy.com 镜像下载；信任仍锚定于 SHA256`.
- [x] 4.3 Add the EN fallback-firing notice string: `GitHub download failed (likely CN network); retrying via ghproxy.com mirror...`.
- [x] 4.4 Add the ZH fallback-firing notice string: `GitHub 下载失败（网络可能受限）；切换到 ghproxy.com 镜像重试...`.

## 5. README + ZH README

- [x] 5.1 In the install section of `README.md`, add one paragraph: "*From inside China? The installer automatically falls back to a public GitHub mirror (`ghproxy.com`) if the direct GitHub download stalls — set `DITING_INSTALL_MIRROR=ghproxy` to skip the GitHub-first attempt and save 20 s per install once you know GitHub is unreachable from your network.*"
- [x] 5.2 Mirror into `docs/zh/README.md` with the natural Chinese phrasing.

## 6. Tests

- [x] 6.1 `tests/test_install.py::test_mirror_env_default_auto_ladder` — `MIRROR` is unset; script proceeds normally (TESTONLY skips the actual downloads but the env resolution branch is still reached). Assert TESTONLY proceeds without the new "unknown DITING_INSTALL_MIRROR" abort.
- [x] 6.2 `tests/test_install.py::test_mirror_env_invalid_value_aborts` — set `DITING_INSTALL_MIRROR=fastgit`; assert exit 1 BEFORE any TESTONLY step prints, stderr contains `unknown DITING_INSTALL_MIRROR value: fastgit (expected auto|github|ghproxy)`.
- [x] 6.3 `tests/test_install.py::test_mirror_env_github_only_skips_ghproxy_path` — set `DITING_INSTALL_MIRROR=github`. Use a curl shim (PATH override) that fails the github URL. Assert exit 1 and that the curl shim's call log contains the github URL but NOT the ghproxy URL.
- [x] 6.4 `tests/test_install.py::test_mirror_env_ghproxy_only_skips_github_path` — set `DITING_INSTALL_MIRROR=ghproxy`. Curl shim records calls; assert ghproxy URL was attempted and github URL was NOT.
- [x] 6.5 `tests/test_install.py::test_auto_ladder_falls_back_when_github_fails` — `MIRROR=auto`. Curl shim fails github URL (exit 28 — `--max-time` reached), succeeds on ghproxy URL. Assert exit 0, stdout contains the "GitHub download failed (likely CN network)" fallback notice AND the "fetched via ghproxy.com mirror" completion notice.
- [x] 6.6 `tests/test_install.py::test_auto_ladder_emits_no_notice_when_github_succeeds` — `MIRROR=auto`, github URL succeeds first try. Assert no fallback notice printed; no "fetched via ghproxy" completion notice.
- [x] 6.7 `tests/test_install.py::test_sha_verification_runs_against_ghproxy_served_bytes` — `MIRROR=ghproxy`, curl shim "serves" bytes that match the canonical SHA. Assert install proceeds. Then second case: curl shim "serves" bytes that mismatch; assert `die_with_marker 4 "sha256 mismatch …"` fires regardless of which URL produced the bytes.
- [x] 6.8 `tests/test_install.py::test_completion_notice_uses_zh_locale_when_helper_lang_is_zh` — set `defaults read AppleLanguages` shim (or pre-existing `DITING_LANG`) to zh; under `MIRROR=ghproxy` and TESTONLY, assert the completion notice's ZH copy appears.

## 7. CI gates

- [x] 7.1 `uv run pytest` — green
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression` — unaffected, green
- [x] 7.3 `openspec validate --specs --strict` — green
- [x] 7.4 `openspec validate install-cn-cdn-fallback --strict` — green
- [ ] 7.5 `shellcheck install.sh` — clean (no new warnings introduced; existing baseline preserved)

## 8. Manual visual check

- [ ] 8.1 In a non-CN network (or with VPN), run `DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm no fallback notice prints (happy path).
- [ ] 8.2 In a CN network without VPN, run `DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm either GitHub succeeds (no notice) or the fallback notice prints and ghproxy serves the bytes.
- [ ] 8.3 Run `DITING_INSTALL_MIRROR=ghproxy DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm the github URL is never attempted (skip the 20 s wait).
- [ ] 8.4 Run `DITING_INSTALL_MIRROR=github DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm canonical-only path, no fallback.
- [ ] 8.5 Run `DITING_INSTALL_MIRROR=fastgit DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm immediate error with `unknown DITING_INSTALL_MIRROR value: fastgit` on stderr.
- [ ] 8.6 Run `DITING_LANG=zh DITING_INSTALL_MIRROR=ghproxy DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm ZH copy on the fallback + completion notices.

## 9. Wrap-up

- [x] 9.1 EN ↔ ZH parity check on the new copy strings + TESTING entries + README entries.
- [ ] 9.2 Commit and push the branch `feat/install-cn-cdn-fallback`.
- [ ] 9.3 Open the PR using the repo template.
