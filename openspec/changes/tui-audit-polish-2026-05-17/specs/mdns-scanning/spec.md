## ADDED Requirements

### Requirement: The `BonjourPanel` SHALL support a `by-host` sort mode in addition to the default service-row mode
The Bonjour panel SHALL accept two sort modes:

- `service` (default) — one row per `(host, service_type)` pair. Each row's services column carries a single service-type name. This is the historical behaviour.
- `by-host` — one row per `host`. The vendor / name / age / host columns reflect the host's most-recent service announce. The services column folds the host's services into a comma-joined string of the short service-type names (e.g. `AirPlay, AirPlay audio, Apple Companion, HomeKit`), in alphabetical order of the short name. Long folded lists SHALL be truncated to the column width with an ellipsis via `fit_cells` (no raw slicing — keep CJK-safe).

The user SHALL cycle between modes via the existing `s` keystroke. The cycle order is `service` → `by-host` → `service`. The border subtitle's `sort: <mode>` SHALL reflect the current mode.

The `service` mode is the default on TUI start. Switching modes does not refetch — both modes operate on the same `BonjourDevice` snapshot.

#### Scenario: User on Bonjour view presses `s`
- **WHEN** the view is `bonjour`, current sort is `service`, and the user presses `s`
- **THEN** the panel re-renders in `by-host` mode and the border subtitle reads `sort: by-host`

#### Scenario: User presses `s` again
- **WHEN** the view is `bonjour` and current sort is `by-host`
- **THEN** the panel re-renders in `service` mode and the border subtitle reads `sort: service`

#### Scenario: HomePod with four services
- **WHEN** in `by-host` mode and a host `Blue-Pod` has services `_airplay._tcp`, `_raop._tcp`, `_companion-link._tcp`, `_homekit._tcp`
- **THEN** the row's services column reads `AirPlay, AirPlay audio, Apple Companion, HomeKit` (alphabetically sorted short names, comma-joined)

#### Scenario: by-host mode collapses count
- **WHEN** in `service` mode the panel reports `21 services` from `8` hosts, then the user presses `s`
- **THEN** `by-host` mode shows `8` rows; the border subtitle's `Nearby Bonjour devices` count reflects the row count in the active mode

#### Scenario: Long services list truncates with ellipsis
- **WHEN** a host has 7 services and the joined string would overflow the column
- **THEN** the rendered string is truncated to the column width with a trailing `…` via `fit_cells`, never via raw `str` slicing

## MODIFIED Requirements

### Requirement: The diagnostics panel SHALL surface an mDNS-side summary when the active view is `mdns`
When the user has the Bonjour view active, the Diagnostics panel SHALL replace its Wi-Fi-side lines with an mDNS summary:

1. **Visible Bonjour** — total service count + distinct service-type count.
2. **Top services** — three most-common service types with counts (e.g. `5 Apple Companion · 4 AirPlay · 4 AirPlay audio`).
3. **Top vendors** — three most-common vendor names with counts. The unknown-vendor bucket SHALL be rendered as `(unknown) N`, never as `? N`, to match the column placeholder used in the table and the same bucket's label in the BLE panel.
4. **Closest** — RSSI is not available on mDNS, so this line is omitted (BLE-only).

#### Scenario: User in mDNS view sees Bonjour diagnostics
- **WHEN** the user toggles to the `bonjour` view with 21 announces across 8 hosts
- **THEN** the diagnostics panel shows `Visible Bonjour 21 total · 7 service types`, `Top services …`, and `Top vendors …` rows

#### Scenario: Empty snapshot placeholder
- **WHEN** the user toggles to the `bonjour` view before any announce has arrived
- **THEN** the diagnostics panel shows a single dim-italic line `(listening for announces …)`

#### Scenario: Unknown-vendor bucket rendered with explicit label
- **WHEN** the snapshot has 16 announces from `Apple, Inc.` and 5 from devices whose vendor could not be resolved
- **THEN** the `Top vendors` line reads `Top vendors  16 Apple, Inc.  ·  (unknown) 5` — the literal `?` glyph SHALL NOT appear for this bucket
