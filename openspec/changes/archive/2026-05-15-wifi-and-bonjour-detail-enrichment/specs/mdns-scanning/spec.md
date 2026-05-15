## MODIFIED Requirements

### Requirement: `BonjourDevice` SHALL carry the announce-derived fields the panel renders
`BonjourDevice` SHALL be a frozen dataclass exposing these fields:

- `service_type: str` — the underscore-form type (e.g., `_airplay._tcp`).
- `name: str` — the service-instance name (e.g., `Living-Room-AppleTV`).
- `host: str | None` — the announced server (e.g., `Living-Room-AppleTV.local.`); None when the announce hasn't included one yet.
- `port: int | None` — the announced port.
- `addresses: tuple[str, ...]` — the announced IPv4 / IPv6 addresses (empty tuple if not yet resolved).
- `txt: dict[str, str]` — the parsed TXT record fields; UTF-8-decoded keys + values; binary-valued keys excluded.
- `vendor: str | None` — resolved via the chain in the next Requirement.
- `vendor_trace: str | None` — names which step of the resolution chain produced `vendor`. One of `txt-vendor`, `oui`, `hostname-pattern`, `service-type-hint`, or `None` when `vendor` is also `None`. Recorded by the resolver at the same time it produces `vendor`. Used by `bonjour-detail-modal` to annotate the Identity section so the user can see which signal won; used by maintainers to diagnose long-tail vendor-resolution gaps.
- `category: str | None` — the friendly service category from `bonjour_services.json` (e.g., `AirPlay` for `_airplay._tcp`); None for unknown types (cannot occur in v1 because unknown types are filtered out, but the field is included for forward-compatibility).
- `first_seen: datetime` — first announce observed (UTC).
- `last_seen: datetime` — most recent announce observed (UTC).

Field updates SHALL be applied per `(service_type, name)` key: a second announce for the same key updates `last_seen` and any newly-resolved field (addresses, port, TXT entries), but never replaces the device record.

#### Scenario: TXT record decoded UTF-8
- **WHEN** the announce includes a TXT entry `model=AppleTV3,2`
- **THEN** `BonjourDevice.txt["model"]` is the string `"AppleTV3,2"`

#### Scenario: Binary TXT field excluded
- **WHEN** the announce includes a TXT entry whose value bytes do not decode as UTF-8
- **THEN** that key is dropped from `BonjourDevice.txt`
- **AND** no exception propagates out of the parser

#### Scenario: vendor_trace records the winning chain step
- **WHEN** a device's vendor is resolved by the OUI step (step 2 of the chain)
- **THEN** `BonjourDevice.vendor_trace == "oui"`
- **AND** `BonjourDevice.vendor` is the non-None vendor name

#### Scenario: vendor_trace is None when the chain abstains
- **WHEN** all five steps abstain
- **THEN** both `BonjourDevice.vendor` and `BonjourDevice.vendor_trace` are `None`
