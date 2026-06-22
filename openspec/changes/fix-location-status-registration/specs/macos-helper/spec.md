## MODIFIED Requirements

### Requirement: The helper SHALL expose read-only `location-status` and `bluetooth-authorization` probes

The helper SHALL accept `diting-tianer location-status` and `diting-tianer
bluetooth-authorization`, each an exit-code-only probe of the bundle's TCC
authorization that NEITHER prompts the user NOR powers the radio.
`location-status` SHALL determine the Location authorization via the
`CLLocationManager` authorization-change CALLBACK (which fires once the manager
registers with the location daemon), NOT a synchronous read of
`CLLocationManager.authorizationStatus` immediately after construction — that
premature read returns a spurious `.notDetermined` before registration completes
and would report an authorized bundle as not-determined. It SHALL exit `0` when
the status is `authorizedWhenInUse` / `authorizedAlways`, non-zero otherwise, and
SHALL NOT call `requestWhenInUseAuthorization` (assigning a delegate triggers the
callback without prompting). A bounded settle timeout SHALL fall back to reading
the property (registered by then). `bluetooth-authorization` SHALL read
`CBManager.authorization` (the class property, not a live central manager) and
exit `0` when it is `allowedAlways`, non-zero otherwise. Neither SHALL surface a
TCC prompt — they are read-only so a verification poll can run without stacking
prompts on the helper GUI's flow.

These SHALL appear in the helper's `--help` so the Python side can detect support
and degrade gracefully on an older helper. They print no JSON and SHALL NOT
change the `wifi-scan` or `associate` schema integers. The existing `scan` and
`bluetooth-status` subcommands — the FUNCTIONAL checks (unredacted scan;
`.poweredOn`) used by the TUI and BLE readiness — are unchanged.

#### Scenario: Location authorized is reported reliably (no registration-lag false negative)
- **WHEN** the bundle has Location granted and `diting-tianer location-status` runs as a fresh process
- **THEN** it exits 0 (via the authorization callback once registration completes), with no macOS prompt surfaced and no scan performed — it does NOT return notDetermined due to reading the property before the manager registered

#### Scenario: Bluetooth not yet authorized
- **WHEN** the bundle's Bluetooth grant is not determined and `diting-tianer bluetooth-authorization` runs
- **THEN** it exits non-zero, with no macOS Bluetooth prompt surfaced

#### Scenario: Older helper without the probes is detectable
- **WHEN** the Python side runs `diting-tianer --help` against a helper that predates these subcommands
- **THEN** `location-status` / `bluetooth-authorization` are absent from the help text, and the caller falls back to the functional probes
