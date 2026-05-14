## Why

Users running diting today can't tell which version they have without
poking at `pyproject.toml` (developer workflow) or
`~/.local/share/diting/` (curl-installed). There's no `diting --version`
flag, the TUI title bar just says `diting`, and `__version__` in
`src/diting/__init__.py` is stale ("0.5.0") because it's a hand-
maintained duplicate of `pyproject.toml`'s version. After a release —
or when triaging a bug report — "what version is this?" needs to be
answerable in one keystroke.

## What Changes

- `src/diting/__init__.py`: `__version__` SHALL be sourced from
  `importlib.metadata.version("diting")` so there is exactly one
  source of truth (`pyproject.toml`'s `version` field). The stale
  hard-coded `0.5.0` is removed.
- `cli.py`: new `--version` flag prints `diting <version>` to stdout
  and exits 0. Recognised at the top level before subcommand
  dispatch.
- `tui.py`: `App.title` becomes `diting v<version>` so the TUI's
  header always shows the running version.
- `--help` output (EN + ZH) mentions `--version`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `cli`: add `--version` to the recognised top-level flags.
- `tui-shell`: pin the App title to include the running version.

## Impact

- `src/diting/__init__.py`: 1-line change.
- `src/diting/cli.py`: argv parsing + help-text bullet for `--version`
  (EN + ZH).
- `src/diting/i18n.py`: ZH help-text bullet update (EN ↔ ZH parity).
- `src/diting/tui.py`: one assignment in `App.__init__` / similar.
- New unit tests under `tests/test_cli.py` (or wherever existing CLI
  smoke tests live) for `--version`; the TUI title assertion goes
  in `test_tui_smoke.py`.
- No new deps. `importlib.metadata` is stdlib.
