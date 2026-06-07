# tui-shell delta — add-panel-zoom-and-scope-reroam

## ADDED Requirements

### Requirement: The active list panel SHALL maximize in place via `z`
The App SHALL bind `z` to an in-place zoom of the active list-view
panel (Wi-Fi scan / BLE / Bonjour / LAN): the live panel widget fills
the screen while polling updates, sort cycling, row selection and
inspect continue to work on it unchanged. Pressing `z` again or `Esc`
SHALL restore the normal stacked layout. Cycling views with `n` while
zoomed SHALL keep the zoom on the newly active panel (minimize before
the visibility flip, re-maximize after). Zoom SHALL only act on the
default screen — it SHALL NOT fire while a modal screen is open, and
the `Esc` restore SHALL NOT shadow any modal's own `Esc` binding.

#### Scenario: User zooms a dense BLE list
- **WHEN** the BLE view is active and the user presses `z`
- **THEN** the BLE panel fills the screen, keeps receiving live updates, and `up`/`down`/`enter` still select and inspect rows

#### Scenario: Zoom restores
- **WHEN** a panel is maximized and the user presses `z` (or `Esc`)
- **THEN** the normal stacked layout returns

#### Scenario: Zoom follows the view cycle
- **WHEN** a panel is maximized and the user presses `n`
- **THEN** the newly active view's panel is the maximized one

#### Scenario: Zoom is inert under modals
- **WHEN** a modal screen (events, help, detail) is open
- **THEN** `z` does not maximize anything and `Esc` closes the modal as before

## MODIFIED Requirements

### Requirement: The footer SHALL be a single GroupedFooter with three semantic groups
`GroupedFooter` SHALL split the App's bindings into three groups
separated by `│` dividers, in this order:

1. **App** — `quit`, `pause`
2. **Scan / view** — `rescan`, `cycle sort`, `toggle view`, `zoom`,
   and — on the Wi-Fi view only — `re-roam`
3. **Modals** — `events`, `companion`, `help`, `basics`

This grouping is more readable than Textual's flat default Footer
on a tool with this many bindings, and gives the user a faster path to
"is this an app control or a scan action?". The `companion` binding
(`k`, the pairing screen) lives in the Modals group alongside the other
screen-pushers. The `re-roam` binding (`c`) is a Wi-Fi-link action:
it SHALL be shown and active only while the Wi-Fi view is active —
on the BLE / Bonjour / LAN views the key SHALL do nothing and the
footer SHALL omit it.

#### Scenario: User reads the footer on the Wi-Fi view
- **WHEN** they look at the bottom of the TUI while the Wi-Fi view is active
- **THEN** they see `quit  pause  │  rescan  sort  view  zoom  reroam  │  events  companion  help  basics` (or the ZH equivalent)

#### Scenario: Re-roam absent off the Wi-Fi view
- **WHEN** the BLE, Bonjour, or LAN view is active
- **THEN** the footer has no `reroam` entry and pressing `c` does not bounce the Wi-Fi link
