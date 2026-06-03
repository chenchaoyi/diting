# threats — delta

## ADDED Requirements

### Requirement: security_downgrade SHALL flag a weaker cipher on a known SSID
The engine SHALL emit a `security_downgrade` threat when the user associates
with an SSID at a cipher weaker than the strongest already seen for that SSID
this session, ranked open < WEP < WPA < WPA2 < WPA3. The first association to an
SSID sets the baseline and SHALL NOT fire; an unrankable / absent cipher SHALL
be skipped (never guessed). It SHALL key on the authoritative cipher, never
trusting the SSID as identity, and the detail SHALL report the SSID and the
prior + current cipher.

#### Scenario: Weaker cipher on a known SSID fires
- **WHEN** SSID `cafe` was seen this session at `WPA2 Personal`, then re-associates at `None` (open)
- **THEN** a `critical` `security_downgrade` threat fires with detail reporting `cafe`, `was` `WPA2 Personal`, `now` `None`

#### Scenario: First association sets the baseline
- **WHEN** SSID `cafe` is associated for the first time this session
- **THEN** no `security_downgrade` threat fires

#### Scenario: Same-or-stronger cipher does not fire
- **WHEN** SSID `cafe` re-associates at the same or a stronger cipher than before
- **THEN** no `security_downgrade` threat fires

#### Scenario: Unrankable cipher is skipped
- **WHEN** an association carries a cipher string the ranker does not recognise
- **THEN** the engine does not fire and does not raise
