# analyze Specification

## Purpose

Defines the `diting analyze <log.jsonl>` post-processor — what
shape the report takes, which heuristics fire on which patterns,
and how it stays a pure rule-based tool (no LLM, no network calls).
Users run it after a problematic session to get a checklist of what
went wrong; the heuristics are pinned by tests so each rule's
trigger condition is concrete.
## Requirements
### Requirement: Analyze SHALL be pure rules, no LLM, no network
The analyzer SHALL produce its report from local JSONL alone, with
no external API calls and no statistical model. Each heuristic SHALL
be an explicit predicate on the event list with an actionable hint
attached. The user SHALL be able to read the source and predict the
output for a given log.

#### Scenario: Offline analysis
- **WHEN** the user runs `diting analyze /tmp/wifi.jsonl` with airplane mode on
- **THEN** the report renders identically to an online run

### Requirement: The report SHALL open with span / counts / connection timeline
Every report SHALL begin with: log file path, total event count by
type, time span (first event → last event in human-readable
duration), and a connection timeline derived from the
`connection_update` log-only stream. The timeline SHALL show each
contiguous "associated to BSSID X for Y minutes" segment.

#### Scenario: 4-hour session on home Wi-Fi
- **WHEN** the user analyzes a log spanning 4 hours
- **THEN** the report header reads `span: 4h 02m`, the connection timeline shows one row per associated period, and the time-axis matches local-TZ wall clock

### Requirement: Insights SHALL be produced by named heuristics with explicit trigger conditions
Each heuristic SHALL be defined as a `@dataclass Insight` with
fields `name`, `summary`, `todo` (next-step hint). Heuristics SHALL
not share state; each runs independently against the full event
list. The set of bundled heuristics covers: stale-gateway probing,
sustained loss, repeated disassociations, weak roam targets, RF
stir bursts coinciding with latency spikes.

#### Scenario: Repeated AP disassociation
- **WHEN** the log carries ≥ 3 `link_state` events with `state="disassociated"` in a 10-minute window
- **THEN** the report includes an Insight with `name="Repeated disassociations"`, summary describing the count, and `todo` suggesting Wi-Fi driver / power-management investigation

### Requirement: Loss-percent rendering SHALL handle both 0..1 fractions and 0..100 percent
The analyzer SHALL detect the loss-percent encoding heuristically
(any sample ≥ 1.5 → 0..100 percent; otherwise 0..1 fraction) via
`_scaled_loss_pct` and SHALL render consistently as percent in the
report. Older logs stored loss as fractions, newer logs as percent;
heuristic thresholds SHALL apply against the post-scaled value.

#### Scenario: Old log with 0..1 fractions
- **WHEN** the log has `loss_pct` values like `0.42`
- **THEN** the report renders `42%` and the "sustained loss" heuristic compares against the post-scaled threshold

### Requirement: Duration formatting SHALL use units honestly — `1s`, never `1 min`
`_format_duration` SHALL render seconds-scale durations as `<n>s`
(e.g. `45s`), minute-scale as `<n>m <ss>s` (e.g. `4m 12s`), hour-
scale as `<n>h <mm>m`. Never round a sub-minute span up to "1 min" —
that misled users into thinking events were further apart than they
were.

#### Scenario: A 30-second span renders as 30s
- **WHEN** the report has a span of exactly 30 seconds
- **THEN** it renders `30s`, never `0 min` or `1 min`

### Requirement: The "what to do next" section SHALL exist when ANY insight fires
If at least one heuristic produced an Insight, the report SHALL end
with a "TODO" section listing each Insight's `todo` hint as a
bulleted line. If no Insight fired, the report ends with a single
"No issues detected" line. This section is the user's actionable
takeaway — the rest is context.

#### Scenario: Clean log
- **WHEN** the user analyzes a session with zero events from any heuristic-tracked type
- **THEN** the report ends with `No issues detected`, no TODO list

#### Scenario: Several issues
- **WHEN** three heuristics fire
- **THEN** the report ends with a TODO section containing three bulleted `todo` lines, one per Insight

