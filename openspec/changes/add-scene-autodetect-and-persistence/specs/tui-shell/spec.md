## ADDED Requirements

### Requirement: Scene classification SHALL print a one-line banner at startup
When the scene was resolved by `scenes.yaml` lookup or by the auto-detect heuristic (i.e. `scene_source ∈ {yaml, auto}`), diting SHALL print exactly one line to **stderr** before launching the TUI / monitor, explaining the choice. The banner format is:

EN:
- `auto-detected scene: <scene> (<reason>)` — for source `auto`
- `pinned scene: <scene> (matched "<key>" in scenes.yaml)` — for source `yaml`
- `scene: home (default — no Wi-Fi connection at startup)` — for source `default` when no connection is available

ZH equivalents in the matching catalog. The banner SHALL go to **stderr** (not stdout) so that `diting monitor > out.jsonl` streams stay clean. When `DITING_SCENE_QUIET=1` is set, the banner SHALL be suppressed (for users / scripts that want silent startup).

When the scene was resolved by `--scene` flag or `DITING_SCENE` env var (source `cli` or `env`), NO banner is printed — the user already knows what they asked for.

The banner SHALL fire exactly once per session, before the TUI's alt-screen takes over (so it stays visible in the shell's scroll-back after diting exits).

#### Scenario: auto-detect banner names the reason
- **WHEN** diting launches on a WPA2 Enterprise network without `--scene` / env / yaml
- **THEN** stderr carries one line: `auto-detected scene: office (WPA2 Enterprise auth)`

#### Scenario: scenes.yaml hit banner names the match key
- **WHEN** `scenes.yaml` contains `{ ssid: Meituan, scene: office }` and diting launches connected to `Meituan`
- **THEN** stderr carries one line: `pinned scene: office (matched "Meituan" in scenes.yaml)`

#### Scenario: explicit `--scene` is silent
- **WHEN** diting launches with `--scene office`
- **THEN** no scene banner is printed

#### Scenario: DITING_SCENE_QUIET=1 suppresses the banner
- **WHEN** `DITING_SCENE_QUIET=1 diting` is invoked on a WPA2 Enterprise network
- **THEN** the scene is still resolved to `office` (auto), the chip still shows in the TUI, but no banner is printed
