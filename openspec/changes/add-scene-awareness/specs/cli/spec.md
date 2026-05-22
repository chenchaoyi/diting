## ADDED Requirements

### Requirement: `--scene SCENE` SHALL select one of the four named scenes for the session
The `--scene` flag SHALL accept exactly one of `home`, `office`, `public`, `audit`. The flag is global — valid on the default TUI subcommand, `monitor`, `calibrate`, and any future subcommand that runs pollers.

Resolution precedence is documented in the `scenes` capability and SHALL be honoured here: `--scene` (highest) > `DITING_SCENE` env var > default `home`.

Invalid values SHALL exit non-zero with a clear error listing the four accepted names. Missing value (`--scene` with no argument) SHALL exit non-zero.

The resolved scene SHALL be threaded through every subcommand that constructs a `BLEPoller`, so the poller's `presence_gate_s` default matches `scene_defaults(scene)["ble_presence_gate_s"]` unless `--ble-presence-gate D` explicitly overrides it. Override precedence: explicit `--ble-presence-gate` > scene-derived default.

#### Scenario: User in an office picks the office scene
- **WHEN** they run `diting --scene office`
- **THEN** the BLE presence gate defaults to 15 s (not the home / default 5 s)

#### Scenario: Explicit `--ble-presence-gate` overrides scene
- **WHEN** they run `diting --scene office --ble-presence-gate 5s`
- **THEN** the BLE presence gate is 5 s; the scene name is still `office` (used by session_meta and LLM context)

#### Scenario: Invalid scene name
- **WHEN** they run `diting --scene shop`
- **THEN** stderr prints "unsupported scene: 'shop'" and lists the four valid names; the process exits non-zero

#### Scenario: Missing value
- **WHEN** they run `diting --scene` (no argument)
- **THEN** stderr prints a clear error; the process exits non-zero
