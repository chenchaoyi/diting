# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `installation`
  rows: redirect fallback resolves; total failure names both escapes.

## 2. Version resolution
- [x] 2.1 `install.sh` — `resolve_latest_version`: API first (bounded
  timeout), then the `releases/latest` redirect through `build_candidates`;
  version-shape check on the parsed tag; failure copy names
  `DITING_VERSION` + `DITING_INSTALL_MIRROR`.

## 3. README bootstrap mirror
- [x] 3.1 `README.md` + `docs/zh/README.md` — document the proxy-prefixed
  raw URL for fetching `install.sh` when raw.githubusercontent.com is
  blocked.

## 4. Tests
- [x] 4.1 `test_install.py` — fake-`curl` shims: API fails → redirect
  resolves (resolved tag visible downstream); everything fails → guidance
  named; non-version redirect rejected.

## 5. Gates
- [x] 5.1 `uv run pytest`, snapshot regression,
  `openspec validate --specs --strict`,
  `openspec validate harden-version-resolve --strict`.
