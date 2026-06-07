# tui-shell delta — add-listening-mark-empty-state

## ADDED Requirements

### Requirement: List-panel waiting states SHALL render the animated listening mark
Each list-view panel SHALL render, in its waiting state (no rows yet
— Wi-Fi scan / BLE / Bonjour / LAN), the pixel-art diting mark
(the brand header's half-block rendering, geometry unchanged) above
the existing localized dim-italic waiting caption, with a single radar
pulse dot travelling away from the antenna. The animation SHALL tick
at most 2 Hz and ONLY while the panel is visible AND in its waiting
state AND polling is not paused: data arriving replaces the mark with
rows immediately, hiding the panel or pausing polling freezes/stops
the animation, and frame 0 (no dot) SHALL be the deterministic first
paint so snapshot captures are stable. Populated panels SHALL carry
zero animation-timer cost (timer paused, not merely no-opped).

#### Scenario: LAN sweep shows the listening mark
- **WHEN** the LAN view is active and the first sweep has not returned
- **THEN** the panel shows the beast mark with the travelling pulse above `(sweeping subnet…)`

#### Scenario: Rows clear the mark
- **WHEN** the first inventory update with hosts lands
- **THEN** the mark and pulse disappear and the host rows render as before

#### Scenario: Pause freezes the pulse
- **WHEN** the user presses `p` while a waiting panel is visible
- **THEN** the pulse stops advancing (the sweep is not running, so the listening picture must not pretend it is)

#### Scenario: Hidden panels do not animate
- **WHEN** the user cycles to another view while a panel is still waiting
- **THEN** the hidden panel's animation timer is paused and costs nothing
