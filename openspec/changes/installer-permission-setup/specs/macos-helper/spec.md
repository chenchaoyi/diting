## ADDED Requirements

### Requirement: The helper SHALL expose a `notification-status` probe subcommand

The helper SHALL accept `diting-tianer notification-status`, which SHALL query
`UNUserNotificationCenter.getNotificationSettings` and exit `0` when the bundle's
Notifications authorization is granted (`.authorized` or `.provisional`) and
non-zero otherwise (`.denied` / `.notDetermined` / timeout). It SHALL print no
JSON — it is an exit-code-only probe, mirroring `bluetooth-status` — and SHALL
exit within a few seconds regardless of outcome. This lets the Python side VERIFY
the Notifications grant (not merely request it) so `diting setup` can report a
trustworthy Notifications state.

Because the probe is exit-code-only and adds no field to any JSON response, it
SHALL NOT change the `wifi-scan` or `associate` schema integers. The subcommand
SHALL appear in the helper's `--help` output so the Python side can detect
whether a given (possibly older) helper supports it and degrade gracefully when
it does not.

#### Scenario: Notifications granted
- **WHEN** the bundle has been granted Notifications and `diting-tianer notification-status` runs
- **THEN** it exits 0 with no stdout JSON

#### Scenario: Notifications not granted
- **WHEN** the bundle's Notifications grant is denied or not yet determined
- **THEN** `diting-tianer notification-status` exits non-zero

#### Scenario: Older helper without the probe is detectable
- **WHEN** the Python side runs `diting-tianer --help` against a helper that predates this subcommand
- **THEN** `notification-status` is absent from the help text, and the caller treats the Notifications grant as unverifiable rather than denied
