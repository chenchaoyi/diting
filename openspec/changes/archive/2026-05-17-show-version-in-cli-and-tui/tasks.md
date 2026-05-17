## 1. Single source of truth

- [x] 1.1 Rewrite `src/diting/__init__.py` to compute `__version__` lazily via `importlib.metadata.version("diting")`, with a `PackageNotFoundError` fallback to `"0+unknown"`.

## 2. CLI `--version`

- [x] 2.1 In `src/diting/cli.py`, detect `--version` in the top-level argv list before subcommand dispatch. On match, print `diting <version>` to stdout and exit 0.
- [x] 2.2 Add a `--version` bullet to the EN `--help` block in `cli.py`.
- [x] 2.3 Add the matching `--version` bullet to `src/diting/i18n.py`'s ZH `--help` block.

## 3. TUI title

- [x] 3.1 In `src/diting/tui.py` `DitingApp.__init__`, change `self.title = "diting"` to `self.title = f"diting v{__version__}"` (import `__version__` from `diting`).

## 4. Tests

- [x] 4.1 Add a CLI unit test under `tests/` asserting `diting --version` prints `diting <X.Y.Z>` matching the importlib-metadata version and exits 0.
- [x] 4.2 Extend `tests/test_tui_smoke.py` with an assertion that `app.title.startswith("diting v")` after `DitingApp` constructs.

## 5. Gates

- [x] 5.1 `uv run pytest` passes (existing + new tests).
- [x] 5.2 `uv run python scripts/tui_snapshot.py --mode regression` passes.
- [x] 5.3 `openspec validate --specs --strict` passes.
- [x] 5.4 `openspec validate show-version-in-cli-and-tui --strict` passes.
