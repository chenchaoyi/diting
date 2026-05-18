# events Specification

## Purpose

Defines the unified event vocabulary every diagnostic surface in
diting shares — the in-memory ring buffer the TUI's events strip
and modal browser read from, the JSONL stream `diting monitor`
writes, and the analyzer consumes. One schema, five event types, one
source of truth for what "event" means across the tool.
## Requirements
### Requirement: Five event types SHALL share one schema and one ring
The system SHALL emit exactly five event types — `roam`, `rf_stir`,
`latency_spike`, `loss_burst`, `link_state` — into a single
`EventRing` keyed by emission timestamp. All five SHALL be
serialisable through the same `event_to_jsonl` writer; the analyzer
SHALL read all five through one `_extract_event` function. Adding a
sixth event type MUST file an ADDED Requirement on this capability.

#### Scenario: TUI event strip
- **WHEN** the user looks at the bottom Events strip
- **THEN** they see the most-recent N events drawn from the ring, regardless of which producer (poller, latency watcher, environment monitor) emitted them

#### Scenario: Headless `diting monitor`
- **WHEN** the user runs `diting monitor > events.jsonl`
- **THEN** every event flowing through the same ring also lands as one JSONL line on stdout, byte-identical to what the TUI's `--log` would write

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

### Requirement: The `EventRing` SHALL be size-bounded and thread-safe-by-construction
The ring SHALL retain at most 100 events by default (configurable via
constructor arg). Older events SHALL roll off the front when the
buffer is full. The ring SHALL be appendable from any coroutine in
the asyncio loop without explicit locking — Python's GIL plus the
single-thread asyncio model is the consistency guarantee.

#### Scenario: Ring overflow
- **WHEN** the 101st event is appended to a default-sized ring
- **THEN** the oldest event is dropped silently, the new event lands at the tail, and `snapshot()` returns 100 events (newest last)

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

### Requirement: Timestamps in the JSONL stream SHALL be local-TZ ISO-8601 with offset
The serialiser SHALL emit timestamps as ISO-8601 strings carrying
the local timezone offset (`_to_utc_iso` is named historically but
emits local offset, not UTC). Naïve datetimes SHALL be promoted to
local-aware via `datetime.astimezone()` before serialisation. The analyzer parses
this back transparently, and human readers see times that match
their wall clock without doing UTC math.

#### Scenario: Event in Beijing local time
- **WHEN** an event is emitted at 2026-05-09 14:23:11 +08:00
- **THEN** the JSONL line carries `"ts":"2026-05-09T14:23:11.123+08:00"`, NOT a UTC string

### Requirement: `NetworkChangeEvent` SHALL be a control-plane signal, not a user-visible event
`NetworkChangeEvent` SHALL exist alongside the five user-visible
event types but SHALL NOT be appended to the `EventRing`. It is an
internal signal consumed by the latency poller (probe reset on
network change). The TUI Events strip and modal SHALL NOT render it;
the JSONL log SHALL NOT carry it.

#### Scenario: User roams from home Wi-Fi to office Wi-Fi
- **WHEN** the connection changes
- **THEN** a `NetworkChangeEvent` reaches the latency poller (which resets gateway/WAN probes), AND a separate `RoamEvent` reaches the user-visible ring; the analyzer sees only the `RoamEvent`

