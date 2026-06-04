# Tasks

## 1. Fix the frozen build
- [x] 1.1 `scripts/build_frozen.py` — add `--collect-all nacl`, `--collect-all
  cffi`, `--hidden-import _cffi_backend`; extract `_pyinstaller_cmd()` for
  testability.

## 2. Verify
- [x] 2.1 Fresh frozen build contains `_internal/_cffi_backend.*.so` +
  `_internal/nacl/_sodium.abi3.so`; `dist/diting/diting companion status`
  exits 0 (no crash).

## 3. Guard + docs
- [x] 3.1 `tests/test_build_frozen.py` — assert the command keeps the nacl /
  cffi / `_cffi_backend` collection (CI does no per-PR frozen build).
- [x] 3.2 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `installation` row.

## 4. Gates
- [x] 4.1 `uv run pytest`, `openspec validate --specs --strict`,
  `openspec validate fix-frozen-companion-crypto --strict`.
