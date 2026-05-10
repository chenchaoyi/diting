## MODIFIED Requirements

### Requirement: Analyze SHALL be pure rules, no LLM, no network
The analyzer SHALL produce its report from local JSONL alone, with
no external API calls and no statistical model. Each heuristic SHALL
be an explicit predicate on the event list with an actionable hint
attached. The user SHALL be able to read the source and predict the
output for a given log.

#### Scenario: Offline analysis
- **WHEN** the user runs `diting analyze /tmp/wifi.jsonl` with airplane mode on
- **THEN** the report renders identically to an online run
