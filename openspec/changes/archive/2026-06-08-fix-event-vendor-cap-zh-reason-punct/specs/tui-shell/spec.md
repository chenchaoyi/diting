# tui-shell delta — fix-event-vendor-cap-zh-reason-punct

## MODIFIED Requirements

### Requirement: Event rows SHALL render display-alias vendor names
BLE event rows (seen / left, strip and modal) SHALL render the resolved
vendor through the same display-alias map the BLE list and the census fold
use, so one device never shows two names across surfaces (list `Huami` vs
event `Anhui Huami Information Technology Co., Ltd.`). After alias
resolution the vendor label SHALL be capped to a fixed cell budget with a
visible trailing ellipsis when it overflows — matching the list's
vendor-cell discipline, so an unaliased long-tail IEEE registrant string
(e.g. `Qualcomm Technologies International, Ltd. (QTIL)`) does not render
at full length and dominate the event line. The cap is truncate-only (no
trailing padding, since the event line is free-flow, not a fixed column).
The `(anonymous)` / `(unknown)` fallbacks are unaffected.

#### Scenario: Aliased vendor in an event row
- **WHEN** a BLE seen event carries vendor `Anhui Huami Information Technology Co., Ltd.`
- **THEN** the rendered row reads `Huami  ·  <label>` — same vendor text as the BLE list row for that device

#### Scenario: Unaliased long vendor is capped, not passed through
- **WHEN** a BLE seen event carries a vendor with no alias entry whose length exceeds the cap (e.g. `Qualcomm Technologies International, Ltd. (QTIL)`)
- **THEN** the rendered vendor is truncated to the cap with a trailing `…`, not shown at full length

#### Scenario: Short unaliased vendor is unchanged
- **WHEN** a BLE seen event carries an unaliased vendor within the cap (e.g. `Ericsson AB`)
- **THEN** the rendered vendor is the string unchanged, with no ellipsis and no trailing padding
