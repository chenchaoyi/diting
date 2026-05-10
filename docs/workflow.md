# diting Workflow

How a change to diting gets from idea to merged. Short version:
new branch → propose change → implement → self-test → CI → review →
archive. Skip any step and the PR doesn't get merged.

> **EN ↔ ZH parity**: this guide has a Chinese translation at
> [`docs/zh/workflow.md`](zh/workflow.md). Any edit to one MUST land
> with a matching edit to the other in the same PR.

## Branch layout — new branch is mandatory

Every change MUST land on a branch — no direct commits to `main`.
Cut the branch from latest `main`:

| Prefix | Use for |
|---|---|
| `feature/<name>` | new capability or extension |
| `fix/<name>` | bug fix |
| `refactor/<name>` | internal cleanup, no observable behaviour change |
| `chore/<name>` | tooling / deps / doc-only changes outside `openspec/` |

Branch names are short, descriptive, kebab-case (`feature/eddystone-decoder`,
`fix/airpods-modal-crash`). The PR template (`.github/pull_request_template.md`)
asks you to confirm the branch was cut from latest `main`; reviewers
will check.

Hot fixes to a broken `main` use `fix/`, not direct push. The
shorter the branch's life, the better — long-lived feature branches
mean painful rebases.

## Per-change spec workflow (OpenSpec)

Every behaviour-affecting branch carries an OpenSpec change. The
process is wired up to:

- `openspec` CLI (npm `@fission-ai/openspec`, install once via
  `npm install -g @fission-ai/openspec`)
- Claude Code slash commands `/opsx:propose`, `/opsx:apply`,
  `/opsx:sync`, `/opsx:archive`, `/opsx:explore` under
  `.claude/commands/opsx/`

You can run the workflow either via the CLI directly, via the slash
commands inside Claude Code, or by hand-authoring the markdown files
(the format is plain enough that the tooling is convenience, not
required).

### 1. Propose

Easiest path inside Claude Code:

```
/opsx:propose <kebab-name-or-description>
```

This scaffolds `openspec/changes/<name>/` with `.openspec.yaml` plus
`proposal.md` / `design.md` / `tasks.md` / `specs/<capability>/spec.md`.

CLI alternative:

```bash
openspec new change <kebab-name>
# then write the four files manually
```

Each change has four files:

| File | Content |
|---|---|
| `proposal.md` | **Why** + **What Changes** + **Capabilities** (New / Modified / Removed) + **Impact** (affected files, deps) |
| `design.md` | Decisions, rejected alternatives, risks |
| `tasks.md` | Implementation checklist (PR commits tick boxes) |
| `specs/<capability>/spec.md` | Spec **delta** — `### ADDED Requirement: ...`, `### MODIFIED Requirement: ...`, `### REMOVED Requirement: ...` |

If the change touches multiple capabilities, add one folder per
capability under `specs/`.

If the change is documentation-only (writing a spec for behaviour
that already exists in code), name the change `document-<capability>`
and cite source files in `proposal.md`.

### 2. Implement

Tick `tasks.md` items as commits land. Code under `src/`, tests
under `tests/`. Run `uv run pytest` locally before pushing.

### 3. Merge

PR merges to `main`. Tests must be green; the spec delta must read
cleanly against the canonical `openspec/specs/` (delta diff is part
of the PR review).

### 4. Archive

After merge, apply the spec delta into `openspec/specs/<capability>/spec.md`
and move the change directory.

Easiest path inside Claude Code:

```
/opsx:archive <change-name>
```

Or via CLI:

```bash
openspec archive <change-name>
```

Both:
- Apply `ADDED Requirement: …` → append (drop the prefix)
- Apply `MODIFIED Requirement: …` → replace the matching requirement
- Apply `REMOVED Requirement: …` → remove the matching requirement
- Move `openspec/changes/<change-name>` → `openspec/changes/archive/<YYYY-MM-DD>-<change-name>/`

The canonical specs become the new source of truth; the archive
holds the historical reasoning. A change directory never lives in
both places at once.

To validate before archiving:

```bash
openspec validate <change-name> --strict
```

## Capability vs change

- **Capability** = a long-lived behaviour contract. Lives at
  `openspec/specs/<capability>/spec.md`. Doesn't go away when a
  change lands; it gets updated.
- **Change** = a discrete unit of work. Has start (`proposal.md`)
  and end (archive entry) timestamps. Multiple changes can update
  the same capability over time.

Capabilities currently in the index live in `openspec/README.md`.

## Tests

Three layers, all in CI:

| Layer | Tool | Location |
|---|---|---|
| Unit | pytest | `tests/test_<module>.py` |
| TUI smoke | pytest + Textual `app.run_test` | `tests/test_tui_smoke.py` |
| Snapshot regression | `scripts/tui_snapshot.py --mode regression` | `snapshot-output/` |

The `live_*` snapshot scenarios (`--mode explore`) are real-Mac only
and not part of CI.

### Test design discipline

`tests/TESTING.md` is the **canonical test plan** — every automated
test corresponds to a row in that document. When you touch a test
surface, the order is:

1. Update `tests/TESTING.md` first (EN + the `docs/zh/TESTING.md`
   mirror) — describe the new / changed scenario in prose.
2. Translate the prose into a pytest case.
3. Run the case, watch it fail, write the production code, run
   again, watch it pass.

Adding a test without updating `tests/TESTING.md` is a documented
review-block.

### Spec → test mapping

Each capability under `openspec/specs/<name>/spec.md` SHALL have a
matching test file (or section within an existing file). When a
spec adds a Requirement with a Scenario, that Scenario SHALL show
up as a test case. The reverse is also true: a test case that
asserts behaviour not in any spec is a smell — either the behaviour
deserves a spec (file an `openspec/changes/document-<capability>`)
or the test is over-specifying.

### Self-test before push

Strict gating before the PR opens, in this exact order:

```bash
uv run pytest                                                    # 0 failures
uv run python scripts/tui_snapshot.py --mode regression          # 0 assertion failures
openspec validate --specs --strict                               # 15/15 pass
openspec validate <your-change> --strict                         # active change passes
```

If any of these fails, the PR does not open. CI runs all four;
running locally first saves a CI cycle.

### Subagent for test execution

Use `/opsx:test` (Claude Code slash command) to delegate the full
self-test to a sub-agent. It runs all four gates above, captures
output, and reports a pass / fail summary back to the main thread
without polluting the parent context with test logs. Useful when
the test run is long or when you want the parent agent to keep
working while tests cook.

## Local commands

```bash
uv run pytest                                              # full unit + smoke suite
uv run python scripts/tui_snapshot.py --mode regression    # synthetic regression
uv run python scripts/tui_snapshot.py --mode explore       # real env, /tui-audit
openspec validate --specs --strict                         # canonical specs
openspec list                                              # active changes
openspec view                                              # dashboard
```

## CHANGELOG + bilingual docs

`CHANGELOG.md` keeps user-facing release notes (English). Each
merged change that ships a user-visible behaviour gets a line under
`[Unreleased]`. The entry references the change name so readers can
drill into the archive. The Chinese mirror at
`docs/zh/CHANGELOG.md` SHALL be updated in the same PR.

### Bilingual rule (EN ↔ ZH parity)

diting ships a Chinese audience as a first-class concern; a
change that drops Chinese coverage is incomplete. In a single PR:

- Every `i18n.py` EN-key edit MUST update the matching ZH value.
- Every `docs/<file>.md` edit MUST land with a matching
  `docs/zh/<file>.md` edit (existing files: `README.md`, `TESTING.md`,
  `HELPER.md`, `CHANGELOG.md`, `workflow.md`, …).
- Every README user-visible section change MUST land with a matching
  `docs/zh/README.md` edit.
- New help/basics modal copy MUST be added to BOTH `_ZH` and the
  EN source on the same line — the file structure makes this
  natural.

The PR template's "Docs" section asks you to confirm parity; CI
does not currently lint for it but reviewers will. A follow-on
`feature/lint-bilingual-parity` change can automate the check.

## When to NOT use the OpenSpec flow

- Pure CHANGELOG, README, screenshot edits → `chore/` branch is fine,
  no `openspec/changes/` entry needed.
- Hot-fix to broken CI → `fix/` branch, prioritise the green build;
  if the fix encodes a contract worth preserving, file a follow-on
  `document-<capability>` change after the fact.
- Experimental spike scripts under `/tmp/` or `scripts/<name>_spike.py`
  — these are not contracts. Promote to a real capability + spec when
  the experiment graduates.
