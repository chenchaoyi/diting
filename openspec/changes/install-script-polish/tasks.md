## 1. Test plan (test-first, per CLAUDE.md hard rule)

- [x] 1.1 Add a "Three-tier output ladder" row to `tests/TESTING.md` under the `installation` capability table — describe the tier-selection rules and pin the three test cases (TIER FULL / PLAIN / LOG).
- [x] 1.2 Mirror into `docs/zh/TESTING.md`.

## 2. `install.sh` — tier detection + renderer entry points

- [x] 2.1 Add `detect_tier()` near the top of `install.sh` (after `set -euo pipefail`, before platform check). Return `full` / `plain` / `log` via stdout per the proposal's priority order.
- [x] 2.2 Store the tier in a script-global `TIER` variable, computed once.
- [x] 2.3 Define ANSI color escape constants (`ORANGE`, `GREEN`, `RED`, `DIM`, `RESET`) — empty strings when `TIER != full`, real escape sequences when `TIER == full`.
- [x] 2.4 Implement `print_header()` — emit pixel-beast art (byte-equal to `_LOGO_MARK_ART` in `tui.py`) + tagline. No-op in TIER PLAIN / LOG.

## 3. Six-step routing helpers

- [x] 3.1 Implement `step <N> <label> <value>` — case-dispatches on `$TIER`:
  - `full`: `printf '[%d/6] %-10s %s %s\n' "$N" "$label" "$value" "${GREEN}✓${RESET}"`
  - `plain`: `printf '[%d/6] %-10s %s [OK]\n' "$N" "$label" "$value"`
  - `log`: keep the existing `note "..."` shape — pass through to today's prose strings via a step-N → today's-text lookup.
- [x] 3.2 Implement `summary` — in FULL/PLAIN, print the indented `Installed.` block with `binary` / `bundle` / `next` rows; in LOG, no-op (the existing PATH-hint tail stays as the closer).
- [x] 3.3 Implement `die_with_marker <step_n> <msg>` — prints a `[✗] Step <N>/6 failed: <msg>` line (in FULL/PLAIN, red marker) before calling the existing `die` with the same message.

## 4. Wire the existing flow through the new helpers

- [x] 4.1 Step 1 (Host) — replace `note "host detected: darwin-${ARCH}"` at install.sh:102 with `step 1 "Host" "darwin-${ARCH}"`.
- [x] 4.2 Step 2 (Release) — replace the `note "latest release: $VERSION"` / `note "pinned version: …"` branches with `step 2 "Release" "$VERSION"` (annotate with `(pinned)` suffix when DITING_VERSION override).
- [x] 4.3 Step 3 (Download) — replace `note "downloading $TARBALL_NAME"` with `step 3 "Download" "$TARBALL_NAME"`. Add the tarball size in human-readable form (Mac stat `stat -f %z` + simple MB rounding) as a parenthesised suffix.
- [x] 4.4 Step 4 (Verify) — replace `note "sha256 verified: $ACTUAL_SHA"` with `step 4 "Verify" "sha256 ${ACTUAL_SHA:0:8}…"`. The full hash stays available in `$ACTUAL_SHA` for `die_with_marker` failure-path use.
- [x] 4.5 Step 5 (Install) — fold the existing `note "installed to ${INSTALL_PREFIX}"` and `note "symlinked ${BIN_DIR}/diting"` into a single `step 5 "Install" "${INSTALL_PREFIX}"` row; the symlink path goes into the summary block at the end.
- [x] 4.6 Step 6 (Helper) — replace `note "helper bundle primed at ${DST_BUNDLE}"` with `step 6 "Helper" "${DST_BUNDLE}"`. The three localised guidance lines (Location/Bluetooth/Notifications etc.) become continuation rows printed AFTER the step row, indented to align with the value column in FULL/PLAIN; in LOG they keep their current `note "..."` shape.
- [x] 4.7 Failure sites — wrap each `die "..."` site that corresponds to a numbered step with the matching `die_with_marker <step_n> "..."` call: sha mismatch (step 4), tarball download fail (step 3), extract path missing (step 5), helper bundle missing (step 6). Non-step-bound `die` calls (e.g. platform check, version resolve) stay as plain `die`.

## 5. End-of-install summary block

- [x] 5.1 Replace the existing PATH-hint case block at install.sh:236-258 with `summary` invocation in FULL/PLAIN, fall through to the existing case in LOG.
- [x] 5.2 The `summary` body in FULL/PLAIN prints:
  - bold/header line `Installed.`
  - `  binary    ${BIN_DIR}/diting`
  - `  bundle    ${DST_BUNDLE}` (when on the helper path; skip in TESTONLY)
  - `  next      run \`diting\` (the splash will guide you through the TCC prompts)` OR the per-shell PATH-update hint when `~/.local/bin` is not on PATH.

## 6. Tests

- [x] 6.1 `tests/test_install.py::test_tier_log_byte_identical_under_non_tty` — run the installer with `DITING_INSTALL_TESTONLY=1`, no PTY harness; capture stdout; assert the byte-exact today-format lines (`diting install: host detected: darwin-*`, `diting install: latest release: …`, etc.) — proves the LOG-tier path is unchanged.
- [x] 6.2 `tests/test_install.py::test_tier_full_under_pty` — spawn the installer via `pty.openpty()` with `LANG=en_US.UTF-8`, `TERM=xterm-256color`, `NO_COLOR` unset, `DITING_INSTALL_TESTONLY=1`. Assert the output contains the orange-color escape sequence `\033[38;2;254;166;43m`, the pixel-beast `▀██▀▀▀▀██` line, `[1/6] Host`, `✓`, the indented `Installed.` summary block.
- [x] 6.3 `tests/test_install.py::test_tier_plain_under_pty_with_no_color` — same PTY harness with `NO_COLOR=1`. Assert output has the six-step structure (`[1/6] Host`), ASCII `[OK]` markers, NO ANSI escape sequences, NO pixel-beast art, but DOES include the `Installed.` summary block.
- [x] 6.4 `tests/test_install.py::test_tier_format_env_override_forces_log_on_tty` — PTY harness + `DITING_INSTALL_FORMAT=log`. Assert output is byte-identical to the non-TTY LOG run from 6.1.
- [x] 6.5 `tests/test_install.py::test_tier_plain_under_lc_all_c` — PTY harness with `LC_ALL=C`. Assert PLAIN tier engages (six-step structure, ASCII markers, no logo).
- [x] 6.6 `tests/test_install.py::test_die_with_marker_failure_path_keeps_exit_status` — synthesise a step failure (e.g. point SHASUMS to a bad URL via the existing testonly hooks if possible, or a separate `tests/test_install_failure.py`); assert exit 1, assert the `[✗]`/`[FAIL]` marker prefix on the failing step row in FULL/PLAIN, assert the `diting install: error: ...` text still appears for grep-friendliness.

## 7. CI gates

- [x] 7.1 `uv run pytest` — green
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression` — unaffected, green
- [x] 7.3 `openspec validate --specs --strict` — green
- [x] 7.4 `openspec validate install-script-polish --strict` — green
- [ ] 7.5 `shellcheck install.sh` — clean (no new warnings introduced; existing baseline preserved)

## 8. Manual visual check

- [ ] 8.1 Run `DITING_INSTALL_TESTONLY=1 bash install.sh` in iTerm2 (UTF-8, no NO_COLOR) — confirm TIER FULL renders header + six steps + summary.
- [ ] 8.2 Run `NO_COLOR=1 DITING_INSTALL_TESTONLY=1 bash install.sh` — confirm TIER PLAIN.
- [ ] 8.3 Run `DITING_INSTALL_TESTONLY=1 bash install.sh | cat` — confirm TIER LOG.
- [ ] 8.4 Run `DITING_INSTALL_FORMAT=log DITING_INSTALL_TESTONLY=1 bash install.sh` in iTerm2 — confirm override forces LOG even on TTY.
- [ ] 8.5 Run `DITING_INSTALL_TESTONLY=1 LANG=zh_CN.UTF-8 bash install.sh` — confirm ZH guidance lines appear under step 6, six-step structure intact.

## 9. Wrap-up

- [x] 9.1 EN ↔ ZH parity check on the new TESTING entries.
- [ ] 9.2 Commit and push the branch `feat/install-script-polish`.
- [ ] 9.3 Open the PR using the repo template.
