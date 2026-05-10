# OpenSpec — agent rules

Diting's spec / change workflow. Read this once before touching any
file under `openspec/`.

## Tooling

- CLI: `openspec` (npm-installed `@fission-ai/openspec`, currently 1.2.0).
  Validate, list, scaffold, archive — all via this binary. `openspec --help`
  for the full surface.
- Claude Code slash commands under `.claude/commands/opsx/`:
  - `/opsx:explore` — kick the tires on an idea before commit
  - `/opsx:propose <name-or-description>` — scaffold a new change
    (proposal + design + tasks + spec deltas) end-to-end
  - `/opsx:apply <name>` — implement the tasks of an active change
  - `/opsx:sync <name>` — apply spec deltas to canonical specs
    without archiving (for iteration mid-PR)
  - `/opsx:archive <name>` — apply deltas + move to
    `openspec/changes/archive/<date>-<name>/`

## What lives here

```
openspec/
├── AGENTS.md                 ← this file (rules for agents)
├── README.md                 ← human-friendly capability index
├── specs/                    ← canonical, in-force specifications
│   └── <capability>/spec.md
└── changes/                  ← proposed / in-flight / archived deltas
    ├── <change-name>/        ← in flight (open PR)
    │   ├── proposal.md
    │   ├── design.md
    │   ├── tasks.md
    │   └── specs/<capability>/spec.md     ← delta only (ADDED / MODIFIED / REMOVED)
    └── archive/<YYYY-MM-DD>-<change-name>/ ← merged + applied
        └── (same four files preserved as historical record)
```

## The lifecycle

1. **Propose**. Create `openspec/changes/<kebab-name>/` with the four
   files. Spec deltas inside use ADDED / MODIFIED / REMOVED Requirement
   sections so the diff against canonical `openspec/specs/` is obvious.
2. **Implement**. Tasks in `tasks.md` get checked off as PR commits
   land. Tests live in `tests/` as usual.
3. **Merge**. PR merges to `main`.
4. **Archive**. Apply the delta into `openspec/specs/<capability>/spec.md`
   (canonical specs become the new source of truth). Move the change
   directory to `openspec/changes/archive/<YYYY-MM-DD>-<change-name>/`.

A change directory **never** lives in both places at once. After
archive, the canonical `openspec/specs/` reflects the merged state and
the archive holds the historical reasoning.

## Spec file format

Each `spec.md` follows the same shape — both canonical specs and
deltas inside changes. Use SHALL / SHOULD / MAY (RFC 2119 keywords)
and WHEN / THEN scenarios.

```markdown
# <capability> Specification

## Purpose
One paragraph: what contract this capability defines, and which
upstream consumers depend on it.

## Requirements

### Requirement: <one sentence using SHALL>
Body text expanding the requirement.

#### Scenario: <short label>
- **WHEN** <input / event>
- **THEN** <observable behaviour>
```

Inside a change `specs/<capability>/spec.md`, the requirements are
prefixed with their delta kind:

```markdown
### ADDED Requirement: ...
### MODIFIED Requirement: <previous wording>
(new body)
### REMOVED Requirement: ...
```

The archive step is a pure text apply against canonical `spec.md`.

## Naming conventions

- Capability names: kebab-case nouns describing a *behaviour
  contract*, not a code file. `bluetooth-scanning` ✓ — `ble-py` ✗.
- Change names: kebab-case verb phrases. `add-ruuvi-decoder` ✓ —
  `ruuvi` ✗. Use `document-<capability>` for pure-backfill changes
  that introduce a spec without changing code.
- Archive directories: `YYYY-MM-DD-<change-name>` so chronology is
  obvious in `ls -1`.

## When in doubt

- If a change is documentation-only (writing a spec for behaviour
  that already exists in code), use `document-<capability>` and
  cite the source files in `proposal.md` under "Affected code".
- If a change introduces both new code and a new capability, the
  proposal lives in `openspec/changes/`; the capability gets a
  spec under `specs/<capability>/spec.md` *inside the change*
  (ADDED Requirements). Archive merges that delta into
  `openspec/specs/<capability>/spec.md`.
- If a change touches multiple capabilities, the change's
  `specs/` subdir holds one folder per capability.

## What this workflow is NOT

- Not a ticketing system. Tasks lists are local to a change; if you
  need a backlog, that's `docs/roadmap.md` or a tracker.
- Not a freeform design dump. `design.md` captures load-bearing
  decisions and rejected alternatives, not stream-of-consciousness.
- Not a substitute for code review. Specs describe contracts; PRs
  still get reviewed for implementation quality.
