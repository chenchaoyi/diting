## Why

The install-time permission flow looks unfinished and feels slow:

- **The helper window renders badly.** Its content stack sets
  `translatesAutoresizingMaskIntoConstraints = false` but adds no constraints,
  so AppKit drops it at the bottom-left origin at its intrinsic size — the text
  is jammed into the bottom-left corner under a large empty void, with no app
  icon and flat, marker-prefixed status lines. It reads as unprofessional.
- **The window appears only after a multi-second stall.** `diting setup` runs a
  blocking initial readiness probe (the Location read waits up to its 4 s
  registration-settle timeout on a fresh install) BEFORE it opens the bundle, so
  the permission window does not show until that probe returns.
- **The installer's terminal output is ragged.** `diting setup`'s human output
  prints flush-left while the installer frames everything else with indentation,
  so the setup lines break the installer's visual alignment.

## What Changes

- **Redesign the helper status window** (`HelperAppDelegate`): top-aligned Auto
  Layout pinned to the top of the content view (no void), the diting app icon at
  the top, a bold title, a secondary-color explanatory paragraph, and one status
  row per permission — each with a color-coded leading glyph (pending /
  in-progress / granted / denied) using the diting brand orange for the active
  step. The window sizes itself to fit its content.
- **Open the helper window promptly.** `setup` opens the bundle before any
  blocking verification probe; the interactive readiness pre-check uses a short
  Location settle (via a new `DITING_LOC_SETTLE` helper env) so it cannot stall
  the window. The accurate default settle is kept for `--json` / non-interactive
  reads.
- **Indentable setup output.** When `DITING_SETUP_INDENT=<n>` is set, `setup`
  left-pads its human terminal output by n spaces; `install.sh` sets it so the
  setup lines align under the helper step. `--json` is unaffected.

## Impact

- Specs: `macos-helper` (window appearance), `permission-setup` (prompt
  promptness + indentable output).
- Code: `helper/Sources/diting-tianer/main.swift` (window rewrite +
  `DITING_LOC_SETTLE`), `src/diting/_helper.py` + `permission.py` (settle
  override), `src/diting/cli.py` (`_run_setup` reorder + indent), `install.sh`
  (set `DITING_SETUP_INDENT`). Needs a helper rebuild.
