## MODIFIED Requirements

### Requirement: Scene resolution SHALL follow a documented precedence
diting SHALL pick the active scene at startup using this precedence (highest first):

1. CLI flag `--scene SCENE` (explicit per-session)
2. Env var `DITING_SCENE=SCENE` (shell-level persistent preference)
3. `scenes.yaml` lookup (per-network persistent assignment by SSID or gateway MAC)
4. Auto-detect heuristic (classify from active connection's security mode + visible BSSID density)
5. Default `home`

A blank env var (set but empty) is treated as absent so a parent shell can clear it with `DITING_SCENE= diting`. An invalid env-var value SHALL print a stderr warning and fall back to the next tier (yaml, then heuristic, then default), not exit; a broken shell rc should not break startup.

The CLI flag wins over an env var even when both are set; the env var wins over the yaml; the yaml wins over the heuristic. The resolved scene's **source** SHALL be retrievable separately from the scene name and SHALL be one of: `cli`, `env`, `yaml`, `auto`, `default`. Downstream consumers (JSONL `session_meta`, the analyzer's report header) record this source so users can later distinguish "I explicitly chose this" from "diting guessed".

When no Wi-Fi connection is available at startup (`get_connection()` returns None), the yaml and heuristic tiers are both skipped and the resolution falls straight to `default`.

#### Scenario: CLI flag wins over yaml + heuristic
- **WHEN** `scenes.yaml` says the current SSID maps to `home` AND the user runs `diting --scene office`
- **THEN** the active scene is `office` and the source is `cli`

#### Scenario: yaml lookup wins over heuristic
- **WHEN** no `--scene` flag, no `DITING_SCENE` env var, AND `scenes.yaml` has an entry matching the current SSID
- **THEN** the active scene is the yaml-assigned value; the source is `yaml`; the heuristic does NOT run

#### Scenario: heuristic fires when no higher tier decides
- **WHEN** no `--scene` flag, no `DITING_SCENE` env var, no `scenes.yaml` match, AND the active connection has security `"WPA2 Enterprise"`
- **THEN** the active scene is `office` and the source is `auto`

#### Scenario: heuristic falls to home for sparse RF
- **WHEN** no flag, no env, no yaml, AND security is `"WPA2 Personal"`, AND only 5 BSSIDs are visible
- **THEN** the active scene is `home` and the source is `auto`

#### Scenario: no Wi-Fi connection falls straight to default
- **WHEN** the machine has no associated Wi-Fi (`get_connection()` returns None)
- **THEN** the active scene is `home` and the source is `default`

#### Scenario: invalid env var warns and falls through (NOT to default)
- **WHEN** `DITING_SCENE=shop diting` is invoked on an enterprise network
- **THEN** a stderr warning is printed; the yaml and heuristic tiers are evaluated; the active scene reflects whichever tier resolves first (likely `office` from auto-detect)

## ADDED Requirements

### Requirement: `scenes.yaml` SHALL map networks to scenes
A user-curated `scenes.yaml` file SHALL be an optional resolution input for the active scene. The file lives at `./scenes.yaml` by default (resolved against cwd at startup, matching the `aps.yaml` pattern); the path is overridable via `DITING_SCENES_FILE`.

The file format is a top-level mapping with a single `networks` key whose value is a list of entries. Each entry SHALL carry exactly one of `ssid` or `gateway_mac` as the match key, plus a `scene` field naming one of the four canonical scenes.

```yaml
networks:
  - ssid: HomeNet
    scene: home
  - ssid: Meituan
    scene: office
  - gateway_mac: 14:51:7e:71:5a:1a
    scene: office
```

Resolution semantics:

- A missing file SHALL be treated as an empty registry (no error, no warning).
- A malformed top-level (not a mapping, or `networks` not a list) SHALL print a stderr warning and behave as an empty registry; diting SHALL continue to launch.
- An individual entry with an invalid `scene` value SHALL be skipped with a stderr warning naming the offending entry; the rest of the file SHALL still load.
- When BOTH an `ssid` entry AND a `gateway_mac` entry could match the current connection, the `gateway_mac` match wins (more specific).
- The loader is read-only — diting SHALL NOT write back to `scenes.yaml` based on auto-detect results. The file is human-curated.

#### Scenario: SSID match returns the assigned scene
- **WHEN** `scenes.yaml` contains `{ ssid: Meituan, scene: office }` AND the current connection's SSID is `Meituan`
- **THEN** the lookup returns `office`

#### Scenario: gateway_mac wins over ssid when both match
- **WHEN** `scenes.yaml` contains `{ ssid: eduroam, scene: home }` AND `{ gateway_mac: 14:51:..., scene: office }`, AND the current connection has SSID `eduroam` AND gateway MAC `14:51:...`
- **THEN** the lookup returns `office`

#### Scenario: invalid scene name in yaml is skipped
- **WHEN** `scenes.yaml` contains `{ ssid: Meituan, scene: shop }`
- **THEN** a stderr warning identifies the offending entry; the resolution proceeds to the next tier (heuristic)

#### Scenario: missing yaml is silent
- **WHEN** no `scenes.yaml` file exists
- **THEN** the yaml tier returns no match; no warning is printed

### Requirement: Auto-detect heuristic SHALL classify from observable network signals
When no higher tier (CLI / env / yaml) decides the scene AND a Wi-Fi connection is available, diting SHALL run a pure-function heuristic against the connection's security mode and visible BSSID density.

The classifier `classify_environment(security: str | None, visible_bssid_count: int, ssid: str | None) -> tuple[str, str]` returns `(scene, reason)`. Rules evaluated in priority order:

1. **Enterprise auth → `office`.** If `security` contains the substring "Enterprise" (case-insensitive — matches WPA2 Enterprise / WPA3 Enterprise / WPA-Enterprise), classify as `office`. Reason: `"{security} auth"`.
2. **High BSSID density → `office`.** If `visible_bssid_count >= 30`, classify as `office`. Reason: `"{N} BSSIDs visible"`.
3. **Otherwise → `home`.** Reason: `"no enterprise auth, sparse BSSID surface"`.

`public` is intentionally NOT auto-classified — open Wi-Fi exists in homes (neighbour's), offices (guest networks), and public spaces; without active probing diting cannot distinguish them. Public is opt-in via `--scene public` or `DITING_SCENE=public`.

The 30-BSSID threshold is a constant; tuning is a future concern.

#### Scenario: WPA2 Enterprise classifies as office regardless of BSSID count
- **WHEN** `classify_environment("WPA2 Enterprise", 5, "Meituan")` is called
- **THEN** returns `("office", "WPA2 Enterprise auth")`

#### Scenario: WPA3 Enterprise also classifies as office
- **WHEN** `classify_environment("WPA3 Enterprise", 12, "Corp")` is called
- **THEN** returns `("office", "WPA3 Enterprise auth")`

#### Scenario: dense BSSID surface without enterprise still classifies as office
- **WHEN** `classify_environment("WPA2 Personal", 47, "BigComplex")` is called
- **THEN** returns `("office", "47 BSSIDs visible")`

#### Scenario: sparse personal network classifies as home
- **WHEN** `classify_environment("WPA2 Personal", 8, "HomeNet")` is called
- **THEN** returns `("home", "no enterprise auth, sparse BSSID surface")`

#### Scenario: open network does NOT classify as public
- **WHEN** `classify_environment("None", 12, "CoffeeBar-WiFi")` is called
- **THEN** returns `("home", "no enterprise auth, sparse BSSID surface")` — public auto-detection is out of scope
