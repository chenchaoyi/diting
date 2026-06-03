# threats — delta

## ADDED Requirements

### Requirement: A threat engine SHALL detect hostile-environment patterns
The system SHALL provide a threat engine that observes the enriched event
stream and emits `critical`-severity `insight` events when the wireless
environment looks hostile. It MUST be hermetic and testable (inject
observations + clock), MUST bound its state, MUST NOT raise on a malformed
payload, MUST ignore `insight`-type payloads, and MUST debounce each
threat per (code, target) with a cooldown. Every detector SHALL key only on
authoritative, hard-to-spoof signals — BSSID, OUI/vendor, disassociation
timing, the rotation-folded device identity — and SHALL NOT treat a
user-controllable name (SSID-as-trust, Bonjour name, hostname) as a trust
anchor.

#### Scenario: Malformed observation is ignored
- **WHEN** a payload missing expected fields is observed
- **THEN** the engine does not raise and emits nothing for it

#### Scenario: A sustained threat fires once per cooldown
- **WHEN** a threat condition holds across many consecutive observations within one cooldown window
- **THEN** the engine emits at most one threat for that (code, target) in that window

### Requirement: evil_twin SHALL flag a same-SSID vendor change
The engine SHALL emit an `evil_twin` threat when the user associates with — or
roams onto — an SSID via an access point whose OUI-derived vendor differs from a
vendor already seen for that SSID in the session. The first vendor observed for
an SSID SHALL NOT fire (no prior to compare against). The detail SHALL identify
the SSID and the conflicting vendors.

#### Scenario: Same SSID, different vendor fires
- **WHEN** the session has seen SSID `cafe` on a `Cisco` AP, and the user then associates with `cafe` on a `Espressif`-vendor AP
- **THEN** an `evil_twin` threat fires naming SSID `cafe` and the new vendor

#### Scenario: First vendor for an SSID does not fire
- **WHEN** SSID `cafe` is associated for the first time this session
- **THEN** no `evil_twin` threat fires

#### Scenario: Same SSID, same vendor does not fire
- **WHEN** the user roams within SSID `cafe` between two APs of the same vendor
- **THEN** no `evil_twin` threat fires

### Requirement: deauth_storm SHALL flag a tight burst of disconnects
The engine SHALL emit a `deauth_storm` threat when disassociations exceed a
threshold within a tight window — distinct from, and tighter than, the
operational `repeated_disassociates` insight. The detection SHALL be honestly
framed as inferred from `link_state` transitions, not from observed 802.11
deauthentication frames.

#### Scenario: A tight disconnect burst fires
- **WHEN** four or more `link_state` disassociations occur within the tight window
- **THEN** a `deauth_storm` threat fires reporting the count

#### Scenario: Slow disconnects do not storm
- **WHEN** three disassociations are spread across ten minutes
- **THEN** no `deauth_storm` threat fires (the slower `repeated_disassociates` insight covers that)

### Requirement: follows_you SHALL flag an unfamiliar device across locations
The engine SHALL emit a `follows_you` threat when an *unfamiliar*
(`first_time` / `occasional`) BLE device is observed in two or more distinct
location epochs within one session, where a `network_change` advances the epoch.
A habitual device SHALL NOT fire.

#### Scenario: An unfamiliar device that persists across a network change fires
- **WHEN** an unfamiliar BLE identifier is seen, a `network_change` occurs, and the same identifier is seen again
- **THEN** a `follows_you` threat fires for that identifier reporting the location count

#### Scenario: A habitual device does not fire
- **WHEN** a `habitual` BLE device is seen across several network changes
- **THEN** no `follows_you` threat fires
