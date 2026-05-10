## ADDED Requirements

### Requirement: TUI visual language SHALL conform to the design system
The diting TUI and any UI-adjacent surface (README, marketing snapshots, modals, slide decks, docs site) SHALL conform to the design system at `design/diting-design/`. That directory (`README.md`, `colors_and_type.css`, `SKILL.md`, `assets/`) is the single source of truth for visual language and copy voice. Reviewers MAY block any PR that introduces:

- a hex value not declared as a CSS custom property in
  `design/diting-design/colors_and_type.css`
- a font face other than Fira Code or JetBrains Mono on a mono
  surface (TUI, snapshot title bars, code blocks)
- emoji in user-visible strings (Unicode glyphs like `σ`, `↔`,
  `⚠`, `▁▂▃▄▅▆▇█`, `→` ARE NOT emoji and ARE allowed)
- imports of icon libraries (Lucide, Heroicons, Material
  Symbols, etc.); the only mark is `design/diting-design/assets/logo-mark.svg`
  (or the wordmark `logo.svg`)
- copy that capitalises the brand (`Diting`, `DITING`, `Wifiscope`)
  outside of shell env vars (`DITING_*`) where uppercase is
  required by the platform
- copy that uses first-person plural (`we`, `our`) where the
  brand voice is second-person (`you`)
- empty-state strings that are not parenthesised italic
  (`(scanning…)`, `(no APs from last scan — likely throttle, retrying)`)
- panel chrome that uses rounded "card" containers, gradients,
  drop shadows other than `--shadow-window` / `--shadow-modal`,
  or borders other than the heavy 1px orange box-drawing frame

The Requirement points at `design/diting-design/` rather than
embedding hex values inline so future palette adjustments don't
require a spec amendment — the canonical file is the contract.

#### Scenario: A new PR adds an off-palette hex value to the TUI theme
- **WHEN** a PR introduces `color: "#3a92e8"` in `src/diting/tui.py`
- **AND** `#3a92e8` is not present anywhere in `design/diting-design/colors_and_type.css`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL substitute a CSS custom property already declared in the design system or surface a real new-token request before merging

#### Scenario: A new PR adds an emoji to a help modal string
- **WHEN** a PR adds `t("📡 Scanning Wi-Fi…")` to `src/diting/i18n.py`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL replace the emoji with prose, a Unicode functional glyph (e.g. `σ`, `↔`), or remove the decoration entirely

#### Scenario: A new PR introduces a Lucide icon import to a Textual widget
- **WHEN** a PR adds `from textual_lucide import Icon` (or any equivalent icon library) anywhere under `src/diting/`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL either drop the icon or, if the surface genuinely needs a mark, use `design/diting-design/assets/logo-mark.svg` for brand placement only
