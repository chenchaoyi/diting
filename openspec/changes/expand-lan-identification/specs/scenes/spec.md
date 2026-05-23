## MODIFIED Requirements

### Requirement: `scene_defaults(scene)` SHALL return a stable mapping of knobs
The function `scene_defaults(scene: str) -> dict[str, Any]` SHALL return a dict keyed by knob name. The dict MUST include `ble_presence_gate_s` (float seconds), `llm_prior` (string for LLM prompt injection), and `lan_active_probe` (bool — whether the LAN inventory poller may send NBNS / SSDP / active mDNS probes by default in this scene). Other keys MAY be present in future phases without breaking callers — callers SHALL read keys defensively (use `.get(name, default)`).

Per-scene values:

| Scene | `ble_presence_gate_s` | `lan_active_probe` | `llm_prior` (abridged) |
|---|---|---|---|
| `home` | 5.0 | `True` | "small known network — novelty matters" |
| `office` | 15.0 | `True` | "dense enterprise env — baseline churn expected" |
| `public` | 30.0 | `False` | "hostile shared Wi-Fi — cardinality is noise" |
| `audit` | 0.0 | `True` | "raw capture — no filtering applied" |

The `lan_active_probe` knob describes the **default** for the scene. The env var `DITING_LAN_PROBE=0|1` (documented in the `cli` capability) overrides it at process startup regardless of scene.

#### Scenario: home presence gate is 5 s
- **WHEN** `scene_defaults("home")["ble_presence_gate_s"]` is read
- **THEN** the value is exactly `5.0`

#### Scenario: audit presence gate is 0 s
- **WHEN** `scene_defaults("audit")["ble_presence_gate_s"]` is read
- **THEN** the value is exactly `0.0`

#### Scenario: home enables active LAN probing by default
- **WHEN** `scene_defaults("home")["lan_active_probe"]` is read
- **THEN** the value is exactly `True`

#### Scenario: office enables active LAN probing by default
- **WHEN** `scene_defaults("office")["lan_active_probe"]` is read
- **THEN** the value is exactly `True`

#### Scenario: audit enables active LAN probing by default
- **WHEN** `scene_defaults("audit")["lan_active_probe"]` is read
- **THEN** the value is exactly `True`

#### Scenario: public disables active LAN probing by default
- **WHEN** `scene_defaults("public")["lan_active_probe"]` is read
- **THEN** the value is exactly `False`

#### Scenario: callers read knobs defensively
- **WHEN** a caller reads a knob name not present in `scene_defaults(scene)` (a future-phase knob accessed by older code)
- **THEN** `.get(name, default)` returns the supplied default rather than raising KeyError
