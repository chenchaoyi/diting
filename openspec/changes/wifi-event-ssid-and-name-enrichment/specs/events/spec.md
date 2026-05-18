## MODIFIED Requirements

### Requirement: Each event SHALL be a frozen dataclass with an explicit timestamp
Every event class SHALL be defined as a `@dataclass(frozen=True, slots=True)` with at minimum a `timestamp: datetime` field (timezone-aware, local TZ at construction). Mutating an event after emission is prohibited; that is enforced by `frozen=True`. All other fields are event-type-specific.

Wi-Fi-anchored events (`RoamEvent`, `RFStirEvent`) SHALL additionally carry SSID context for the affected association:

- `RoamEvent` SHALL carry `previous_ssid: str | None = None` and `new_ssid: str | None = None`. Each is the SSID associated with the corresponding BSSID at the moment the poller observed the roam.
- `RFStirEvent` SHALL carry `ssid: str | None = None`. It is the SSID associated with the BSSID at the moment the σ threshold was crossed.

Both fields are optional with a default of `None` for backwards compatibility with code paths that construct the event without going through the poller / environment monitor; new fields land at the end of each dataclass so positional construction in legacy callers keeps working.

#### Scenario: Constructing an RFStirEvent
- **WHEN** `RFStirEvent(timestamp=..., bssid=..., location=..., magnitude_db=..., duration_s=..., confidence=..., mode=...)` is created
- **THEN** the resulting object is hashable, comparable, and immutable; `event.ssid` is `None`

#### Scenario: Constructing an RFStirEvent with SSID
- **WHEN** `RFStirEvent(..., ssid="tedo_5G")` is created
- **THEN** the resulting object exposes `event.ssid == "tedo_5G"`

#### Scenario: Constructing a RoamEvent with SSID pair
- **WHEN** `RoamEvent(..., previous_ssid="tedo_5G", new_ssid="tedo_5G")` is created
- **THEN** the resulting object exposes both fields verbatim

### Requirement: JSONL serialisation SHALL use locale-stable English keys
`event_to_jsonl` SHALL emit JSON with English keys (`type`, `bssid`, `ssid`, `state`, `magnitude_db`, etc.) regardless of the active UI language. User-supplied strings (SSID, AP location names from aps.yaml) SHALL pass through with `ensure_ascii=False` so a Chinese SSID like `咖啡馆` lands readable in the log instead of `哖...`.

When `RoamEvent.previous_ssid` / `new_ssid` are set, the JSONL line SHALL include them under the keys `previous_ssid` and `new_ssid` after the existing BSSID / channel keys. When `RFStirEvent.ssid` is set, the JSONL line SHALL include it under the key `ssid` after the existing `bssid` / `location` keys. When the SSID field is `None`, the key SHALL be omitted (the serialiser already skips `None` values for optional fields; this keeps old log entries diff-stable).

#### Scenario: ZH UI, Chinese SSID
- **WHEN** the user runs `diting --lang zh --log /tmp/wifi.jsonl`, gets a roam event from `咖啡馆 → Office`
- **THEN** the JSONL line is `{"type":"roam","previous_ssid":"咖啡馆","new_ssid":"Office", ...}` — keys English, values raw UTF-8

#### Scenario: RFStirEvent with SSID
- **WHEN** an `RFStirEvent` fires for an AP on `tedo_5G`
- **THEN** the JSONL line carries `"ssid":"tedo_5G"` after `"bssid"` and `"location"`

#### Scenario: RoamEvent with no known SSID (TCC redacted)
- **WHEN** a `RoamEvent` fires with both SSIDs `None` (Location Services denied mid-session)
- **THEN** the JSONL line omits both `previous_ssid` and `new_ssid` keys, matching the legacy pre-enrichment shape
