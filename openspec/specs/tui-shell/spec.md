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
ConnectionPanel (`#conn`), EnvironmentPanel (`#env`), then ONE OF
ScanPanel (`#scan`), BLEPanel (`#ble`), or BonjourPanel (`#mdns`)
depending on view, then EventsPanel (`#roam`), then GroupedFooter
(`#footer`). All three view-toggle panels SHALL be mounted on launch
when their respective subsystems are available; toggling SHALL flip
their `display` attribute, never mount/unmount, so the widget tree
stays stable for tests.

The `n` key binding cycles the view across `wifi` → `ble` → `mdns`
→ `wifi`, in that order.

The active third-slot panel's `border_title` SHALL render an
always-visible three-segment tab indicator listing every view name
in cycle order: `Wi-Fi · BLE · Bonjour`. The active view's label
SHALL be styled bold-cyan and the two inactive labels SHALL be
dimmed, so the user can see from any single screen that three
views exist and which one is active. The panel-specific status
detail (count, sort hint, last-scan timestamp) SHALL move to the
panel's `border_subtitle` (bottom of frame) so no information is
lost.

The footer label for `n` SHALL continue to read the literal name of
the NEXT view in the cycle (e.g., `→ BLE` while in Wi-Fi, `→ Bonjour`
while in BLE, `→ Wi-Fi` while in mDNS) so the user knows where the
next press lands.

#### Scenario: User toggles from Wi-Fi to BLE
- **WHEN** the user is in `wifi` view and presses `n`
- **THEN** ScanPanel.display goes False, BLEPanel.display goes True, BonjourPanel.display stays False; the events strip and connection panel are unchanged

#### Scenario: User toggles from BLE to mDNS
- **WHEN** the user is in `ble` view and presses `n`
- **THEN** BLEPanel.display goes False, BonjourPanel.display goes True, ScanPanel.display stays False

#### Scenario: User toggles from mDNS back to Wi-Fi (cycle wraps)
- **WHEN** the user is in `mdns` view and presses `n`
- **THEN** BonjourPanel.display goes False, ScanPanel.display goes True, BLEPanel.display stays False

#### Scenario: All three panels mounted at launch
- **WHEN** the App composes its widget tree
- **THEN** ScanPanel, BLEPanel, and BonjourPanel are all present in the tree (no widgets are mounted or unmounted during view toggles)

#### Scenario: Tab indicator visible in every view
- **WHEN** the user is in any of `wifi` / `ble` / `mdns` view
- **THEN** the active third-slot panel's `border_title` contains all three view labels (`Wi-Fi`, `BLE`, `Bonjour`) separated by `·`
- **AND** the label matching the active mode is styled distinctly (bold-cyan) while the other two are dimmed

#### Scenario: Panel detail moves to the border subtitle
- **WHEN** the user is in `wifi` view
- **THEN** the panel's `border_subtitle` carries the Wi-Fi-specific detail (`Nearby BSSIDs (N) · sort: AP` or equivalent) and the `border_title` carries the tab indicator
- **AND** the equivalent split applies in BLE view (`border_subtitle` shows `Nearby BLE devices (N)`) and mDNS view (`Nearby Bonjour (N)`)

### Requirement: Diagnostics panel content SHALL follow the active view
`_refresh_environment_panel()` SHALL render Wi-Fi-side diagnostic
content (visible BSSIDs, things-to-notice, link, environment) when
the view is `wifi`, BLE-side content (visible BLE / vendors /
categories / closest / connected) when the view is `ble`, and
mDNS-side content (visible Bonjour / top services / top vendors)
when the view is `mdns`. The panel SHALL refresh both on view-toggle
AND on each event for the active view.

#### Scenario: BLE view, BLE event arrives
- **WHEN** the user is in BLE view and a fresh BLE snapshot lands
- **THEN** the diagnostics panel re-renders with the new BLE-side stats

#### Scenario: mDNS view, Bonjour snapshot lands
- **WHEN** the user is in mDNS view and a fresh `BonjourScanUpdate` snapshot lands
- **THEN** the diagnostics panel re-renders with the new mDNS-side stats (visible Bonjour count, top services, top vendors)

#### Scenario: Wi-Fi view ignores mDNS updates
- **WHEN** the user is in Wi-Fi view and a fresh `BonjourScanUpdate` snapshot lands
- **THEN** the diagnostics panel does NOT re-render (the snapshot is held for when the user toggles back)

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
The TUI SHALL render a custom `BrandHeader` widget at the top of
the screen — a four-row Horizontal container with the diting radar
mark on the left and a three-line title / subtitle / clock stack on
the right, separated from the panels below by a one-cell-tall
`tall` border in brand orange (`#fea62b`).

The radar mark SHALL be rendered with Unicode half-block characters
(`▀` / `█` / `▄`) in foreground `#fea62b`, matching the pixel grid
of `docs/design/diting-design/assets/logo-mark.svg`. The mark MUST
NOT be replaced by an icon font or PNG.

The right-hand stack SHALL render exactly three lines, top to
bottom:

1. The current local time as `HH:MM:SS`, right-aligned, dim-styled.
2. The App's `title` attribute (already pinned to `diting v<version>`
   by the version Requirement), bold-styled.
3. The App's `sub_title` attribute (the short live-updated string
   built by `_build_subtitle()` — `view: ... · scan Ns · PAUSED`
   when paused), dim-styled.

The header SHALL react to changes in `App.title` and `App.sub_title`
without explicit notification from the call site (i.e. the widget
watches those reactives and re-renders), so existing `self.sub_title
= ...` assignments continue to drive the live state.

#### Scenario: Title bar shows the brand mark + version + subtitle
- **WHEN** the user launches the TUI
- **THEN** the rendered top of the screen contains at least one Unicode half-block glyph (`▀`, `█`, or `▄`) on the left in brand orange
- **AND** the App's `title` text (`diting v<X.Y.Z>`) is visible to its right
- **AND** the App's `sub_title` text (`view: wifi · scan 7s` by default) is visible below the title
- **AND** a clock reading `HH:MM:SS` is right-aligned on the top row of the header

#### Scenario: User pauses polling
- **WHEN** the user presses `p`
- **THEN** the subtitle line of the header updates from `view: wifi · scan 7s` to `view: wifi · scan 7s · PAUSED` immediately, without the user pressing any other key
- **AND** the brand mark and title remain unchanged

#### Scenario: User toggles to BLE view
- **WHEN** the user presses `n` from the Wi-Fi view
- **THEN** the subtitle line updates from `view: wifi · ...` to `view: ble · ...`
- **AND** the brand mark and title remain unchanged

### Requirement: TUI visual language SHALL conform to the design system
The diting TUI and any UI-adjacent surface (README, marketing snapshots, modals, slide decks, docs site) SHALL conform to the design system at `docs/design/diting-design/`. That directory (`README.md`, `colors_and_type.css`, `SKILL.md`, `assets/`) is the single source of truth for visual language and copy voice. Reviewers MAY block any PR that introduces:

- a hex value not declared as a CSS custom property in
  `docs/design/diting-design/colors_and_type.css`
- a font face other than Fira Code or JetBrains Mono on a mono
  surface (TUI, snapshot title bars, code blocks)
- emoji in user-visible strings (Unicode glyphs like `σ`, `↔`,
  `⚠`, `▁▂▃▄▅▆▇█`, `→` ARE NOT emoji and ARE allowed)
- imports of icon libraries (Lucide, Heroicons, Material
  Symbols, etc.); the only mark is `docs/design/diting-design/assets/logo-mark.svg`
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

The Requirement points at `docs/design/diting-design/` rather than
embedding hex values inline so future palette adjustments don't
require a spec amendment — the canonical file is the contract.

#### Scenario: A new PR adds an off-palette hex value to the TUI theme
- **WHEN** a PR introduces `color: "#3a92e8"` in `src/diting/tui.py`
- **AND** `#3a92e8` is not present anywhere in `docs/design/diting-design/colors_and_type.css`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL substitute a CSS custom property already declared in the design system or surface a real new-token request before merging

#### Scenario: A new PR adds an emoji to a help modal string
- **WHEN** a PR adds `t("📡 Scanning Wi-Fi…")` to `src/diting/i18n.py`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL replace the emoji with prose, a Unicode functional glyph (e.g. `σ`, `↔`), or remove the decoration entirely

#### Scenario: A new PR introduces a Lucide icon import to a Textual widget
- **WHEN** a PR adds `from textual_lucide import Icon` (or any equivalent icon library) anywhere under `src/diting/`
- **THEN** the reviewer SHALL block the PR with a citation to this Requirement
- **AND** the contributor SHALL either drop the icon or, if the surface genuinely needs a mark, use `docs/design/diting-design/assets/logo-mark.svg` for brand placement only

### Requirement: Each list-style view panel SHALL share the same row-select + inspect gesture contract
The TUI SHALL guarantee that every list-style panel in the third panel slot (Wi-Fi scan list, BLE devices, Bonjour services, and any future analogue) exposes the same input contract to the user. The following bindings MUST behave identically across every such view:

- `up` / `down` move selection within the active view, registered
  priority=True so they fire before `VerticalScroll`'s scroll
  handler.
- `i` and `enter` open a panel-specific detail modal for the
  current selection.
- Mouse click on a data row sets selection to that row AND opens
  the detail modal in the same gesture; clicks on header /
  placeholder / spacer rows are no-ops.
- Modal close binds `escape`, `i`, and `q`; closing does NOT
  mutate the panel's selection state.
- The action methods backing `up` / `down` / `i` / `enter` SHALL
  no-op when the active view does not match the action's panel.
  This keeps the same physical key safe across views (e.g. ↓ in
  Wi-Fi view does not also act on BLE selection state).
- Selection state SHALL be keyed by a stable identifier (BSSID,
  BLE peripheral identifier, Bonjour service-instance FQDN), NOT
  by row index. Selected targets that drop out of the next snapshot
  SHALL clear the selection.

The specific section layout, field set, and behavioural edge cases
for each modal are defined in that panel's capability spec
(`wifi-detail-modal`, `ble-detail-modal`, `bonjour-detail-modal`).
This requirement only pins the cross-cutting input contract.

#### Scenario: User switches views, gesture works identically in each
- **WHEN** the user presses `n` to cycle Wi-Fi → BLE → Bonjour and presses `↓` `↓` `i` in each
- **THEN** in each view the cursor moves down twice and the same row's detail modal opens

#### Scenario: Mouse click in any list view
- **WHEN** the user clicks a data row in any of the three list views
- **THEN** that row gets selected AND its detail modal opens, with no separate keypress needed

#### Scenario: Adding a fourth list panel
- **WHEN** a future change introduces another selectable list panel
- **THEN** that panel inherits the same contract; deviating from the contract requires explicitly modifying this Requirement

