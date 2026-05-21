# event-log Specification

## Purpose

Defines the JSONL event log writer shared by the TUI's `--log <path>`
mode and the headless `diting monitor` subcommand. Both modes
produce byte-identical streams; the analyzer assumes this. Crash
safety, locale stability, and append-mode semantics are load-bearing
— a session log that loses its last 30 seconds to a crash is worse
than no log.
## Requirements
### Requirement: The writer SHALL flush after every event for crash safety
EventLogger SHALL open the output file with line-buffering AND
explicitly flush after every event write, so each event hits the
kernel page cache before the producer side moves on. A SIGKILL
between events SHALL lose at most one in-flight event, never the
preceding history.

#### Scenario: Hard crash mid-session
- **WHEN** the user's Mac panics 30 minutes into a logged session
- **THEN** the JSONL file on disk after reboot contains every event up to (and possibly including) the very last one before the crash

#### Scenario: Process killed by SIGKILL
- **WHEN** the user runs `kill -9 $(pgrep diting)` after 5 minutes of logging
- **THEN** the JSONL file is complete up to the last `flush()` call (i.e. up to the last event)

### Requirement: An atexit hook SHALL close the writer cleanly on graceful exit
EventLogger SHALL register an `atexit` hook (via `weakref` so the
hook does not hold the writer alive) that closes the underlying
file. On SIGTERM / Ctrl+C / `quit` action, the file SHALL be flushed
and closed before the process exits.

#### Scenario: User presses `q`
- **WHEN** the user quits the TUI gracefully
- **THEN** the log file's last byte is `\n` (no torn final line) and `lsof` shows no leaked file descriptor

### Requirement: JSONL keys SHALL be locale-stable English regardless of UI language
The writer SHALL use English JSON keys (`type`, `bssid`, `ssid`,
`state`, `magnitude_db`, etc.) even when `DITING_LANG=zh` is set.
User-supplied strings (SSID, AP location names from aps.yaml) SHALL
flow through with `ensure_ascii=False` so a Chinese SSID like
`咖啡馆` survives readable in the log.

#### Scenario: ZH user, Chinese SSID
- **WHEN** the user runs `DITING_LANG=zh diting --log /tmp/wifi.jsonl`
- **THEN** roam events lay down as `{"type":"roam","previous_ssid":"咖啡馆", ...}`, NOT escaped to `\\uXXXX` sequences

### Requirement: Timestamps SHALL be local-TZ ISO-8601 with offset
Every event written SHALL carry a `ts` field as ISO-8601 with the
local timezone offset (e.g. `2026-05-09T14:23:11.123+08:00`). Naïve
datetimes SHALL be promoted to local-aware via `astimezone()` before
serialisation. UTC strings ending in `Z` SHALL NOT appear in the log.

#### Scenario: Event in Beijing local time
- **WHEN** an event fires at 14:23 +08:00
- **THEN** the JSONL `ts` is `2026-05-09T14:23:11.123+08:00`, the analyzer renders it back as `14:23:11`, the user sees their wall-clock time without doing UTC math

### Requirement: The writer SHALL accept `None` as a no-op
EventLogger constructed with `path=None` SHALL silently no-op every
`emit_*` call. Code that conditionally enables logging — both the TUI
(when `--log` was not passed) and the monitor (when stdout is `/dev/null`)
— SHALL be able to call the same emit methods unconditionally.

#### Scenario: TUI without --log
- **WHEN** the user runs `diting` (no log path)
- **THEN** `app._event_logger.emit_roam(...)` calls are no-ops; no file is opened, no IO happens

### Requirement: Connection-update events SHALL ride alongside the five event types
`emit_connection_update` SHALL produce a sixth log-only event type
(`{"type":"connection_update", ...}`) that carries the live
`Connection` snapshot fields (BSSID, SSID, channel, signal, etc.).
This is a log-stream-only construct — it does NOT enter the
in-memory `EventRing` and does NOT show up in the TUI's events
strip. The analyzer uses it to reconstruct a connection timeline.

#### Scenario: Long session with stable connection
- **WHEN** the user runs `diting --log` and stays on one BSSID for an hour
- **THEN** the log carries one `connection_update` per scan tick (~ every 7 s) plus zero `roam` events; the analyzer can render an "associated for 1 h" timeline from this

### Requirement: Both `--log` and `diting monitor` SHALL produce byte-identical streams
The `EventLogger` class SHALL be the single point of truth for the
wire format. The TUI's `--log <path>` and the headless `diting
monitor` subcommand SHALL both route every event through the same
class with the same writer. The analyzer SHALL be unable to tell
which mode produced a given log.

#### Scenario: Side-by-side capture
- **WHEN** the user runs `diting --log a.jsonl` and `diting monitor > b.jsonl` in the same Wi-Fi environment for the same duration
- **THEN** `diff <(jq -c . a.jsonl) <(jq -c . b.jsonl)` shows differences only in timestamps, never in field shape

### Requirement: The writer SHALL serialize the seven new transition event types
`event_to_jsonl` SHALL emit each new event type with a locale-stable English `type` key:

| Event class | JSONL `type` value |
|---|---|
| `BLEDeviceSeenEvent` | `"ble_device_seen"` |
| `BLEDeviceLeftEvent` | `"ble_device_left"` |
| `BonjourServiceSeenEvent` | `"bonjour_service_seen"` |
| `BonjourServiceLeftEvent` | `"bonjour_service_left"` |
| `LANHostSeenEvent` | `"lan_host_seen"` |
| `LANHostLeftEvent` | `"lan_host_left"` |
| `LANHostDHCPRotationEvent` | `"lan_host_dhcp_rotation"` |

Field naming SHALL follow the snake_case English convention used by the existing five event types. Fields whose value is `None` SHALL be omitted from the line; tuple fields whose value is `()` SHALL emit as `[]` (informative — "empty list" is distinct from "field missing").

#### Scenario: BLE device-seen serialises with all populated fields
- **WHEN** `BLEDeviceSeenEvent(timestamp=t, identifier="abc", name="Magic Keyboard", vendor="Apple, Inc.", rssi_dbm=-55, service_categories=("HID",))` flows through `event_to_jsonl`
- **THEN** the JSONL line is `{"type": "ble_device_seen", "ts": "<iso>", "identifier": "abc", "name": "Magic Keyboard", "vendor": "Apple, Inc.", "rssi_dbm": -55, "service_categories": ["HID"]}`

#### Scenario: Bonjour-service-left preserves empty addresses tuple
- **WHEN** `BonjourServiceLeftEvent(timestamp=t, service_type="_airplay._tcp.local.", name="Blue Pod._airplay._tcp.local.", host=None, category="AirPlay", seen_for_seconds=3600.0)` flows through `event_to_jsonl`
- **THEN** the JSONL line carries `category` and `seen_for_seconds` but NOT `host`; `service_type` and `name` are present

### Requirement: `EventLogger` SHALL expose one emit method per new event type
The logger SHALL gain seven new methods, each accepting the corresponding event dataclass and writing one JSONL line with flush-on-write semantics (matching the existing five emit methods):

- `emit_ble_device_seen(event: BLEDeviceSeenEvent) -> None`
- `emit_ble_device_left(event: BLEDeviceLeftEvent) -> None`
- `emit_bonjour_service_seen(event: BonjourServiceSeenEvent) -> None`
- `emit_bonjour_service_left(event: BonjourServiceLeftEvent) -> None`
- `emit_lan_host_seen(event: LANHostSeenEvent) -> None`
- `emit_lan_host_left(event: LANHostLeftEvent) -> None`
- `emit_lan_host_dhcp_rotation(event: LANHostDHCPRotationEvent) -> None`

The no-op logger contract (writer accepts `None` for `enable_logging=False` runs) SHALL extend to all seven new methods.

#### Scenario: No-op logger swallows new event types
- **WHEN** `EventLogger(None)` has any of the seven new methods called on it
- **THEN** the call returns silently; no file is opened, no exception is raised

