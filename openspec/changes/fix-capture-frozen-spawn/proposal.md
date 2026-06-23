## Why

`diting capture start` is broken on the shipped (PyInstaller frozen) install.
`SessionStore.build_argv` always spawns `[sys.executable, "-m", "diting",
"stream", …]`. On the frozen binary `sys.executable` IS the `diting` binary,
which does not understand `-m` — it parses `-m` as a subcommand and exits with
`diting: unknown subcommand '-m'`, printing `--help`. So the detached stream dies
instantly, the capture file is never written, and `capture status` reports
`exited`. (Found live while setting up an overnight monitoring capture, which had
to be launched via `diting stream` directly as a workaround.)

## What Changes

- `build_argv` detects a frozen runtime (`getattr(sys, "frozen", False)`) and
  spawns the binary's own `stream` verb directly — `[sys.executable, "stream",
  …]` — instead of `-m diting stream`. The source / `uv run` path (where
  `sys.executable` is a real Python interpreter) keeps using `-m diting`.

## Impact

- Specs: `capture-sessions` (the detached spawn invocation).
- Code: `src/diting/sessions.py` (`build_argv`). Test:
  `test_sessions.py::test_build_argv_frozen_omits_dash_m`. Pure Python; fixes the
  feature for every released (frozen) install.
