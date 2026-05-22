## MODIFIED Requirements

### Requirement: Every session JSONL SHALL open with a `session_meta` event
On `EventLogger` open (when a writable path is supplied), the writer SHALL emit exactly one `session_meta` line as the **first line** of the file, before any other event. The line carries the session-wide context that downstream tools (the analyzer, the `--for-llm` bundle, third-party `jq` consumers) need to interpret per-event data correctly.

The `session_meta` event SHALL include these fields:

| Field | Type | Source |
|---|---|---|
| `type` | string, fixed `"session_meta"` | constant |
| `ts` | ISO-8601 local TZ, same format as other events | `datetime.now(LOCAL_TZ)` at writer open |
| `scene` | string, one of `home` / `office` / `public` / `audit` | `get_scene()` |
| `scene_source` | string, one of `cli` / `env` / `yaml` / `auto` / `default` | resolution layer in `cli.py` |
| `diting_version` | string | `importlib.metadata.version("diting")` |
| `ssid` | string or null | latest connection's SSID at open time; null if not yet connected |
| `gateway_ip` | string or null | latest connection's gateway IP; null if not yet known |
| `hostname` | string | `socket.gethostname()` |

Field omission rules match the existing event schema: `None` values are written through (NOT skipped) because downstream consumers want to distinguish "not known" from "not measured". `ts` follows the existing local-TZ-offset convention.

The `scene_source` field's expanded value set lets analyzers distinguish:

- `cli` — user explicitly passed `--scene SCENE`.
- `env` — `DITING_SCENE` env var.
- `yaml` — `scenes.yaml` matched the current network.
- `auto` — heuristic classified from active connection signals.
- `default` — nothing decided; fell to `home`.

Per-event lines following the session_meta SHALL remain unchanged.

When `diting monitor` is invoked (stdout mode), the same `session_meta` line SHALL be emitted as the first stdout line, byte-identical to the file-mode case.

#### Scenario: yaml-resolved scene records source `yaml`
- **WHEN** `scenes.yaml` matches the current SSID, diting launches the TUI with `--log /tmp/x.jsonl`
- **THEN** the first line of `/tmp/x.jsonl` has `"scene_source": "yaml"`

#### Scenario: auto-detected scene records source `auto`
- **WHEN** the user has no `--scene` / no env var / no yaml match, and the active connection is WPA2 Enterprise
- **THEN** the session_meta line has `"scene": "office"` and `"scene_source": "auto"`

#### Scenario: no Wi-Fi falls to default
- **WHEN** diting launches without a Wi-Fi connection
- **THEN** the session_meta line has `"scene": "home"` and `"scene_source": "default"`
