# tui-shell — delta

## MODIFIED Requirements

### Requirement: The footer SHALL be a single GroupedFooter with three semantic groups
`GroupedFooter` SHALL split the App's bindings into three groups
separated by `│` dividers, in this order:

1. **App** — `quit`, `pause`
2. **Scan / view** — `rescan`, `cycle sort`, `re-roam`, `toggle view`
3. **Modals** — `events`, `companion`, `help`, `basics`

This grouping is more readable than Textual's flat default Footer
on a tool with this many bindings, and gives the user a faster path to
"is this an app control or a scan action?". The `companion` binding
(`k`, the pairing screen) lives in the Modals group alongside the other
screen-pushers.

#### Scenario: User reads the footer
- **WHEN** they look at the bottom of the TUI
- **THEN** they see `quit  pause  │  rescan  sort  reroam  view  │  events  companion  help  basics` (or the ZH equivalent)

## ADDED Requirements

### Requirement: The help and basics modals SHALL document the synthesized insight/threat layer
The `?` help modal SHALL document the synthesized insight/threat layer that sits
on top of the raw event stream: an **Insights & threats** section explaining
that `[INSIGHT]` rows are operational findings (unfamiliar device cluster,
repeated disconnects, packet loss, latency-without-loss, band-steering) and
`[THREAT]` rows are defensive-security findings (evil-twin, deauth-storm,
follows-you, security-downgrade), that each device/AP carries a familiarity
class so the everyday environment is suppressed, and that identity is keyed on
authoritative signal (payload / OUI / MAC), never a spoofable name. The help
modal's Bindings list SHALL include the companion (`k`) binding, and the
`--notify` description SHALL state that note / warn / threat-level insights and
threats also notify (and forward to a paired phone), not only monitor anomalies.

The `b` basics glossary SHALL define the user-facing terms of this layer —
`Familiarity`, `INSIGHT`, `THREAT` — so the glossary's "every term diting shows"
promise holds once those rows appear.

All added / changed help + glossary strings SHALL carry a matching ZH catalog
entry (EN↔ZH parity), with no English fall-through in ZH mode.

#### Scenario: User opens help to understand an INSIGHT row
- **WHEN** the user presses `?` after seeing an `[INSIGHT]` or `[THREAT]` row in the events modal
- **THEN** the help modal's Insights & threats section explains what those rows mean, lists the companion `k` binding, and the `--notify` text covers the TUI insight/threat path

#### Scenario: User opens basics to define a glossary term
- **WHEN** the user presses `b`
- **THEN** the glossary defines `Familiarity`, `INSIGHT`, and `THREAT`

#### Scenario: Chinese reader sees translated insight/threat docs
- **WHEN** the interface language is ZH and the user opens help or basics
- **THEN** the Insights & threats content renders in Chinese with no English fall-through
