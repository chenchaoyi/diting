# tasks — add-scene-awareness

## 1. Spec

- [x] Draft proposal, design, tasks
- [x] New capability spec: `specs/scenes/spec.md`
- [x] Delta on `specs/cli/spec.md`
- [x] Delta on `specs/event-log/spec.md`
- [x] Delta on `specs/analyze/spec.md`
- [x] Delta on `specs/bluetooth-scanning/spec.md`
- [x] Delta on `specs/tui-shell/spec.md`

## 2. Test plan

- [x] Extend `tests/TESTING.md` — new `scenes` section, extended
      `event-log`, extended `analyze`
- [x] `docs/zh/TESTING.md` — EN ↔ ZH parity

## 3. Implementation — core

- [x] `src/diting/scene.py` — constants, get/set/resolve,
      `scene_defaults`
- [x] `src/diting/event_log.py` — `emit_session_meta` method;
      idempotent

## 4. Implementation — CLI

- [x] `src/diting/cli.py` — `_extract_scene_arg`, scene resolution
      in `main()`, threaded into `_run_tui` and `_run_monitor`
- [x] `_resolve_ble_presence_gate` accepts `scene_default`
- [x] Help text update (EN + ZH)

## 5. Implementation — TUI + BLE

- [x] `DitingApp` accepts `scene` + `scene_source`; chip in title
      bar via `_build_subtitle`
- [x] `emit_session_meta` called immediately after constructing
      the event logger (before any other emit)

## 6. Implementation — analyze + LLM

- [x] `analyze()` collects session_meta into `Report.scenes` +
      `Report.scene_sources` + observed counters
- [x] `render_markdown` adds `**Scene:**` line in header
- [x] `scene_summary` helper; `scene_llm_context_paragraph` helper
- [x] `build_llm_prompt` prepends `[Scene context]` paragraph

## 7. Tests

- [x] `tests/test_scene.py` — 16 tests
- [x] `tests/test_event_log.py` — 5 new session_meta tests
- [x] `tests/test_cli.py` — 10 new scene + scene-aware-gate tests
- [x] `tests/test_analyze.py` — 11 new scene-consumption tests

## 8. Validation

- [x] `uv run pytest` — 826 passed
- [x] `uv run python scripts/tui_snapshot.py --mode regression` — green
- [x] `openspec validate --specs --strict` — 21/21
- [x] `openspec validate add-scene-awareness --strict` — valid

## 9. README + CHANGELOG + i18n

- [x] `README.md` — new `## Scenes` section
- [x] `docs/zh/README.md` — mirror
- [x] `CHANGELOG.md` — `## [Unreleased]` → `### Added` (4 bullets)
- [x] `docs/zh/CHANGELOG.md` — mirror
- [x] `src/diting/i18n.py` — scene name translations + chip + error msgs

## 10. Merge + archive

- [ ] PR open, reviewed, merged
- [ ] `/opsx:archive add-scene-awareness`
