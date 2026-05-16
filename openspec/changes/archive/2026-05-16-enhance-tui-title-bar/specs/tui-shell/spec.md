## MODIFIED Requirements

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
