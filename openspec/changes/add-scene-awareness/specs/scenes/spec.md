## ADDED Requirements

### Requirement: diting SHALL recognise four named scenes that describe the user's network environment
diting SHALL accept one of exactly four scene names: `home`, `office`, `public`, `audit`. Each scene describes a class of network environment and carries a set of default knobs (currently one: `ble_presence_gate_s`; more in future phases).

Scene semantics:

- `home` — apartment / own Wi-Fi, ~10-15 BLE devices, single AP. Sparse RF; anomalies dominate the signal. **Default scene** when no flag and no env var are set.
- `office` — corporate floor, enterprise Wi-Fi, 50+ BLE devices, dense BSSID surface. Continuous Continuity / Find My churn is the baseline.
- `public` — cafe / train / plane / public Wi-Fi. Highest cardinality of unique identifiers; almost everything is passers-by.
- `audit` — actively investigating: forensics / security / brief-advertiser debug / device research. All filtering disabled; record everything.

Names SHALL be lowercase ASCII. Unknown scene names SHALL exit with a clear error.

#### Scenario: home is the default scene
- **WHEN** `diting` is invoked with no `--scene` flag and no `DITING_SCENE` env var
- **THEN** `get_scene()` returns `"home"` and `scene_defaults("home")["ble_presence_gate_s"]` is 5.0 (matches the v1.5.0 default behaviour)

#### Scenario: invalid scene name exits with error
- **WHEN** `diting --scene shop` is invoked
- **THEN** the process exits non-zero with a stderr message listing the valid scene names

### Requirement: Scene resolution SHALL follow a documented precedence
diting SHALL pick the active scene at startup using this precedence (highest first):

1. CLI flag `--scene SCENE` (explicit per-session)
2. Env var `DITING_SCENE=SCENE` (shell-level persistent preference)
3. Default `home`

A blank env var (set but empty) is treated as absent so a parent shell can clear it with `DITING_SCENE= diting`. An invalid env-var value SHALL print a stderr warning and fall back to the default (not exit), so a broken shell rc doesn't break startup.

The CLI flag wins over an env var even when both are set; the env var wins over the default. The resolved scene's **source** (`cli` / `env` / `default`) SHALL be retrievable separately from the scene name — downstream consumers (the JSONL `session_meta`, the analyzer's report header) record this source so users can later distinguish "I explicitly chose this" from "the default kicked in".

#### Scenario: CLI flag wins over env var
- **WHEN** `DITING_SCENE=office diting --scene home` is invoked
- **THEN** the active scene is `home` and the source is `cli`

#### Scenario: env var fills in when no flag
- **WHEN** `DITING_SCENE=office diting` is invoked
- **THEN** the active scene is `office` and the source is `env`

#### Scenario: blank env var falls to default
- **WHEN** `DITING_SCENE= diting` is invoked (env var set to empty string)
- **THEN** the active scene is `home` and the source is `default`

#### Scenario: invalid env var warns and falls to default
- **WHEN** `DITING_SCENE=shop diting` is invoked
- **THEN** a stderr warning is printed; the active scene is `home`; source is `default`; the process continues to launch (does NOT exit)

### Requirement: `scene_defaults(scene)` SHALL return a stable mapping of knobs
The function `scene_defaults(scene: str) -> dict[str, Any]` SHALL return a dict keyed by knob name. The dict MUST include `ble_presence_gate_s` (float seconds) and `llm_prior` (string for LLM prompt injection). Other keys MAY be present in future phases without breaking callers — callers SHALL read keys defensively (use `.get(name, default)`).

Per-scene values for the keys defined in this phase:

| Scene | `ble_presence_gate_s` | `llm_prior` (abridged) |
|---|---|---|
| `home` | 5.0 | "small known network — novelty matters" |
| `office` | 15.0 | "dense enterprise env — baseline churn expected" |
| `public` | 30.0 | "hostile shared Wi-Fi — cardinality is noise" |
| `audit` | 0.0 | "raw capture — no filtering applied" |

#### Scenario: home presence gate is 5 s
- **WHEN** `scene_defaults("home")["ble_presence_gate_s"]` is read
- **THEN** the value is exactly `5.0`

#### Scenario: audit presence gate is 0 s
- **WHEN** `scene_defaults("audit")["ble_presence_gate_s"]` is read
- **THEN** the value is exactly `0.0`

#### Scenario: callers read knobs defensively
- **WHEN** code reads `scene_defaults("home").get("future_knob", "fallback")` against a build that doesn't yet implement `future_knob`
- **THEN** the call returns `"fallback"` and does NOT raise
