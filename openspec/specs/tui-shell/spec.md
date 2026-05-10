# tui-shell Specification

## Purpose

Defines the diting TUI's top-level layout — the four-panel
arrangement (Connection / Diagnostics / Scan-or-BLE / Events), the
view-toggle mechanic that swaps Wi-Fi scan vs BLE list in place, the
modal-screen lifecycle, and the GroupedFooter convention. Capability
specs for the panel CONTENTS (wifi-scanning, bluetooth-scanning,
link-health, etc.) ride on top of this layout contract.
## Requirements
### Requirement: The TUI SHALL have exactly four stacked panels in a fixed order
`DitingApp.compose()` SHALL yield, top to bottom: Header,
ConnectionPanel (`#conn`), EnvironmentPanel (`#env`), then EITHER
ScanPanel (`#scan`) OR BLEPanel (`#ble`) depending on view, then
EventsPanel (`#roam`), then GroupedFooter (`#footer`). Both Scan and
BLE panels SHALL be mounted on launch; toggling SHALL flip their
`display` attribute, never mount/unmount, so the widget tree stays
stable for tests.

#### Scenario: User toggles to BLE view
- **WHEN** the user presses `n`
- **THEN** ScanPanel.display goes False, BLEPanel.display goes True, the events strip and connection panel are unchanged

#### Scenario: User toggles back
- **WHEN** the user presses `n` again
- **THEN** ScanPanel.display goes True, BLEPanel.display goes False; no widgets are mounted or unmounted

### Requirement: Diagnostics panel content SHALL follow the active view
`_refresh_environment_panel()` SHALL render Wi-Fi-side diagnostic
content (visible BSSIDs, things-to-notice, link, environment) when
the view is `wifi`, and BLE-side content (visible BLE / vendors /
categories / closest / connected) when the view is `ble`. The panel
SHALL refresh both on view-toggle AND on each event for the active
view.

#### Scenario: BLE view, BLE event arrives
- **WHEN** the user is in BLE view and a fresh BLE snapshot lands
- **THEN** the diagnostics panel re-renders with the new BLE-side stats

#### Scenario: User in Wi-Fi view, BLE event arrives
- **WHEN** the user is in Wi-Fi view and a fresh BLE snapshot lands
- **THEN** the BLE poller silently updates `_latest_ble` and `_latest_ble_connected` but the diagnostics panel does NOT switch to BLE-side rendering — the user's chosen view is sticky

### Requirement: Modal screens SHALL push onto a stack and Esc / their own letter SHALL close
Each modal SHALL be opened via `app.push_screen(...)` and SHALL
close on Esc, `q`, or the same letter that opened it. The four
bundled modals — HelpScreen (`h`), BasicsScreen (`b`),
EventsScreen (`m`), BLEDetailScreen (`i`) — all follow this
convention. Modals
SHALL render center-middle with a heavy-bordered box and a footer
hint listing the close keys.

#### Scenario: User opens help, reads, closes
- **WHEN** the user presses `h` then `Esc`
- **THEN** HelpScreen pushes onto the stack, the underlying view stays mounted underneath, Esc pops it back to the main view

#### Scenario: User opens BLE detail, presses `i` to close
- **WHEN** the user presses `i` to open the modal then `i` again
- **THEN** the modal closes; `i`-to-toggle is documented as a convenience identical to Esc

### Requirement: The footer SHALL be a single GroupedFooter with three semantic groups
`GroupedFooter` SHALL split the App's bindings into three groups
separated by `│` dividers, in this order:

1. **App** — `quit`, `pause`
2. **Scan / view** — `rescan`, `cycle sort`, `re-roam`, `toggle view`
3. **Modals** — `events`, `help`, `basics`

This grouping is more readable than Textual's flat default Footer
on a tool with eight bindings, and gives the user a faster path to
"is this an app control or a scan action?".

#### Scenario: User reads the footer
- **WHEN** they look at the bottom of the TUI
- **THEN** they see `quit  pause  │  rescan  sort  reroam  view  │  events  help  basics` (or the ZH equivalent)

### Requirement: Hidden bindings SHALL exist for power-user navigation
The footer SHALL only show the eight primary bindings. Additional
bindings — BLE row navigation (`up`, `down`, `enter`, `i`), modal
filter-cycling (`0`/`1`/`2`/`3`/`4` in the events modal),
scroll-within-modal — SHALL exist with `show=False` and SHALL be
documented in the help modal but NOT clutter the footer.

#### Scenario: User opens help to find arrow-key behavior
- **WHEN** they press `h`
- **THEN** the help modal lists every binding including the hidden ones

### Requirement: The header SHALL show title + clock; the subtitle SHALL describe the live state
`Header(show_clock=True)` SHALL render at top. The App's
`sub_title` SHALL be a short live-updated string built by
`_build_subtitle()` covering: view (`wifi` / `ble`), scan period,
paused state. Updated whenever the view toggles, polling pauses, or
the user changes a relevant flag.

#### Scenario: User pauses polling
- **WHEN** the user presses `p`
- **THEN** the subtitle updates from `view: wifi · scan 7s` to `view: wifi · scan 7s · PAUSED` immediately

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

