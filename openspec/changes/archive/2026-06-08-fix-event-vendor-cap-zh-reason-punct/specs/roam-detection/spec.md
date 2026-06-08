# roam-detection delta — fix-event-vendor-cap-zh-reason-punct

## ADDED Requirements

### Requirement: Roam-score reason clauses SHALL use locale-correct list punctuation
The roam-score reason clause SHALL wrap its reasons in punctuation that
matches the active UI locale — ASCII `( …, … )` in English, full-width
`（…、…）` in Chinese — for both the current link and any surfaced
candidate.
The reason words themselves are already individually translated; this
covers only the brackets and the list separator so a Chinese line reads
`（信号强、5 GHz）` rather than mixing half-width `( )` and `,` into
Chinese prose.

#### Scenario: English reasons
- **WHEN** the UI locale is English and the reasons are `strong signal`, `5 GHz`
- **THEN** the clause renders ` (strong signal, 5 GHz)`

#### Scenario: Chinese reasons
- **WHEN** the UI locale is Chinese and the reasons are `信号强`, `5 GHz`
- **THEN** the clause renders with full-width parens and a `、` separator (`（信号强、5 GHz）`), not half-width `( )` / `,`
