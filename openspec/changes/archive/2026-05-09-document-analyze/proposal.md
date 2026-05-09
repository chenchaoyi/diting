# Document the `analyze` capability

## Why

`wifiscope analyze` is the user's primary "what went wrong last
night" tool. The heuristics it ships with (stale gateway, sustained
loss, repeated disassoc, weak roam targets, stir-during-spike) were
landed iteratively over the v0.7.0 / overnight-log work and the
contract is now load-bearing: users have shell pipelines that
parse the report, the loss-percent format-detection logic
(0..1 fraction vs 0..100 percent) silently corrects old logs, and
the duration-formatting honesty rule ("never round 30s up to 1 min")
came from a real user complaint. Backfill captures these as
contracts so a refactor doesn't reintroduce the rounding bug.

## What Changes

- Introduce capability `analyze`.
- No code changes — backfill from `src/wifiscope/analyze.py` and
  the `_run_analyze` CLI entry in `cli.py`.

## Capabilities

### New Capabilities
- `analyze`: pure-rules report shape, heuristic catalogue,
  loss-percent format auto-detection, duration-formatting honesty,
  TODO-section gating.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/analyze/spec.md`
- Cross-cuts with: `events` / `event-log` (consumes the JSONL
  stream), `cli` (wires the `analyze` subcommand)
- Future impact: adding a heuristic is a no-spec-change PR (the
  framework permits it). Removing one, changing the report's
  section ordering, or relaxing the rules-only stance MUST file a
  MODIFIED Requirement
