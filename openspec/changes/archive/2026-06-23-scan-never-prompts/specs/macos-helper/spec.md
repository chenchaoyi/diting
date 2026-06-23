## ADDED Requirements

### Requirement: The `scan` subcommand SHALL NOT prompt for Location Services

The `scan` subcommand SHALL NOT trigger a Location Services TCC prompt. It SHALL
register as a CoreLocation consumer by assigning a `CLLocationManager` delegate —
which delivers the bundle's settled authorization via the authorization callback
WITHOUT prompting — and SHALL run the (unredacted) CoreWLAN scan only once the
authorization has settled to authorized. For a `notDetermined` (grant pending),
`denied`, or `restricted` status it SHALL emit a redacted scan and SHALL NOT call
`requestWhenInUseAuthorization`. Because `scan` runs on every poll tick, prompting
from it re-popped the Location dialog on every tick while the grant was
`notDetermined`; surfacing the Location prompt is the GUI helper's job (a single
dialog driven by the install / `diting setup` / auto-launch flow), never the
scan's.

#### Scenario: Repeated scans on an ungranted bundle do not prompt
- **WHEN** the bundle's Location authorization is `notDetermined` and `scan` is invoked repeatedly (e.g. once per poll tick during an audit)
- **THEN** no Location prompt appears; each invocation returns a redacted scan

#### Scenario: Authorized bundle still scans unredacted
- **WHEN** the bundle has been granted Location Services
- **THEN** `scan` registers the CoreLocation consumer and returns unredacted SSID / BSSID rows as before
