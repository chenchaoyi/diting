## ADDED Requirements

### Requirement: `LANActiveProbeConsentedEvent` SHALL be a defined event type that records the user's one-shot acceptance of public-scene LAN active probing
The events module SHALL define a `LANActiveProbeConsentedEvent` `@dataclass(frozen=True, slots=True)` with at minimum:

- `timestamp: datetime` — UTC moment the user confirmed the probe
- `scene: str` — at-time scene name (always `"public"` in v1 since the override is public-only)
- `ssid: str | None` — SSID of the connected Wi-Fi at confirm time, or `None` if disassociated
- `nbns_packets: int` — count of NBNS Status Queries that will be emitted on the next sweep (typically the count of silent hosts)
- `ssdp_packets: int` — fixed at `1`
- `mdns_packets: int` — fixed at `1`

The event SHALL be ingested by the existing `EventLogger.append()` path and SHALL serialise to one JSONL line with `"type": "lan_active_probe_consented"` (kebab → snake matching the existing event type conventions). It SHALL NOT appear in the in-app events modal (LAN-host-seen / left / DHCP-rotation already cover the LAN feed); it is a JSONL-only marker for post-hoc replay.

#### Scenario: Event instance is constructible with required fields
- **WHEN** `LANActiveProbeConsentedEvent(timestamp=<now>, scene="public", ssid="HotelGuest", nbns_packets=8, ssdp_packets=1, mdns_packets=1)` is invoked
- **THEN** the dataclass instance is produced without error and round-trips through JSONL serialisation

#### Scenario: Event serialises with stable type name
- **WHEN** the event is serialised by `EventLogger`
- **THEN** the JSONL line has `"type": "lan_active_probe_consented"`

#### Scenario: Event NOT emitted for scene-default probing
- **WHEN** active scene is `home`, active probing runs as scheduled
- **THEN** no `LANActiveProbeConsentedEvent` is appended (the event is uniquely the user-override marker)
