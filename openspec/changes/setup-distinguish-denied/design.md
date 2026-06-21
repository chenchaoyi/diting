## Context

The read-only helper probes return `exit 0 authorized · 3 denied · 4
notDetermined · 5 restricted`. `permission.probe` collapsed exit==0 to a bool, so
`setup` could not tell "not answered yet" from "refused", and its 12 s grace
heuristic assumed the latter. The helper rebuild between releases resets grants
to `notDetermined`, which is exactly the case that got mislabeled.

## Goals / Non-Goals

**Goals:** never call a pending grant "denied"; wait for the prompt; route only a
real denial to Settings.

**Non-Goals:** changing the helper (probes already expose the codes); changing the
`setup --json` boolean contract; the TUI path.

## Decisions

### D1 — Status strings, not bools
`probe()` returns `location`/`bluetooth` ∈ {`authorized`, `denied`,
`not_determined`, `restricted`, `unknown`}. `_helper.location_status` /
`bluetooth_authorization_status` map the exit code; the old `*_authorized` bools
delegate (`== "authorized"`). Fallback functional probes (old helper) → `True →
authorized`, `False → unknown` (indistinguishable), so setup waits rather than
mislabels.

### D2 — Loop routes on settled denial only
Per poll: ready → done; a required grant in {`denied`, `restricted`} → open its
Privacy pane once + instructions, keep polling (so toggling it on is detected);
`not_determined` / `unknown` → keep waiting to the timeout. No grace-window
denial assumption.

### D3 — JSON unchanged
`setup --json` still emits booleans (`location`/`bluetooth` = `status ==
"authorized"`); the status detail is internal to the interactive loop.

## Risks / Trade-offs

- [A genuinely stuck `not_determined` (prompt never appears) now waits to timeout
  instead of bailing at 12 s] → Correct trade: better to wait for a pending prompt
  than to falsely declare denial; timeout still reports the state + guidance.
- [Old helper can't distinguish] → maps to `unknown` → setup waits (no false
  denial); same as functional-probe behavior, no regression.

## Open Questions
- None.
