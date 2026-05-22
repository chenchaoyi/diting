## ADDED Requirements

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
