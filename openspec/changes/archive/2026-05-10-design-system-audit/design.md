## Context

The design system at `design/diting-design/` was created recently
and isn't yet enforced anywhere. The codebase pre-dates it, so
some divergence is expected — old hex values that don't match the
canonical palette, occasional emoji in user-visible strings,
voice slips like `Wifiscope` (capital) or `we` (instead of `you`),
or stylistic decisions that don't map back to a token in
`colors_and_type.css`.

`CLAUDE.md` already directs every UI / docs / mock / slide / copy
task to follow the rules at `design/diting-design/`. The audit
turns that direction into an enforced contract.

## Goals / Non-Goals

**Goals:**

- Produce a structured audit at `design/audit.md` that a maintainer
  can triage in one sitting — every finding has file/line + rule
  citation + severity + proposed fix.
- Add one Requirement to `tui-shell` that turns the design system
  into a citable rule for future PR reviews.
- Stage the work so the maintainer's triage is a HARD STOP between
  audit and implementation. No fixes land without explicit
  per-finding approval.
- Keep Phase C commits small and topical so review remains
  tractable.

**Non-Goals:**

- **Don't redesign anything.** This audit treats the design
  system as fixed truth. The audit reports divergence from it,
  not "I think the system should also say…".
- **Don't redraw the logo.** `assets/logo-mark.svg` and the rest
  of `assets/` are sealed. Phase C copies assets out, never
  modifies them in place.
- **Don't invent new tokens.** Every Phase C color change must
  cite an existing CSS custom property in
  `colors_and_type.css`. If a use-case genuinely needs a new
  token, surface it in the audit and stop — don't pre-declare it.
- **Don't enforce the rules in code (lint / hook).** That's a
  separate change. This one writes the policy and applies the
  one-shot cleanup; future enforcement is its own scope.
- **No archive policy on `docs/specs/v0.x.x-*.md`** or other
  pre-OpenSpec historical drafts. Frozen.

## Decisions

### Audit categories — exactly the five the user named

Five sections in `design/audit.md`, no more:

1. **Voice / copy** — lowercase `diting`, second-person voice
   (you-not-we), no emoji, parenthesised italic empty states
   (`(scanning…)`), exact protocol terms (RSSI in dBm, MCS / NSS,
   σ for std-dev, `▁▂▃▄▅▆▇█` sparklines).
2. **Colors** — every hex value used in `tui.py`, any Textual
   `.tcss` file, snapshot fixtures, `docs/_capture_preview.py`,
   and any preview SVG. Compare against the named CSS custom
   properties in `colors_and_type.css`. Anything that isn't in
   the palette gets flagged with a proposed token to substitute.
3. **Type** — only Fira Code / JetBrains Mono allowed in mono
   surfaces (TUI, code blocks, snapshot SVG title bars). Any
   other family is a finding, including system-default leakage.
4. **Iconography** — no emoji. No Lucide / Heroicons / Material
   Symbols imports. Only `assets/logo-mark.svg` (or the wordmark
   `assets/logo.svg`) for brand placement. Unicode glyphs are
   allowed inline (σ, ↔, ⚠, sparkline blocks); decorative emoji
   are not.
5. **Layout** — panels MUST be heavy 1px orange box-drawing
   borders with square corners; no rounded "card" containers; no
   shadows except `--shadow-window` and `--shadow-modal`; the
   footer is always pinned and always shows the active key
   bindings.

Anything that doesn't fit one of these five buckets is dropped or
folded into the closest match. The audit is intentionally narrow.

### Severity rubric — three tiers, no half-tiers

- **Blocker** — actively wrong vs the design system AND visible
  to end users (e.g. emoji in a TUI panel, `Wifiscope` capital in
  the help modal subtitle, an off-palette hex on a panel border).
  Applied immediately on triage approval.
- **Should-fix** — divergent but not user-visible (e.g. internal
  comment uses `Wifiscope`, a hex value used in an unrendered
  test fixture). Batched into Phase C if approved.
- **Nice-to-have** — micro polish (e.g. an internal variable
  name that uses the old palette name, a docs example that
  could be tightened). May be deferred indefinitely.

The maintainer can override severities during triage. The audit
proposes; triage decides.

### Output format — Markdown table per category

Each of the five sections in `design/audit.md` opens with a
narrow tabular list:

```
| # | file:line | rule | severity | proposed fix |
|---|---|---|---|---|
| V1 | src/diting/tui.py:1234 | "no emoji" (SKILL.md L20) | blocker | drop `🛜` from … |
```

Citations point at the SKILL.md line or README.md section they
violate so the rule is one click away. The "proposed fix" column
is the smallest viable patch — not a redesign.

### One Requirement on `tui-shell`, not five

Resisting the temptation to scatter one Requirement per category
across `tui-shell` / `i18n` / others. The design-system-as-
source-of-truth is a single rule that applies to anything user-
visible; encoding it in one Requirement keeps it citable
without fragmenting policy.

### Phase B is a real stop

The implementation is split across two commits in this branch
*at minimum*:

1. The Phase A commit that adds `design/audit.md` and this
   change's scaffolding.
2. The maintainer's triage edits to `design/audit.md` (in-place,
   marking each finding accept / defer / reject).
3. Phase C commits, each landing a logical group of accepted
   fixes.

Phase C cannot start until commit 2 lands. The PR description
will spell this out and commit 2 is on the maintainer.

## Risks / Trade-offs

- **Risk**: the audit lands and then sits — triage never
  happens, fixes never apply.
  → **Mitigation**: the audit is the work product of Phase A.
  Even un-triaged it's useful documentation. The OpenSpec change
  archives once Phase A and at least one Phase C commit has
  landed; if the maintainer abandons Phase C, the change can be
  archived with the unapplied findings still in `design/audit.md`
  as known divergence.

- **Risk**: a Phase C commit batches too many findings and review
  stops being meaningful.
  → **Mitigation**: each commit covers one *category* AND ideally
  one *file group*. "Drop emoji from i18n catalog" is one commit;
  "normalise lowercase diting in docs" is another. The maintainer
  can request splits during review.

- **Risk**: a finding turns out to require more than a one-line
  fix (e.g. a panel that wasn't using box-drawing borders needs
  significant Textual restructuring).
  → **Mitigation**: such findings get downgraded to should-fix
  during triage and folded into a follow-up change. The audit
  surfaces them; this change isn't on the hook for unbounded
  fixes.

- **Trade-off**: the audit will likely mark the existing
  `docs/logo.svg` (still the wordmark + radar arcs) and the
  six baked-in snapshot SVG title bars as should-fix or
  blocker. Regenerating them is cheap (`make preview`); the
  logo redesign was already deferred per memory until domains
  are secured. Audit may flag the logo as nice-to-have so the
  domain timeline isn't blocked.

## Migration Plan

1. Phase A: write `design/audit.md`, this change's scaffolding.
   Validate strict, commit, push, open PR.
2. Pause for triage. Maintainer marks dispositions in
   `design/audit.md` and pushes a triage commit to the same
   branch.
3. Phase C: one commit per accepted-finding group. Each commit
   updates the corresponding line of `design/audit.md` to mark
   the finding `applied: <commit hash>`.
4. CI green on all Phase C commits before the PR merges.
5. Archive: `openspec archive design-system-audit` after merge.

If triage rejects every finding, the PR still lands the audit
document + the new Requirement; Phase C is a no-op.

## Open Questions

- **Phase C commit granularity** — one per category (5 commits
  max) or finer? Defer to maintainer preference at triage time;
  default plan is one per category.
- **Should `design/audit.md` survive after archive?** Yes — it's
  a project doc. If the maintainer wants it deleted post-fix,
  that's a one-line commit they can do directly.
