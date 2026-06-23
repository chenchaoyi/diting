# Tasks

- [x] `SessionStore.build_argv`: spawn `[sys.executable, "stream", …]` when
      `sys.frozen`, else `[sys.executable, "-m", "diting", "stream", …]`
- [x] `test_sessions.py::test_build_argv_frozen_omits_dash_m`
- [x] `tests/TESTING.md` + `docs/zh/TESTING.md` row
- [x] all four CI gates
