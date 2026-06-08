# companion-bridge delta — show-paired-mobile-count

## ADDED Requirements

### Requirement: The relay SHALL expose a count-only channel presence endpoint
The relay SHALL track, per channel, the set of distinct recently-active
pullers and expose the count via `GET /v1/channel/{id}/presence`,
authenticated with the same channel bearer token as the other channel
endpoints. The authenticated phone pull (`GET /v1/channel/{id}`) — the
existing heartbeat — SHALL upsert a presence entry keyed by an opaque,
per-channel, non-reversible hash of the connection (never a stored
device identity), with a fixed TTL of at least twice the mobile pull
cadence. The presence endpoint SHALL return `{active, ttl_s, as_of}` —
the count of pullers seen within the TTL window, the window width, and
a timestamp — and nothing identifying. It SHALL be read-only (it SHALL
NOT itself register a puller, so a desktop polling it never inflates the
count), idempotent, and SHALL reject a bad/absent token exactly as the
other channel reads do.

#### Scenario: A pull registers presence
- **WHEN** a phone performs an authenticated `GET /v1/channel/{id}` and the desktop then `GET /v1/channel/{id}/presence`
- **THEN** the presence response reports `active` ≥ 1 with `ttl_s` and `as_of`, and no device identity

#### Scenario: Presence decays after the TTL
- **WHEN** no pull occurs within the TTL window
- **THEN** the presence count returns to 0

#### Scenario: Repeat pulls from one puller do not inflate the count
- **WHEN** the same puller pulls several times within the window
- **THEN** it counts once, not once per pull

#### Scenario: Polling presence does not register a puller
- **WHEN** only `GET /v1/channel/{id}/presence` is called (no `/pull`)
- **THEN** `active` stays 0 — the presence read never counts itself

#### Scenario: Presence requires the channel token
- **WHEN** `GET /v1/channel/{id}/presence` is called with a wrong or absent bearer token
- **THEN** the relay responds 403 / 401 as the other channel reads do, with no count

### Requirement: The pairing screen SHALL show a connected-count line
The desktop pairing screen SHALL poll the relay presence endpoint while
open and render one connected-count line under the QR, above the key
hints, in the mono face used for diting data. Zero SHALL be a plainly
shown state, never hidden; an error or timeout SHALL show an explicit
"can't confirm" state rather than a stale or fabricated number. The
states (connected count / zero / error) SHALL carry distinguishing
colour and SHALL be available in both English and Chinese. The relative
age of the count SHALL track the endpoint's `as_of`.

#### Scenario: Phones connected
- **WHEN** the presence endpoint reports `active` ≥ 1 while the pairing screen is open
- **THEN** the screen shows a connected-count line (e.g. `N devices connected` / `N 台设备已连接`) with its relative age

#### Scenario: No phones connected
- **WHEN** the presence endpoint reports `active` = 0
- **THEN** the screen shows an explicit zero state (`No devices connected` / `暂无设备连接`), not a hidden or blank line

#### Scenario: Presence unavailable
- **WHEN** the presence poll errors or times out
- **THEN** the screen shows a "can't confirm" state (`Can't confirm connections` / `无法确认连接数`), never a stale or guessed number
