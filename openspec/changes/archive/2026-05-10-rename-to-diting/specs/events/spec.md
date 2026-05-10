## MODIFIED Requirements

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

### Requirement: JSONL serialisation SHALL use locale-stable English keys
`event_to_jsonl` SHALL emit JSON with English keys (`type`, `bssid`,
`ssid`, `state`, `magnitude_db`, etc.) regardless of the active UI
language. User-supplied strings (SSID, AP location names from
aps.yaml) SHALL pass through with `ensure_ascii=False` so a Chinese
SSID like `咖啡馆` lands readable in the log instead of `哖...`.

#### Scenario: ZH UI, Chinese SSID
- **WHEN** the user runs `diting --lang zh --log /tmp/wifi.jsonl`, gets a roam event from `咖啡馆 → Office`
- **THEN** the JSONL line is `{"type":"roam","previous_ssid":"咖啡馆", ...}` — keys English, values raw UTF-8
