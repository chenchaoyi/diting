# diting design-system audit — 2026-05-10

Codebase audited against `design/diting-design/`:

- `README.md` — voice + visual + iconography rules
- `colors_and_type.css` — every color / font / spacing / radius / shadow token
- `SKILL.md` — entry-point one-liner ("voice rules in one line: …")
- `assets/logo-mark.svg` (pixel-beast), `assets/logo.svg` (wordmark)

Severity ladder:

| | meaning | apply when |
|---|---|---|
| **blocker** | actively wrong vs design system AND visible to end users | on triage approval |
| **should-fix** | divergent but not user-visible, or low-prominence violation | batched into Phase C |
| **nice-to-have** | micro polish, internal-only | may be deferred indefinitely |

How to triage: edit each `disposition` cell to `accept` / `defer` / `reject`. Add a `note:` line on rejections so the next audit doesn't re-raise. After Phase C lands a fix, mark its row `applied: <commit-sha>`.

---

## 1. Voice / copy

| # | file:line | rule | severity | proposed fix | disposition |
|---|---|---|---|---|---|
| V1 | `README.md:51` | "always lowercase in running prose" (SKILL.md L20; README.md "Person & casing") | should-fix | `Diting fills that gap.` → `diting fills that gap.` | accept |
| V2 | `docs/workflow.md:1` | same | should-fix | `# Diting Workflow` → `# diting Workflow` (or `# diting · workflow`) | accept |
| V3 | `docs/workflow.md:219` | same | should-fix | `Diting ships a Chinese audience as a first-class concern` → `diting ships …` | accept |
| V4 | `docs/zh/workflow.md:3` | same — CJK title with capital | should-fix | `# Diting 开发流程` → `# diting 开发流程` | accept |
| V5 | `openspec/AGENTS.md:3` | same | should-fix | `Diting's spec / change workflow.` → `diting's spec / change workflow.` | accept |
| V6 | `CLAUDE.md:1` | same | should-fix | `# Diting (谛听) — agent / contributor brief` → `# diting (谛听) — agent / contributor brief` | accept |
| V7 | `openspec/specs/wifi-scanning/spec.md:29` | same | should-fix | `Diting SHALL surface the redacted-scan state` → `diting SHALL surface …` | accept |
| V8 | `README.md:79` | "you-not-we" (README.md "Person & casing") | should-fix | `for what we deliberately do not claim.` → `for what diting deliberately does not claim.` | accept |
| V9 | `README.md:294` | same | should-fix | `which we will not do.` → `which diting will not do.` | accept |
| V10 | `README.md:298` | same | should-fix | `We surface a binary` → `It surfaces a binary` (subject is the Environment line) | accept |
| V11 | `README.md:307` | same | should-fix | `what we honestly do with RSSI.` → `what diting honestly does with RSSI.` | accept |
| V12 | `README.md:313` | same | should-fix | `an invasive perturbation we deliberately avoid.` → `an invasive perturbation diting deliberately avoids.` | accept |
| V13 | `DEVELOPMENT.md:111` | "you-not-we" — DEVELOPMENT.md is contributor-facing so "we" is more defensible than in README | nice-to-have | Either keep ("we" reads natural for contributor narrative) or rewrite to match README's voice; defer per maintainer | accept |
| V14 | `DEVELOPMENT.md:138` | same | nice-to-have | `what we deliberately do *not* claim` → `what diting deliberately does *not* claim` (consistency with README change) | accept |
| V15 | `src/diting/tui.py:93` | "Empty states are full sentences. … Always parenthesised, always italic, always lowercase." (README.md "Vibe & examples") | should-fix | `t("not associated")` → `t("(not associated)")` and add the matching ZH catalog entry; keeps the existing `style="dim italic"` so only the string changes | accept |

**Notes for triage:**

- V1–V7 ask whether title-case `Diting` in `# Foo` headings violates "always lowercase". The SKILL.md is explicit ("Never `Diting`, never `DITING`") and the design system makes no markdown-title carve-out. Recommend accept all seven; the brand voice is unusually strict on this and the consistency win is real.
- V8–V12 are README.md "we" instances. README is the user-facing surface, so "we" violates the brand voice rules. V13–V14 are DEVELOPMENT.md (contributor-facing) where "we" is more defensible — flagged as nice-to-have so the maintainer can choose.
- V15 is a real TUI surface where the empty-state pattern is otherwise well-followed. Worth fixing.

---

## 2. Colors

The Python TUI does NOT use direct hex literals — every Textual `DEFAULT_CSS` block resolves through Textual's `$accent`, `$surface`, `$primary` etc. tokens. Rich-styled spans use named colors (`bold cyan`, `dim`, `bold yellow`). The actual hex values appear only in the rendered SVG snapshots (Textual's screenshot pipeline resolves the theme + bakes pixels into SVG).

A pure-source audit (grep `'#[0-9a-fA-F]{3,8}'` across `src/diting/`) returns zero hex literals. Good. The findings below are about what the rendered SVGs (`docs/preview*.svg`, `docs/logo.svg`) bake in.

| # | file:line | rule | severity | proposed fix | disposition |
|---|---|---|---|---|---|
| C1 | `docs/preview.svg`, `docs/preview-ble.svg`, `docs/preview-events.svg` and their `.zh.svg` counterparts | "Solid fills only. No full-bleed images, no patterns, no gradients." (README.md "Visual foundations" → "Backgrounds") and "every hex value … flagged unless in `colors_and_type.css`" | should-fix | 27 distinct hex values appear in the six preview SVGs that are NOT in `colors_and_type.css`: `#000000` `#003054` `#0a0a0a` `#0a1e2c` `#0b3a5f` `#160` (truncated `#160000`?) `#161616` `#191d21` `#1a1a1a` `#1c2024` `#2e5e68` `#455969` `#476419` `#484848` `#4a4a4a` `#4a4c4d` `#595953` `#595a5a` `#63696e` `#646464` `#6c0a30` `#704717` `#704d1c` `#9e9e9e` `#a0a0a0` `#c5c6c7` `#e6e6e6`. These are emergent from Textual's render pipeline (signal-bar gradients, semantic-color darkenings, dim-text variants). Most cannot be flattened without breaking the rendered look. **Recommendation:** accept the divergence as a known-honest list and add a note to `design/diting-design/colors_and_type.css` that says "Textual's render pipeline produces additional intermediate shades on signal bars, semantic-state backgrounds, and 256-color text fallbacks; those are out of scope for the canonical palette." Alternative: tighten `make preview` to flatten anything outside the canonical palette, but that risks visual regression. | accept |
| C2 | `docs/logo.svg` (the README hero) | "the only image asset that ships is the logo" + "the pixel-art beast in `assets/logo-mark.svg` is the only mark" (CLAUDE.md "Design") | **blocker** | `docs/logo.svg` is a placeholder with radar arcs + Fira Code wordmark — not the canonical pixel-art beast. Replace with a copy of `design/diting-design/assets/logo.svg` (which combines the pixel-beast + wordmark + 谛听 in Songti SC). Asset is 1.4 KB; `cp design/diting-design/assets/logo.svg docs/logo.svg`. **Do NOT redesign or modify the source asset.** | accept |

---

## 3. Type

| # | file:line | rule | severity | proposed fix | disposition |
|---|---|---|---|---|---|
| T1 | `docs/preview.svg:32`, `docs/preview-ble.svg:32`, `docs/preview-events.svg:32`, `docs/preview.zh.svg:32`, `docs/preview-ble.zh.svg:32`, `docs/preview-events.zh.svg:32` | "only Fira Code / JetBrains Mono in mono surfaces; no second face leaking into the TUI" + "One font. Fira Code at 20px / 24.4px line-height is the default." (README.md "Visual foundations" → "3.") | should-fix | Every preview SVG has `font-family: arial;` on its `.terminal-XXX-title` class — that's the small grey title bar text at the very top of the snapshot ("diting"). Textual's snapshot pipeline defaults to Arial for that band. Either: **(a)** override Textual's screenshot CSS at capture time in `docs/_capture_preview.py` to substitute `font-family: 'JetBrains Mono', 'Fira Code', monospace;` for the title class; or **(b)** post-process the SVG output via `sed -i '' 's/font-family: arial;/font-family: '\''JetBrains Mono'\'\','\''Fira Code'\'\','\''SF Mono'\'\','\''Menlo'\'\''monospace;/' docs/preview*.svg` after `make preview`. Option (a) is cleaner; option (b) keeps the change tiny if Textual doesn't expose a hook. | accept |

The TUI's `DEFAULT_CSS` blocks in `src/diting/tui.py` reference no specific font face — they inherit from the terminal emulator. Mono surfaces in the actual TUI are therefore whatever the user's terminal is configured for. ✅ no second face leaks from source.

---

## 4. Iconography

| # | file:line | rule | severity | proposed fix | disposition |
|---|---|---|---|---|---|
| I1 | `README.md:6`, `docs/zh/README.md:6` | "the pixel-art beast in `assets/logo-mark.svg` is the only mark" (CLAUDE.md "Design") + "use this and only this for brand placement" (README.md "Iconography" → "2.") | **blocker** (overlaps with C2) | Same fix as C2 — replace `docs/logo.svg` (or add `docs/logo-mark.svg`) sourced from `design/diting-design/assets/`. The README hero currently shows a redesigned mark that the design system explicitly forbids. | accept |

| Survey | result |
|---|---|
| Lucide / Heroicons / Material Symbols imports anywhere under `src/` | none |
| Emoji in `src/diting/i18n.py` user-visible strings | none |
| `⚠`, `★`, `→`, `↔`, `σ`, `▁▂▃▄▅▆▇█` glyphs | present and design-system-approved (functional Unicode, not emoji) |

Iconography is otherwise clean.

---

## 5. Layout

| Survey | result |
|---|---|
| Panel border style across all `DEFAULT_CSS` blocks in `src/diting/tui.py` | uniformly `border: heavy $accent` — heavy box-drawing border in brand orange ✅ |
| Rounded "card" containers (border-radius) | none in source ✅ |
| Drop shadows on panels | none in source ✅ |
| `--shadow-window` / `--shadow-modal` usage | none directly (would only apply to HTML-rendered surfaces, not the TUI itself) — N/A for the TUI |
| Footer dock | `GroupedFooter` at `tui.py:3208` with `dock: bottom`, `height: 1`, always pinned ✅ |
| Footer always shows active key bindings | yes — `refresh_layout()` at `tui.py:3245` rebuilds the binding list on every state change ✅ |
| Modal close hint | every modal has its own inline close hint (`Esc or h to close`) and the GroupedFooter auto-hides under modals via Textual's standard layering ✅ |

No layout findings. The TUI's structural compliance with the design system is solid — likely because the design system was distilled from this TUI in the first place.

---

## Summary

| category | findings | of which blocker | of which should-fix | of which nice-to-have |
|---|---|---|---|---|
| Voice / copy | 15 | 0 | 13 | 2 |
| Colors | 2 | 1 (C2) | 1 (C1) | 0 |
| Type | 1 | 0 | 1 | 0 |
| Iconography | 1 | 1 (I1, dup of C2) | 0 | 0 |
| Layout | 0 | 0 | 0 | 0 |
| **total** | **19** (18 unique — C2 and I1 overlap) | **1 unique** | **15** | **2** |

The single blocker (the README hero using a non-canonical logo) is also the only finding that's plainly user-visible at first glance. Everything else is should-fix-grade — meaningful but not embarrassing.

Recommended Phase C grouping if all should-fix items are accepted:

1. **One commit: `docs(brand): use canonical logo`** — fix C2 / I1 (cp design-system asset over `docs/logo.svg`)
2. **One commit: `docs(voice): lowercase brand in titles + prose`** — fix V1–V7 (lowercase `diting` in markdown titles + spec narrative)
3. **One commit: `docs(voice): you-not-we across README`** — fix V8–V12 (rewrite README's "we" instances)
4. **One commit: `tui(voice): parenthesise empty states`** — fix V15 (`(not associated)` + ZH mirror)
5. **One commit: `docs(brand): override snapshot title font`** — fix T1 (font-family arial → JetBrains Mono / Fira Code in preview SVGs)

C1 is best left as a known-divergence note in `colors_and_type.css` rather than a code change — flatten-or-not is a judgement call for the maintainer.

V13–V14 (DEVELOPMENT.md "we") deferred unless the maintainer wants strict consistency with README.

---

## Triage worksheet

Mark each row's `disposition` column above with one of:

- `accept` — fix in Phase C
- `defer` — out of scope for this PR; leave for a future audit
- `reject` — audit was wrong; add a `note:` line below the row explaining why

Once triaged, this branch's next commit applies only the `accept`-marked rows, one logical group per commit.
