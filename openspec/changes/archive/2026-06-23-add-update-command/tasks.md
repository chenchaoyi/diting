# Tasks

- [x] `src/diting/update.py`: `version_tuple` / `is_newer` / `normalize`,
      `fetch_latest_tag` (GitHub API), `run_installer` (fetch install.sh + bash
      pinned to `DITING_VERSION`)
- [x] `cli.py`: `_run_update` (`--check` / `--json` / default install), `update`
      in `_COMMANDS`, dispatch branch, scene-banner suppression
- [x] `i18n.py`: ZH for every new `t()` string
- [x] `test_cli.py`: add `update` to the canonical-verb list assertion
- [x] `tests/TESTING.md` + `docs/zh/TESTING.md` rows BEFORE test code
- [x] `test_update.py`: version compare; `--json` shape; `--check` up-to-date vs
      available; network error → exit 1 (+ structured under `--json`); installer
      re-run pins `DITING_VERSION`
- [x] Run all four CI gates
