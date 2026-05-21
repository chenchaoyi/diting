# tasks — align-events-vocabulary

## 1. Spec

- [x] Draft proposal, design, tasks
- [x] Spec delta in `specs/tui-shell/spec.md`
      (MODIFIED requirement: EventsPanel format bullets + scenario example
      flip from `joined` → `seen`)

## 2. Implementation

- [x] `src/diting/i18n.py:1199-1204` — rename three EN keys:
      `device joined: ` → `device seen: `,
      `service joined: ` → `service seen: `,
      `host joined: ` → `host seen: `
- [x] `src/diting/tui.py:1948, 1971, 1994` — update `t(...)` call sites
- [x] `src/diting/tui.py:885` — extend events-modal footer:
      `Press 1/2/3/4/0 to filter` → `Press 1/2/3/4/5/6/7/0 to filter`
- [x] `src/diting/i18n.py:1248-1249` — ZH translation of the footer
- [x] `src/diting/tui.py:612` — help-modal "Events modal (m)" paragraph
- [x] `src/diting/i18n.py:880, 886` — that paragraph EN + ZH

## 3. Tests

- [x] `tests/test_tui_helpers.py:2659` — `"device joined"` → `"device seen"`
- [x] `tests/test_tui_helpers.py:2692` — `"service joined"` → `"service seen"`
- [x] `tests/test_tui_helpers.py:2725` — `"host joined"` → `"host seen"`

## 4. Validation

- [x] `uv run pytest` — 768 passed
- [x] `uv run python scripts/tui_snapshot.py --mode regression` — green
- [x] `openspec validate --specs --strict` — 21/21
- [x] `openspec validate align-events-vocabulary --strict` — valid

## 5. CHANGELOG

- [ ] `CHANGELOG.md` — `## [Unreleased]` → `### Fixed`
- [ ] `docs/zh/CHANGELOG.md` — mirror EN entry

## 6. Merge + archive

- [ ] PR open, reviewed, merged
- [ ] `/opsx:archive align-events-vocabulary`
