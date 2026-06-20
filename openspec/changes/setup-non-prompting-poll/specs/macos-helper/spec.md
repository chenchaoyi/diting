## ADDED Requirements

### Requirement: The helper SHALL expose read-only `location-status` and `bluetooth-authorization` probes

The helper SHALL accept `diting-tianer location-status` and `diting-tianer
bluetooth-authorization`, each an exit-code-only probe of the bundle's TCC
authorization that NEITHER prompts the user NOR powers the radio. `location-status`
SHALL read `CLLocationManager.authorizationStatus` and exit `0` when it is
`authorizedWhenInUse` / `authorizedAlways`, non-zero otherwise.
`bluetooth-authorization` SHALL read `CBManager.authorization` (the class
property, not a live central manager) and exit `0` when it is `allowedAlways`,
non-zero otherwise. Neither SHALL call `requestWhenInUseAuthorization`,
instantiate a delegate-driven `CBCentralManager`, nor otherwise surface a TCC
prompt — they are pure status reads so a verification poll can run without
stacking prompts on the helper GUI's flow.

These SHALL appear in the helper's `--help` so the Python side can detect support
and degrade gracefully on an older helper. They print no JSON and SHALL NOT
change the `wifi-scan` or `associate` schema integers. The existing `scan` and
`bluetooth-status` subcommands — the FUNCTIONAL checks (unredacted scan;
`.poweredOn`) used by the TUI and BLE readiness — are unchanged.

#### Scenario: Location authorized, read-only
- **WHEN** the bundle has Location granted and `diting-tianer location-status` runs
- **THEN** it exits 0, with no macOS prompt surfaced and no scan performed

#### Scenario: Bluetooth not yet authorized
- **WHEN** the bundle's Bluetooth grant is not determined and `diting-tianer bluetooth-authorization` runs
- **THEN** it exits non-zero, with no macOS Bluetooth prompt surfaced

#### Scenario: Older helper without the probes is detectable
- **WHEN** the Python side runs `diting-tianer --help` against a helper that predates these subcommands
- **THEN** `location-status` / `bluetooth-authorization` are absent from the help text, and the caller falls back to the functional probes
