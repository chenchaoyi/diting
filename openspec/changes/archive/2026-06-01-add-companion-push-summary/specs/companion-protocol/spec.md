# companion-protocol — delta

## RENAMED Requirements
- FROM: `### Requirement: APNs trigger is a minimal doorbell, never a delivery`
- TO: `### Requirement: APNs trigger carries the channel id plus an optional cleartext event summary`

## MODIFIED Requirements

### Requirement: APNs trigger carries the channel id plus an optional cleartext event summary
The APNs payload SHALL carry the channel id and MAY carry a coarse category and
a short, single-line, human-readable event summary in cleartext (e.g. "BLE
nearby: Magic Keyboard", "Roamed to AX51-E"). The summary is a low-sensitivity
convenience composed by the producer so the notification is useful at a glance;
the relay and APNs necessarily see it, which the user accepts by pairing. The
summary SHALL NOT carry the symmetric key or anything beyond the same event
fields the paired app already displays. The full, structured event SHALL
continue to travel only inside the E2E-encrypted envelope, which the relay and
APNs never read. A producer MAY omit the summary, in which case the push falls
back to a coarse "new {category} activity" trigger.

#### Scenario: Push names the event detail
- **WHEN** a producer triggers a push for a newly-seen BLE device named "Magic Keyboard"
- **THEN** the APNs alert body reads a one-line summary such as "BLE nearby: Magic Keyboard", composed by the producer and forwarded verbatim by the relay

#### Scenario: Summary is cleartext but the full event stays sealed
- **WHEN** the relay receives a POST whose body carries the sealed envelope plus a cleartext `push` summary sibling
- **THEN** the relay uses the summary for the APNs alert, strips it, and stores and later returns only the encrypted envelope — the summary is never persisted

#### Scenario: Summary is optional and back-compatible
- **WHEN** a producer POSTs a plain envelope with no `push` sibling
- **THEN** the relay accepts it and rings a coarse "new {category} activity" doorbell, as before
