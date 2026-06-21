## Why

`diting setup` (v2.0.1) verifies grants with the read-only probes, but the Python
side collapses each probe to a bool (authorized vs not) and then, after a 12 s
grace window, treats any still-missing required grant as DENIED — opening System
Settings. That conflates `notDetermined` (the prompt hasn't been answered yet)
with `denied` (a settled refusal macOS won't re-prompt). On a fresh install the
helper rebuild resets grants to `notDetermined`; setup then wrongly announces
"Location Services looks denied" ~12 s in and yanks the user to System Settings
before they can act on the helper's prompt. The read-only probes already return
distinct exit codes (0 authorized · 3 denied · 4 notDetermined · 5 restricted) —
setup must use that distinction.

## What Changes

- `permission.probe()` reports each of Location / Bluetooth as a STATUS string
  (`authorized` / `denied` / `not_determined` / `restricted` / `unknown`) from the
  read-only probe's exit code, instead of a bool. (Fallback functional probes on
  an older helper map to `authorized` / `unknown`, since they can't distinguish.)
- `diting setup` interactive loop:
  - `authorized` (both required) → done;
  - `not_determined` / `unknown` → keep WAITING (the helper's prompt is pending) —
    no Settings, no false "denied";
  - `denied` / `restricted` → open the Privacy pane + instructions once (the only
    case macOS won't re-prompt), and keep polling so enabling it is detected.
  Drop the 12 s "grace → assume denied" heuristic; denial is now read directly.
- `setup --json` keeps its boolean contract (`location`/`bluetooth` = authorized?)
  and gains nothing breaking; the richer status drives only the interactive flow.

## Capabilities

### Modified Capabilities
- `permission-setup`: `setup` SHALL distinguish a pending (`not_determined`) grant
  from a settled denial — waiting on the former, routing only the latter to
  System Settings — so it never mislabels a not-yet-answered prompt as denied.

## Impact

- `src/diting/_helper.py` — `location_status` / `bluetooth_authorization_status`
  return the status string (existing bool wrappers delegate to them).
- `src/diting/permission.py` — `probe()` returns status strings; `is_ready`
  checks `== "authorized"`.
- `src/diting/cli.py` — `_run_setup` loop routes on `denied`/`restricted` only,
  waits on `not_determined`; `_setup_state_json` / status display updated.
- `tests/` — `test_setup.py` updated for status strings + denied-vs-pending.
  Update `tests/TESTING.md` (EN + ZH) first.
- Helper unchanged (the probes already return the distinct codes). No release-
  blocking helper rebuild; ships as a patch.
