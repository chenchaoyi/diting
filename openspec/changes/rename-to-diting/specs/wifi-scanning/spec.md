## MODIFIED Requirements

### Requirement: When the helper is unavailable, scan results SHALL be REDACTED rather than missing
Diting SHALL surface the redacted-scan state explicitly with the
placeholder `(redacted)` and a one-liner pointing the user at
`helper/diting-tianer.app`, and SHALL NOT pretend the scan
returned nothing or fail silently. On macOS 14.4+, a Terminal-launched
Python process cannot earn Location Services TCC and CoreWLAN scans
return rows with `ssid=None` and `bssid=None`.

#### Scenario: First-run user without granted helper
- **WHEN** diting launches and the helper is uninstalled or
  ungranted
- **THEN** the scan panel renders rows with `(redacted)` SSID/BSSID and the diagnostics row points the user at the helper bundle
