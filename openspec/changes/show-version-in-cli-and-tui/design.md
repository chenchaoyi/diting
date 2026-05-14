## Context

Two surfaces today are silent about which version of diting is
running: the CLI accepts `--help` but not `--version`, and the TUI
header just says `diting`. Meanwhile `__version__` in
`src/diting/__init__.py` is hand-maintained as `"0.5.0"` — it
hasn't been bumped through any of the v1.0.x cycle. The
`pyproject.toml` `version` field is the actual truth.

## Goals / Non-Goals

**Goals:**
- One keystroke (`diting --version`) tells the user / a bug
  reporter what version they're on.
- TUI always shows the version in its header — no key press needed.
- Single source of truth for the version string.

**Non-Goals:**
- Surfacing the helper bundle's version separately. The helper
  ships in the same tarball; its version is the same.
- A `--build-info` style verbose dump (commit SHA, build time).
- Showing version in `monitor`'s JSONL payload schema.

## Decisions

### D1 — Source the version from `importlib.metadata`.

`importlib.metadata.version("diting")` reads the installed
package's `version` field, which is set from `pyproject.toml` at
build time. This works both for:
- The frozen PyInstaller binary (PyInstaller bakes the dist-info).
- `uv run diting` from a developer checkout (uv's editable install
  also writes a dist-info record).

Hard-coding `__version__ = "1.0.8"` in `__init__.py` would just
recreate the v0.5.0 staleness problem the next time someone
forgets. `importlib.metadata` is stdlib (no dep), zero runtime cost.

Fallback for the (rare) case where dist-info is absent (e.g. a
contributor running scripts directly out of `src/` without
installing the package): catch `PackageNotFoundError` and return
`"0+unknown"`. The TUI and `--version` then render `0+unknown`,
which is a clear signal "this is not a real install" without
crashing.

### D2 — TUI title becomes `diting v<version>`.

Today: `self.title = "diting"`. The Textual header renders the
`title` on the left. Appending the version reads naturally in
both English and Chinese (the title is not translated; brand
name + version is a noun phrase that works as-is across
languages). The lowercase `v` prefix matches git-tag convention
(`v1.0.8`) without making the title scream.

The subtitle (which shows `view: ... · scan Ns · PAUSED`) stays
unchanged — it carries session state, not identity.

### D3 — `--version` is parsed before subcommand dispatch.

Convention: `diting --version` is allowed by itself; `diting
once --version` is rejected (subcommands don't carry a redundant
`--version`). Implementation: detect `--version` in the top-level
argv list before the subcommand selector runs; print + exit 0.

This is symmetric with how `--help` works today — top-level only.

## Risks / Trade-offs

- **[Risk]** `importlib.metadata.version("diting")` could fail in
  an unusual install layout. → Caught explicitly; falls back to
  `0+unknown` so the binary never crashes on `--version`.
- **[Risk]** Existing callers reading `diting.__version__` (none
  in-tree, but potentially in a downstream script) might rely on
  the string format. → The value still parses as a valid PEP 440
  version. The semantics only change from "stale hard-coded
  string" to "live read".
