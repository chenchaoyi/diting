## ADDED Requirements

### Requirement: The writer SHALL serialise `LANActiveProbeConsentedEvent` with a stable type name
`event_to_jsonl` SHALL emit `LANActiveProbeConsentedEvent` with the locale-stable English `type` key `"lan_active_probe_consented"`. Field naming SHALL follow the snake_case English convention used by the other LAN events.

The JSONL line SHALL carry: `ts`, `scene`, `nbns_packets`, `ssdp_packets`, `mdns_packets`. The `ssid` field SHALL be included when non-`None` and omitted otherwise, matching the existing "None fields are omitted" convention.

#### Scenario: User confirms in public scene on hotel Wi-Fi
- **WHEN** `LANActiveProbeConsentedEvent(timestamp=t, scene="public", ssid="HotelGuest", nbns_packets=8, ssdp_packets=1, mdns_packets=1)` flows through `event_to_jsonl`
- **THEN** the line is `{"type": "lan_active_probe_consented", "ts": "<iso>", "scene": "public", "ssid": "HotelGuest", "nbns_packets": 8, "ssdp_packets": 1, "mdns_packets": 1}`

#### Scenario: User confirms while disassociated
- **WHEN** `LANActiveProbeConsentedEvent(timestamp=t, scene="public", ssid=None, nbns_packets=0, ssdp_packets=1, mdns_packets=1)` flows through
- **THEN** the line omits `ssid`; the remaining fields are present

### Requirement: `EventLogger` SHALL expose `emit_lan_active_probe_consented` matching the existing emit-method conventions
The logger SHALL gain one new method `emit_lan_active_probe_consented(event: LANActiveProbeConsentedEvent) -> None`, writing one JSONL line with flush-on-write semantics. The method SHALL be a no-op when the logger was constructed with `path=None`.

#### Scenario: TUI logger with file path
- **WHEN** `diting --log /tmp/x.jsonl` is running, public scene, user confirms the probe modal
- **THEN** one `lan_active_probe_consented` line lands in `/tmp/x.jsonl` immediately (no buffering delay)

#### Scenario: TUI logger without file path
- **WHEN** `diting` (no `--log`) runs in public scene, user confirms the probe modal
- **THEN** `emit_lan_active_probe_consented` is a no-op; no file is opened

#### Scenario: Monitor stdout mode emits same shape
- **WHEN** `diting monitor` is running in public scene, user confirms via simulated key event in the monitor's TUI layer
- **THEN** the same `lan_active_probe_consented` JSONL line is written to stdout, byte-identical to the `--log` case modulo timestamp
