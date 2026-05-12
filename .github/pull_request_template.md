<!--
Thanks for the PR. The checklist below mirrors docs/workflow.md.
Tick what applies; strike through (~~text~~) what doesn't.
-->

## Summary

<!-- 1–3 sentences: what changed and why. -->

## Branch + change

- [ ] Branched from latest `main` (`feature/*`, `fix/*`, `refactor/*`, or `chore/*`)
- [ ] OpenSpec change exists at `openspec/changes/<name>/` with `proposal.md`, `tasks.md`, `specs/<capability>/spec.md` (delta) — OR this PR is `chore/`-only and touches no behaviour
- [ ] `openspec validate <change> --strict` passes locally

## Tests

- [ ] Unit tests added / updated for new behaviour
- [ ] `tests/TESTING.md` updated where the test surface shifted (canonical test plan, EN + ZH)
- [ ] Subagent test run executed and clean (`/opsx:test`)
- [ ] CI is green (pytest matrix + regression + spec validation)

## Docs

- [ ] README updated if a user-facing surface changed
- [ ] EN ↔ ZH parity preserved: any string change in `i18n.py` keeps both sides aligned, any `docs/*.md` edit has a matching `docs/zh/*.md` update
- [ ] OpenSpec proposal's `## What Changes` accurately describes the PR (this is the source of truth for future release notes — `CHANGELOG.md` is updated only at release time, not per PR)

## Archive (post-merge)

- [ ] `/opsx:archive <name>` run after merge — delta applied to canonical specs, change moved to `openspec/changes/archive/<YYYY-MM-DD>-<name>/`
