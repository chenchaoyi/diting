## ADDED Requirements

### Requirement: Every session JSONL SHALL open with a `session_meta` event
On `EventLogger` open (when a writable path is supplied), the writer SHALL emit exactly one `session_meta` line as the **first line** of the file, before any other event. The line carries the session-wide context that downstream tools (the analyzer, the `--for-llm` bundle, third-party `jq` consumers) need to interpret per-event data correctly.

The `session_meta` event SHALL include these fields:

| Field | Type | Source |
|---|---|---|
| `type` | string, fixed `"session_meta"` | constant |
| `ts` | ISO-8601 local TZ, same format as other events | `datetime.now(LOCAL_TZ)` at writer open |
| `scene` | string, one of `home` / `office` / `public` / `audit` | `get_scene()` |
| `scene_source` | string, one of `cli` / `env` / `default` | resolution layer in `cli.py` |
| `diting_version` | string | `importlib.metadata.version("diting")` |
| `ssid` | string or null | latest connection's SSID at open time; null if not yet connected |
| `gateway_ip` | string or null | latest connection's gateway IP; null if not yet known |
| `hostname` | string | `socket.gethostname()` |

Field omission rules match the existing event schema: `None` values are written through (NOT skipped) because downstream consumers want to distinguish "not known" from "not measured". `ts` follows the existing local-TZ-offset convention.

Per-event lines following the session_meta SHALL remain unchanged — the scene context lives ONLY in the session header, never per-event, to avoid the ~20 byte × N-events overhead at session scale.

When `diting monitor` is invoked (stdout mode), the same `session_meta` line SHALL be emitted as the first stdout line, byte-identical to the file-mode case (this preserves the existing "byte-identical streams" guarantee from the `--log` / `monitor` parity requirement).

#### Scenario: First line of a session log is session_meta
- **WHEN** `diting --log /tmp/x.jsonl --scene office` runs and exits cleanly
- **THEN** the first line of `/tmp/x.jsonl` parses as `{"type": "session_meta", "scene": "office", "scene_source": "cli", ...}`

#### Scenario: session_meta records the resolution source
- **WHEN** `DITING_SCENE=office diting --log /tmp/x.jsonl` runs (no `--scene` flag)
- **THEN** the `scene_source` field of the session_meta line is `"env"`

#### Scenario: session_meta when SSID is unknown at start
- **WHEN** diting launches without a current Wi-Fi connection
- **THEN** the session_meta line still emits with `"ssid": null` and `"gateway_ip": null`; subsequent per-event lines may carry the SSID once it's known
