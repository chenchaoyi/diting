## Why

The repo recently grew a canonical design system at
`design/diting-design/`:

- `README.md` — voice + visual + iconography rules
- `colors_and_type.css` — every color / font / spacing / radius /
  shadow token, with named CSS custom properties
- `SKILL.md` — entry point ("voice rules in one line: lowercase
  brand `diting`, you-not-we, exact protocol terms, no emoji,
  parenthesised italic empty states")
- `assets/logo-mark.svg` — the only brand mark (pixel-art beast)

`CLAUDE.md` already says any UI / marketing copy / docs / snapshot /
slide work for diting MUST follow this system. The codebase wasn't
audited against it when it was added, so the actual TUI / theme /
i18n / docs / snapshots may diverge from the rules. This change
makes the audit explicit, then applies the user-approved subset
of fixes.

The work is staged so it can't drift:

1. **Phase A — audit (this PR's first commit).** Read all three
   canonical files, walk the codebase, write a per-finding report
   to `design/audit.md` covering voice/copy, colors, type,
   iconography, and layout. **No code changes.**
2. **Phase B — triage (gate).** Stop. Wait for the maintainer to
   mark each finding as accept / defer / reject in `design/audit.md`.
3. **Phase C — apply (subsequent small commits).** Apply only the
   accepted fixes, one logical group per commit so review stays
   tractable. Reuse tokens from `colors_and_type.css`; copy assets
   out of `assets/`; don't redraw the logo or invent new colors.

## What Changes

- **New file**: `design/audit.md` — structured per-finding report
  with `file:line · rule · severity (blocker / should-fix /
  nice-to-have) · proposed fix` columns, grouped by category.
- **No code touched in Phase A.** This OpenSpec change is the
  vehicle; Phase A is just the audit document.
- **Phase B is a hard stop**, not a step automation can complete
  alone. Maintainer marks each finding's disposition in the
  audit report.
- **Phase C** lands one logical group per commit (e.g.
  "voice: lowercase diting normalisation", "colors: drop
  off-palette hex values from tui.py", "iconography: remove
  emoji from i18n catalog"). Each commit reuses tokens from
  `colors_and_type.css`; no new hex values, no new fonts, no new
  icons.
- **Spec impact**: `tui-shell` gains a new Requirement formalising
  design-system conformance. The Requirement is the policy that
  reviewers can cite when blocking off-palette hex values, emoji,
  ad-hoc capitalisation, or unauthorised icon imports in future
  PRs.

## Capabilities

### New Capabilities

None. The design system is policy that applies across existing
capabilities (`tui-shell`, `i18n`, …); we don't carve out a new
spec for it.

### Modified Capabilities

- `tui-shell` — adds one ADDED Requirement that codifies the
  design system as the source of truth for TUI visual language
  and TUI-adjacent doc copy. Concrete enforcement (specific hex
  values, specific fonts) lives in `design/diting-design/`,
  which the new Requirement points at — that way future palette
  changes don't need a spec amendment.

## Impact

- **Files touched in Phase A**: `design/audit.md` (new) and the
  OpenSpec change scaffolding under
  `openspec/changes/design-system-audit/`. Nothing else.
- **Files touched in Phase C** (after triage): TBD by the audit;
  likely candidates are `src/diting/tui.py` (theme + colors),
  `src/diting/i18n.py` (voice / strings), `docs/preview*.svg`
  and `docs/logo.svg` (if the audit flags off-palette values
  baked into snapshot title bars), and various README / docs
  if voice rules turn up violations.
- **Tests**: Phase C may need test fixture updates if hex values
  or string text changes are baked into asserts. Phase A doesn't.
- **CI gates**: pytest / regression / spec-strict / change-strict
  all pass on Phase A trivially; Phase C must keep them green.
- **External**: no version bump, no release.
