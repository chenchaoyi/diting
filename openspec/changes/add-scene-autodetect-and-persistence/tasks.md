# tasks — add-scene-autodetect-and-persistence

## 1. Spec

- [x] Draft proposal, design, tasks
- [x] Delta on `specs/scenes/spec.md`
- [x] Delta on `specs/event-log/spec.md`
- [x] Delta on `specs/tui-shell/spec.md`

## 2. Test plan

- [x] Extend `tests/TESTING.md` `scenes` section — 3 new rows
- [x] `docs/zh/TESTING.md` — EN ↔ ZH parity

## 3. Implementation — scenes_config

- [x] New `src/diting/scenes_config.py` — `SceneAssignment`,
      `SceneRegistry`, `load_scenes_registry`, lookup helpers
- [x] `default_scenes_path()` → `./scenes.yaml` (cwd)
- [x] `DITING_SCENES_FILE` env override

## 4. Implementation — heuristic

- [x] `src/diting/scene.py` — `SOURCE_YAML`, `SOURCE_AUTO`
- [x] `classify_environment(security, bssid_count, ssid)` heuristic

## 5. Implementation — CLI startup

- [x] `src/diting/cli.py` — `_resolve_scene_at_startup`,
      `_gateway_mac_for_router_ip`, `_emit_scene_banner`
- [x] Threaded into `main()` (replaces direct `resolve_scene` call)
- [x] `DITING_SCENE_QUIET=1` suppresses banner

## 6. Implementation — i18n

- [x] EN catalog: auto-detect + pinned banner strings
- [x] ZH catalog: 自动识别场景 / 锁定场景

## 7. Tests

- [x] `tests/test_scenes_config.py` (new) — 12 tests
- [x] `tests/test_scene.py` — 10 new heuristic tests
- [x] `tests/test_cli.py` — 8 new startup + banner tests

## 8. Validation

- [x] `uv run pytest` — 856 passed (+30 from this PR)
- [x] `uv run python scripts/tui_snapshot.py --mode regression` — green
- [x] `openspec validate --specs --strict` — 22/22
- [x] `openspec validate add-scene-autodetect-and-persistence --strict` — valid

## 9. README + CHANGELOG + scenes.example.yaml

- [x] `scenes.example.yaml` (new, repo root)
- [x] `.gitignore` — added `scenes.yaml`
- [x] `README.md` — extended `## Scenes` with auto-detect / yaml subsections
- [x] `docs/zh/README.md` — mirror
- [x] `CHANGELOG.md` — `## [Unreleased]` → `### Added`
- [x] `docs/zh/CHANGELOG.md` — mirror

## 10. Merge + archive

- [ ] PR open, reviewed, merged
- [ ] `/opsx:archive add-scene-autodetect-and-persistence`
