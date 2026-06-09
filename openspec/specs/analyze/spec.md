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
Each heuristic SHALL be defined as a self-contained block producing an
`Insight` (`severity`, `title`, `detail`, optional `todo`). Heuristics SHALL
not share state; each runs independently against the full event list and the
aggregated report. The set of bundled heuristics covers: stale-gateway
probing, sustained loss, repeated disassociations, weak roam targets, RF stir
bursts coinciding with latency spikes, and — for a long-timeline capture (a
span at or above a documented threshold, OR multi-file / `--since` input) — a
**temporal / population** family:

- **Arrival rhythm** — names a high-volume category's peak and quiet hour(s)
  and whether its activity is concentrated (a top-few-hours share above a
  documented threshold) or spread, read against the event's own timezone hour.
- **Off-hours activity** — scene-aware: activity during the scene's
  expected-quiet band (office overnight, home workday) above a floor is
  surfaced as more noteworthy than the same activity in-hours.
- **Population & dwell** — distinct *physical* devices counted via the stable
  familiarity identity ladder (manufacturer payload → service-data id →
  vendor/name → vendor-group), NEVER the rotating BLE `identifier`; a
  resident-vs-passer-by split (by hours present) and a dwell distribution
  (transient / lingering / resident, with p50 / p90) from the seen→left spans.
  Sightings with no stable identity are reported as unkeyable, not invented
  devices.
- **Cross-signal coincidence** — when two categories peak in the same hour(s)
  (e.g. loss bursts and the BLE-arrival ramp), an insight states the
  coincidence as a hypothesis (not a cause) with a concrete follow-up capture
  window.

#### Scenario: Repeated AP disassociation
- **WHEN** the log carries ≥ 3 `link_state` events with `state="disassociated"` in a 10-minute window
- **THEN** the report includes an Insight titled "Repeated disassociations", a detail describing the count, and a `todo` suggesting Wi-Fi driver / hand-off investigation

#### Scenario: BLE arrivals have a daily rhythm
- **WHEN** a long-span log's `ble_device_seen` events concentrate in a few hours (e.g. an evening peak and a near-silent overnight floor)
- **THEN** an Insight names the peak and quiet hours and reads the concentration, rather than only reporting a flat total

#### Scenario: Population counted by stable identity, not rotating id
- **WHEN** the same physical BLE devices appear under many rotated `identifier` values across a long log
- **THEN** the population insight counts distinct devices by the stable familiarity key (so a handful of physical devices is not reported as thousands), and splits residents (present across most of the span) from brief pass-bys

#### Scenario: Dwell distribution surfaces foot-traffic
- **WHEN** most `ble_device_left` spans are very short (e.g. a majority under two minutes)
- **THEN** an Insight reports the transient / lingering / resident split (with p50 / p90) and reads it as high transient foot-traffic rather than a stable device population

#### Scenario: Off-hours activity is flagged scene-aware
- **WHEN** an office-scene log shows meaningful activity during the overnight expected-quiet band
- **THEN** an Insight surfaces the off-hours activity as noteworthy, framed against the office baseline

#### Scenario: Cross-signal coincidence is a hypothesis, not a cause
- **WHEN** loss bursts and the BLE-arrival peak fall in the same hour(s)
- **THEN** an Insight states the coincidence and offers a hypothesis plus a concrete next capture window, without asserting causation

#### Scenario: Short per-session log stays lean
- **WHEN** a single log spans well under the long-timeline threshold and no `--since` / multi-file input is given
- **THEN** the temporal / population family does NOT fire and the report matches the legacy per-session shape

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
The Markdown prompt written by `diting analyze --for-llm` SHALL include a `[Scene context]` paragraph immediately before the role section. The paragraph is sourced from `scene_defaults(scene)["llm_prior"]` and tells the LLM what baseline to expect for the captured environment, framed as "look for departures from this baseline, not the baseline itself". For a long-timeline capture the paragraph SHALL also state the observed temporal rhythm (peak / quiet hours) so the LLM has the rhythm up front.

For single-scene input the paragraph mentions the scene + observed BSSID / BLE counts from the data. For multi-scene input the paragraph names the mix and instructs the LLM to compare across scenes.

For JSONL input lacking `session_meta` the paragraph SHALL still be present but acknowledge the gap: "Scene unknown (pre-scene-aware capture). Apply general priors only."

The prompt SHALL additionally include a **temporal & population lenses** section directing the LLM to reason about: activity rhythm and clustering by hour; device recurrence by STABLE identity (with an explicit caution that BLE MACs rotate, so per-sighting ids over-count); dwell (transient vs resident); cross-signal coincidence; off-hours anomalies relative to the scene; and to state what each time pattern *implies* (occupancy, congestion windows, a lingering unfamiliar device) rather than restating counts.

#### Scenario: Office-mode capture gives the LLM the office prior
- **WHEN** `diting analyze diting-office.jsonl --for-llm` runs against an office-scene log
- **THEN** the generated `prompt.txt` includes a `[Scene context]` paragraph mentioning `office` mode and the "dense enterprise env" prior; the paragraph appears BEFORE the role / tasks / output-format / guardrail sections

#### Scenario: Multi-scene bundle acknowledges the mix
- **WHEN** the bundle spans both home-scene and office-scene logs
- **THEN** the paragraph names the mix and instructs the LLM to compare across scenes rather than apply one prior

#### Scenario: Pre-scene-aware log
- **WHEN** the input has no session_meta
- **THEN** the paragraph notes the gap and tells the LLM to use general priors only

#### Scenario: Prompt carries the temporal lenses
- **WHEN** `diting analyze --for-llm` runs on a long-timeline log
- **THEN** the prompt includes a temporal & population lenses section naming rhythm, recurrence-by-stable-identity (with the rotating-MAC caution), dwell, coincidence, and off-hours reasoning, and asks the LLM to state what each pattern implies

### Requirement: `diting analyze` SHALL accept a `--for-llm` flag that writes a Markdown report + paste-ready prompt to a bundle directory
When `--for-llm [outdir]` is set on the analyze CLI, the tool SHALL write a two-file bundle to `outdir` (default `./diting-llm-<ISO-8601-timestamp>/`):

1. `report.md` — Markdown rendition of the same data the terminal report produces (Scope, per-file timelines, all A2 cross-session blocks, all per-session heuristic insights). The Markdown report SHALL:
   - Use fenced code blocks (` ```text `) for ASCII charts (hour-of-day bars, day×hour heatmap, daily-trend sparkline) so Markdown viewers don't try to interpret block characters as formatting.
   - Use Markdown tables for ranked / per-bucket data (per-network ranking, top contributors).
   - Include a `## Glossary` section defining diting-specific terms (`stir`, `co_located` vs `spatial_channel`, `roam` vs `band_switch`, the 7 new BLE / Bonjour / LAN transition event types, family names) so the LLM doesn't have to guess from context.

2. `prompt.txt` — a paste-ready analyst prompt. The template SHALL include five sections:
   - Role / data context line (string-substituted with `<span>` and `<files>` from the analyzed input).
   - Task list: identify top patterns; for each, name likely root cause + supporting evidence; suggest follow-up investigations; restate trends with explicit confidence tags; respect anonymization handles when present.
   - Output format instruction (markdown, conclusions-first, mark inferences as "hypothesis").
   - Guardrail line ("don't speculate beyond data").

#### Scenario: Multi-file `--for-llm` invocation writes the bundle
- **WHEN** the user runs `diting analyze diting-*.jsonl --since 30d --for-llm`
- **THEN** the tool writes `report.md` + `prompt.txt` to a new timestamped directory under the current working directory; both files exist and are non-empty

#### Scenario: `--for-llm` accepts an explicit outdir
- **WHEN** the user runs `diting analyze foo.jsonl --for-llm /tmp/my-analysis`
- **THEN** the bundle is written to `/tmp/my-analysis/report.md` and `/tmp/my-analysis/prompt.txt`; the timestamped default is NOT generated

#### Scenario: Report Markdown includes the glossary
- **WHEN** the bundle's `report.md` is opened
- **THEN** it contains a `## Glossary` section listing the diting-specific terms (`stir`, `roam`, `ble_device_seen`, etc.) so the consuming LLM has the vocabulary

#### Scenario: Prompt includes all five required sections
- **WHEN** `prompt.txt` is read
- **THEN** it contains: role line referencing diting + the analyzed span; numbered task list; output-format instruction; "don't speculate beyond data" guardrail; honour-anonymization clause when applicable

### Requirement: After writing the bundle the CLI SHALL print terminal-side guidance copy
After `--for-llm` succeeds, the CLI SHALL print a four-step instruction block to stdout:

```
to analyze with an LLM:
  1. open https://claude.ai or chat.openai.com
  2. drag-drop the report.md file into the chat
  3. paste the contents of prompt.txt
  4. submit
```

When `--anonymize` is NOT set, the guidance SHALL additionally include a one-line nudge mentioning the `--anonymize` flag for users pasting into a public LLM.

When `--anonymize` IS set, the guidance SHALL print the in-memory handle ↔ original mapping to stdout (and SHALL NOT write it into the bundle) so the user can decode the LLM's references later without leaking the mapping into a public chat.

#### Scenario: Default guidance includes the anonymize-hint
- **WHEN** the user runs `--for-llm` without `--anonymize`
- **THEN** the post-write stdout includes a hint like `(if you're pasting into a public LLM and want to scrub identifiers, re-run with --anonymize)`

#### Scenario: Anonymize-mode prints handle mapping to terminal only
- **WHEN** the user runs `--for-llm --anonymize`
- **THEN** the stdout prints the mapping `SSID_1 ↔ <original>` etc.; the bundle's `report.md` contains an `## Anonymization` placeholder section that points users back at their terminal output but does NOT itself contain the mapping

### Requirement: `--anonymize` SHALL replace privacy-sensitive identifiers with stable handles before writing the report
When `--anonymize` is set, the report-rendering pipeline SHALL replace the following with stable handles assigned in first-seen order:

| Kind | Handle prefix | What gets replaced |
|---|---|---|
| SSID | `SSID_1`, `SSID_2`, … | `event.ssid`, `event.previous_ssid`, `event.new_ssid` |
| BSSID | `AP_1`, `AP_2`, … | `event.bssid`, `event.new_bssid`, `event.previous_bssid` |
| LAN IP | `IP_1`, `IP_2`, … | `event.ip`, `event.new_ip`, `event.previous_ip`, `event.target_ip` — RFC1918 only |
| Hostname | `HOST_1`, `HOST_2`, … | `event.host`, `event.hostname`, `event.bonjour_name` |
| BLE identifier | `BLE_1`, `BLE_2`, … | `event.identifier` |
| LAN MAC | `MAC_1`, `MAC_2`, … | `event.mac` |

Public IPs (anything outside RFC1918) SHALL pass through unchanged — they're not identifying. Vendor names, service categories, event-type names, magnitudes (RTT, σ, loss %), timestamps, and aggregation counts SHALL pass through unchanged.

The handle assignment SHALL be deterministic given a fixed event ordering: re-running `--for-llm --anonymize` on the same input produces the same handles.

The JSONL log file SHALL NOT be modified by `--anonymize` — anonymization runs one-way at report-generation time so the source data stays available for future analysis.

#### Scenario: Same identifier maps to the same handle everywhere in the report
- **WHEN** the BSSID `aa:bb:cc:11:22:33` appears 30 times across roam / rf_stir / per-network blocks
- **THEN** every occurrence in `report.md` renders as `AP_1` (or whichever handle was assigned at first sight)

#### Scenario: Public IPs pass through unchanged
- **WHEN** a `latency_spike` event has `target_ip=1.1.1.1` (Cloudflare public DNS)
- **THEN** `report.md` renders `1.1.1.1` verbatim; the IP is not assigned a handle

#### Scenario: RFC1918 IPs get handles
- **WHEN** a `lan_host_seen` event has `ip=192.168.1.42`
- **THEN** `report.md` renders the address as `IP_1` (or the next available handle); the original mapping appears only in the terminal output

#### Scenario: Vendor and category names are not anonymized
- **WHEN** the report mentions an event with `vendor="Apple, Inc."` and `category="AirPlay"`
- **THEN** both strings appear verbatim in `report.md`; only identifying fields get handles

### Requirement: Anonymization mapping SHALL be surfaced to the terminal but NOT written into the report bundle
The `report.md`'s `## Anonymization` section SHALL be a placeholder that reads (paraphrased):

> Anonymization is active. Handle ↔ original mappings were printed to your terminal when this report was generated. Keep that mapping private — pasting it into a public LLM chat defeats the anonymization purpose.

The actual mapping table SHALL print to stdout at CLI-end. The user is responsible for storing it locally (e.g. piping CLI output to a private file) before sharing the bundle.

#### Scenario: Report doesn't leak the mapping
- **WHEN** `--for-llm --anonymize` runs on input that maps `home-5G` → `SSID_1`
- **THEN** `report.md` contains the string `SSID_1` but does NOT contain the string `home-5G`

#### Scenario: Terminal prints the mapping
- **WHEN** the same run completes
- **THEN** stdout contains a line like `SSID_1 ↔ home-5G` so the user can decode the LLM's output later

