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


### Requirement: Analyze SHALL consume `session_meta` and surface scene in the report header
`diting analyze` SHALL parse the first line of each input JSONL as a potential `session_meta` event; when present, the report header SHALL include a "Scene:" line naming the scene plus its resolution source.

For multi-file glob input where input JSONLs were captured under different scenes, the report header SHALL summarise the mix (e.g., `Scenes: 3 × home, 1 × office`) rather than picking one. Per-network rankings and the top-contributors table SHALL note when their data spans multiple scenes so the user reads ranks knowing different baselines are mixed.

JSONL files written by pre-`session_meta` diting builds SHALL be tolerated — when `session_meta` is absent, the analyzer SHALL render `Scene: unknown (pre-scene-aware capture)` in the report header and proceed without scene-derived assumptions.

#### Scenario: Single-session report header surfaces scene
- **WHEN** `diting analyze diting-20260522-130000.jsonl` runs against a JSONL whose first line is `{"type":"session_meta","scene":"office","scene_source":"cli",...}`
- **THEN** the report header includes `Scene: office (cli)`

#### Scenario: Multi-session mix is reported
- **WHEN** `diting analyze logs/*.jsonl --since 30d` runs across files captured under different scenes
- **THEN** the header summarises the scene mix instead of picking one

#### Scenario: Pre-scene-aware log degrades gracefully
- **WHEN** the input JSONL has no `session_meta` line (e.g. a v1.5.0 capture)
- **THEN** the report renders `Scene: unknown (pre-scene-aware capture)` and continues normally

### Requirement: `--for-llm` SHALL inject scene context into the prompt template
The Markdown prompt written by `diting analyze --for-llm` SHALL include a `[Scene context]` paragraph immediately before the role section. The paragraph is sourced from `scene_defaults(scene)["llm_prior"]` and tells the LLM what baseline to expect for the captured environment, framed as "look for departures from this baseline, not the baseline itself".

For single-scene input the paragraph mentions the scene + observed BSSID / BLE counts from the data. For multi-scene input the paragraph names the mix and instructs the LLM to compare across scenes.

For JSONL input lacking `session_meta` the paragraph SHALL still be present but acknowledge the gap: "Scene unknown (pre-scene-aware capture). Apply general priors only."

#### Scenario: Office-mode capture gives the LLM the office prior
- **WHEN** `diting analyze diting-office.jsonl --for-llm` runs against an office-scene log
- **THEN** the generated `prompt.txt` includes a `[Scene context]` paragraph mentioning `office` mode and the "dense enterprise env" prior; the paragraph appears BEFORE the role / tasks / output-format / guardrail sections

#### Scenario: Multi-scene bundle acknowledges the mix
- **WHEN** the bundle spans both home-scene and office-scene logs
- **THEN** the paragraph names the mix and instructs the LLM to compare across scenes rather than apply one prior

#### Scenario: Pre-scene-aware log
- **WHEN** the input has no session_meta
- **THEN** the paragraph notes the gap and tells the LLM to use general priors only
