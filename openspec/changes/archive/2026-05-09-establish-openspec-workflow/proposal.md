# Establish OpenSpec workflow

## Why

Wifiscope started as a solo tool and grew several heavy capabilities in
quick succession (BLE deep ID, environment monitor, BLE detail modal,
per-protocol decoders, …). Until now design context lived in either:

- one-shot per-release briefs at `docs/specs/v0.x.0-*.md` (high signal,
  but whole-feature; no per-capability index)
- `git log` and PR descriptions (search-unfriendly)
- the maintainer's head (the riskiest place)

Neither generalises well to:

- **multiple capabilities under one PR** (e.g. last week's "schema-4
  helper passthrough + decoder framework + BLE detail modal" change
  touched four capabilities at once and the brief had to go in the
  PR body and a CHANGELOG entry)
- **future contributors** (Android / Linux ports, eventual second
  maintainer) who need a *capability* index, not a release log
- **safe refactor**: contracts the future code must still uphold

OpenSpec — same shape used in `~/StreetEye` — gives us a per-capability
spec index plus a reviewable delta unit per change. Same flow we'll use
forever.

## What Changes

- Introduce `openspec/` as the SDD home: `specs/` (canonical contracts),
  `changes/` (in-flight deltas), `changes/archive/` (history).
- Document the workflow in `openspec/AGENTS.md` (agent-facing rules)
  and `docs/workflow.md` (contributor-facing).
- Update `CLAUDE.md` to point at the workflow.
- Backfill the load-bearing capabilities into `openspec/specs/`, each
  via a `document-<capability>` archive change so the historical
  reasoning is preserved alongside the canonical spec.

This change itself is the workflow-establishment record — an archive
entry rather than a live spec, since "we use OpenSpec" is a process
fact, not a system contract.

## Capabilities

### New Capabilities

None. This change introduces no system requirements; it sets up the
process around them. The actual capability backfill is done by the
companion `document-<capability>` archive changes filed alongside this
one (same date prefix).

### Modified Capabilities

None.

## Impact

- New top-level directory: `openspec/`
- New file: `openspec/AGENTS.md` (workflow rules for agents)
- New file: `openspec/README.md` (human-friendly capability index)
- New file: `docs/workflow.md` (contributor-facing workflow guide)
- Updated: `CLAUDE.md` adds a "Workflow" section pointing to the above
- Companion archive changes filed under `openspec/changes/archive/`
  on the same date, one per backfilled capability. See README index.
- Old `docs/specs/v0.x.0-*.md` release briefs stay in place as
  historical reference but are no longer the source of truth — the
  per-capability `openspec/specs/<name>/spec.md` files are.
