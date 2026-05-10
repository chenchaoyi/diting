## 1. Phase A — audit (this commit)

- [ ] 1.1 Read `design/diting-design/README.md`,
      `design/diting-design/colors_and_type.css`, and
      `design/diting-design/SKILL.md` end-to-end. Note the canonical
      hex tokens, mono font names, and voice rules.
- [ ] 1.2 Survey color usage: grep every hex value (`#[0-9a-fA-F]{3,8}`)
      in `src/diting/`, any Textual `.tcss` file, `docs/_capture_preview.py`,
      `docs/preview*.svg`, `docs/logo.svg`, snapshot fixtures, and the
      `design/diting-design/assets/` it copies from. Compare each against
      the named tokens in `colors_and_type.css`. Flag mismatches.
- [ ] 1.3 Survey type: grep `font-family`, `font:`, and any `Style(...)` /
      `Pretty` / `Text` font references in `src/diting/`. Flag any face
      other than Fira Code / JetBrains Mono / SF Mono / Menlo /
      ui-monospace / generic monospace fallbacks on mono surfaces.
- [ ] 1.4 Survey voice / copy: scan `src/diting/i18n.py` (EN keys + ZH
      values), `README.md`, `docs/zh/README.md`, `DEVELOPMENT.md`,
      `CHANGELOG.md`, `tests/TESTING.md`, `docs/zh/TESTING.md`,
      `docs/workflow.md`, `docs/zh/workflow.md`, the help-modal /
      basics-modal copy in i18n, and the README for: capitalised
      `Wifiscope` / `Diting` / `DITING` in prose; first-person plural
      (`we`, `our`); emoji; empty states that aren't `(parenthesised
      italic)`; protocol terms not in the documented form (RSSI in
      `dBm` not `db`, σ instead of "stddev", etc.).
- [ ] 1.5 Survey iconography: grep `import.*[Ii]con`, `from textual` for
      icon-y imports, scan `docs/preview*.svg` and `docs/logo.svg` for
      embedded glyph SVG, and verify the only brand mark referenced is
      `design/diting-design/assets/logo-mark.svg` (or `logo.svg` for the
      wordmark).
- [ ] 1.6 Survey layout: read `src/diting/tui.py` for panel
      construction / border style / footer widget. Confirm panels use
      heavy 1px orange box-drawing borders with square corners; confirm
      footer is always pinned and always shows active key bindings;
      flag any rounded "card" containers, drop shadows other than the
      two allowed, or panel constructions that don't match the spec.
- [ ] 1.7 Write `design/audit.md` with one section per category
      (Voice / Colors / Type / Iconography / Layout). Each section
      opens with a Markdown table — `# | file:line | rule | severity
      | proposed fix`. Severities: blocker / should-fix / nice-to-have.
      Cite the rule by `SKILL.md` line number or `README.md` section
      heading.
- [ ] 1.8 Re-run `openspec validate design-system-audit --strict`
      — should pass with the new tui-shell delta.
- [ ] 1.9 Commit Phase A: `chore(design-audit): scaffold audit report`.
      Push to `chore/design-system-audit`. Open PR. **Stop.**

## 2. Phase B — triage (maintainer)

- [ ] 2.1 Maintainer reads `design/audit.md`, marks each finding's
      disposition in-place: `accept` (apply now), `defer` (out of
      scope for this PR), or `reject` (audit was wrong). Add a
      `note:` line on rejections so the next audit doesn't re-raise.
- [ ] 2.2 Maintainer commits the triage edits to the same branch.
      The PR description tracks which findings are accepted before
      Phase C runs.

## 3. Phase C — apply (one commit per logical group)

These tasks are populated AFTER triage. Default plan is one commit
per category in this order — adjust based on what's accepted:

- [ ] 3.1 Voice / copy fixes (i18n + docs).
- [ ] 3.2 Color fixes (tui.py + theme + snapshot regen if needed).
- [ ] 3.3 Type fixes (font fallback chain alignment if anything
      diverges).
- [ ] 3.4 Iconography fixes (drop emoji, drop unauthorised icon
      imports).
- [ ] 3.5 Layout fixes (panel border / corner / shadow / footer).
- [ ] 3.6 After each group commit, update the corresponding finding
      lines in `design/audit.md` to `applied: <commit-sha>`.

## 4. Wrap-up

- [ ] 4.1 Run all four CI gates locally: `uv run pytest`,
      `uv run python scripts/tui_snapshot.py --mode regression --check`,
      `openspec validate --specs --strict`,
      `openspec validate design-system-audit --strict`.
- [ ] 4.2 If any preview SVGs got regenerated during Phase C
      (e.g. due to color fixes flowing through `make preview`), confirm
      the diff is clean and intentional.
- [ ] 4.3 Wait for CI green. Merge.
- [ ] 4.4 `openspec archive design-system-audit` — applies the
      tui-shell delta into canonical specs.
- [ ] 4.5 If `design/audit.md` has un-`applied` findings remaining
      (deferred / rejected), leave the file in place as known
      divergence. Otherwise the maintainer can delete it.
