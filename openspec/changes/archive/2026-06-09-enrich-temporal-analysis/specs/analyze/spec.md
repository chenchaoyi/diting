# analyze delta — enrich-temporal-analysis

## MODIFIED Requirements

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
