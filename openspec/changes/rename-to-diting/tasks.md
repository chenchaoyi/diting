## 1. Branch + scaffolding

- [x] 1.1 Cut `chore/rename-to-diting` from latest `main`
- [x] 1.2 Run a baseline self-test (pytest + regression + spec strict) so any breakage is clearly caused by the rename, not pre-existing

## 2. Python package + CLI entry

- [x] 2.1 `git mv src/wifiscope src/diting`
- [x] 2.2 Update every `from wifiscope...` / `import wifiscope...` import across `src/`, `tests/`, `scripts/`, `docs/_capture_preview.py`
- [x] 2.3 Update `pyproject.toml`: `[project] name = "diting"`, console-script entry `wifiscope = ...` → `diting = ...`, any other `wifiscope` references in tool config (uv / hatch / pytest-paths)
- [x] 2.4 Update `Makefile` targets that name the binary or package
- [x] 2.5 Default JSONL log filename builder: `wifiscope-<TS>.jsonl` → `diting-<TS>.jsonl` in `src/diting/i18n.py` (or wherever the default-path constant lives) and matching tests in `test_event_log.py`
- [x] 2.6 `.gitignore`: `/wifiscope-*.jsonl` → `/diting-*.jsonl`

## 3. Environment variables

- [x] 3.1 Replace every `WIFISCOPE_*` env-var reference with `DITING_*`. Grep targets: `os.environ`, `getenv`, `os.getenv`, raw strings in i18n.py, tests that set env vars
- [x] 3.2 Confirm no compatibility shim left: `git grep WIFISCOPE_` returns clean except for `openspec/changes/archive/*` and historical `CHANGELOG.md` sections

## 4. Helper bundle (`diting-tianer` — 谛听之天耳)

- [x] 4.1 Rename `helper/wifiscope-helper.app` → `helper/diting-tianer.app` (and the inner `Contents/MacOS/wifiscope-helper` binary to `diting-tianer`)
- [x] 4.2 Update Swift sources under `helper/Sources/` for any user-facing strings, helpURL, etc. — including any `wifiscope-helper` references in source comments
- [x] 4.3 `Info.plist`: `CFBundleIdentifier` → `com.chenchaoyi.diting.tianer`, `CFBundleName` → `diting-tianer` (and `CFBundleDisplayName` → `谛听 · 天耳` so the brand shows in System Settings → Privacy panes), `CFBundleExecutable` → `diting-tianer`
- [x] 4.4 `helper/build.sh`: replace `wifiscope-helper` references with `diting-tianer`
- [x] 4.5 Update `_helper.find_helper()` search path constant to `helper/diting-tianer.app/Contents/MacOS/diting-tianer`
- [x] 4.6 Rebuild via `./helper/build.sh`; verify binary lands at the new path
- [ ] 4.7 `open helper/diting-tianer.app` once on the maintainer Mac, click Allow on Location Services + Bluetooth prompts. Confirm subsequent `diting wifi-scan` runs produce unredacted SSIDs.  *(USER ACTION — pause point at end of run)*

## 5. Strings + i18n

- [x] 5.1 Replace every `wifiscope` literal in `src/diting/i18n.py` (both EN keys and ZH values) with `diting`. Special care: scenario commands, env-var examples, helper-build hints
- [x] 5.2 Replace every `WIFISCOPE_` literal in i18n catalog with `DITING_`
- [x] 5.3 Run `make test-all` to verify EN, ZH, and locale-detected ZH all still pass

## 6. Docs (EN + ZH parity)

- [x] 6.1 `README.md` + `docs/zh/README.md`: replace `wifiscope` with `diting` / `谛听` in user-facing prose; update tagline lines (subtitle / hero) to the locked B option:
    - EN: "Your Mac hears more than it tells you."
    - ZH: "你的 Mac 听见了什么，告诉你。"
- [x] 6.2 `DEVELOPMENT.md` + `docs/zh/DEVELOPMENT.md`: rename references; the "How it works" section's `WiFiBackend` mention stays (class name, not app name)
- [x] 6.3 `CHANGELOG.md` + `docs/zh/CHANGELOG.md`: add a `[Unreleased]` entry under `### Changed` (and `### BREAKING`) documenting the rename. Do NOT rewrite historical sections — they keep saying `wifiscope`.
- [x] 6.4 `tests/TESTING.md` + `docs/zh/TESTING.md`: rename references to commands and env vars
- [x] 6.5 `docs/workflow.md` + `docs/zh/workflow.md`: rename references; verify the SDD workflow section still describes the same flow
- [x] 6.6 `docs/zh/HELPER.md`: rename references (this file has no EN counterpart; that's pre-existing — flag it in the PR description if found odd, do not create a sibling EN file in this rename PR)
- [x] 6.7 `CLAUDE.md`: rename references in the agent-rules brief
- [x] 6.8 `docs/explainers/wifi-sensing.md` + `docs/zh/explainers/wifi-sensing.md`: rename references

## 7. Specs

- [x] 7.1 Delta specs in `openspec/changes/rename-to-diting/specs/` cover all Requirement-level renames. **Scope expanded from original plan**: 11 capability deltas, not 4. Added `analyze`, `ble-decoders`, `bluetooth-scanning`, `environment-monitor`, `events`, `inventory`, `wifi-scanning` after discovering scenario-level `wifiscope` references in those specs.
- [x] 7.2 Only 4 specs (`ble-detail-modal`, `link-health`, `roam-detection`, `tui-shell`) had wifiscope mentions exclusively in Purpose-section narrative; those got direct (non-delta) text edits.
- [x] 7.3 `openspec/AGENTS.md` + `openspec/README.md`: rename references

## 8. Helper / scripts / engineering tooling

- [x] 8.1 `scripts/tui_snapshot.py` (and any docstrings / banner strings)
- [x] 8.2 `docs/_capture_preview.py` rename references in fake-backend setup
- [x] 8.3 `.github/pull_request_template.md` and any other GitHub templates

## 9. Self-test

- [x] 9.1 `uv run pytest` — all tests green (360/360)
- [x] 9.2 `uv run python scripts/tui_snapshot.py --mode regression` — 16/16 asserts pass
- [x] 9.3 `openspec validate --specs --strict` — 15/15 specs valid
- [x] 9.4 `openspec validate rename-to-diting --strict` — change valid (re-run after every delta spec edit)
- [ ] 9.5 Optional: real-env `/tui-audit` to spot-check that the renamed UI behaves on a live Mac  *(SKIP unless user invokes; not gating)*

## 10. Final hygiene

- [x] 10.1 `git grep -in 'wifiscope'` matches only intentional residuals:
    - `openspec/changes/archive/**` (frozen historical proposals)
    - `openspec/changes/rename-to-diting/**` (this change itself documents the rename)
    - `openspec/specs/<delta-tracked-spec>/**` (12 capabilities — `cli`, `macos-helper`, `i18n`, `event-log`, `analyze`, `ble-decoders`, `bluetooth-scanning`, `environment-monitor`, `events`, `inventory`, `wifi-scanning`, `tui-shell` — these get rewritten at archive time when the delta specs are applied)
    - `CHANGELOG.md` and `docs/zh/CHANGELOG.md` historical sections (pre-rename releases)
    - `.gitignore` (kept the old `wifiscope-*.jsonl` and `helper/wifiscope-helper.app/` entries alongside the new ones — safety net for any leftover local files)
    - `docs/specs/v0.x.x-*.md` (historical pre-OpenSpec spec drafts, frozen)
    - `git log` output — out of scope (history not rewritten)
- [x] 10.2 `git grep -in 'WIFISCOPE_'` matches only the same intentional residuals (canonical specs awaiting delta apply, archive, CHANGELOG history, docs/specs/ historical)

## 11. Commit + PR

- [ ] 11.1 Commit with a message like `chore: rename wifiscope → diting (谛听)`. Body summarises the surface changed + the bundle-ID / TCC re-grant note.
- [ ] 11.2 Push branch, open PR against `main`
- [ ] 11.3 Wait for CI green (pytest matrix × 3, regression, spec validate)
- [ ] 11.4 Merge

## 12. Post-merge (out of band, not strictly part of the change)

- [ ] 12.1 Rename the GitHub repo via the GitHub UI (`chenchaoyi/wifiscope` → `chenchaoyi/diting`); GitHub auto-redirects old URLs
- [ ] 12.2 Update local clone's remote URL: `git remote set-url origin git@github.com:chenchaoyi/diting.git`
- [ ] 12.3 Update `MEMORY.md` entries that reference `wifiscope` to either `谛听 / Diting (formerly wifiscope)` or just `Diting`
- [ ] 12.4 Archive this change: `openspec archive rename-to-diting` (applies the four delta specs into canonical `openspec/specs/`)
