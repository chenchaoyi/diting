# diting for agents

diting's command line is the agent-facing surface. Every read command is
JSON-first — pure JSON on stdout, human prose and errors on stderr — and
exits cleanly, so you can drive diting as a tool without scraping help
text or parsing tables.

The TUI (bare `diting`) is for a human at a terminal. Everything below is
for you.

## Discover the surface first

```bash
diting capabilities --json
```

returns a stable manifest you can pin against:

```json
{
  "schema_version": 1,
  "exit_code_convention": {"0": "success", "1": "runtime error", "2": "usage error"},
  "deprecated_aliases": {"once": "status", "watch": "stream", "monitor": "stream"},
  "commands": [
    {
      "name": "status",
      "summary": "...",
      "output": "json-object",
      "exit_codes": {"0": "associated", "1": "not associated", "2": "usage error"},
      "flags": [{"name": "--json", "type": "bool", "default": false, "repeatable": false}]
    }
  ]
}
```

`commands[].output` is one of `json-object` (one JSON document on
stdout), `json-lines` (newline-delimited JSON, one object per line), or
`text`. `schema_version` starts at `1`; if it changes, re-read the
manifest before relying on a field.

## The commands

| Command | Output | Use it to |
|---|---|---|
| `diting status [--json]` | json-object | read the current connection + permission state once |
| `diting scan [--wifi] [--ble] [--lan] [--mdns] [--duration D] [--json]` | json-object | take a one-shot sensor snapshot |
| `diting stream [--sensors …] [--duration D] [--out FILE] [--notify]` | json-lines | capture a live event stream (bounded or until killed) |
| `diting analyze [PATH ...] [--since D] [--json]` | json-object | post-process a captured JSONL log into a report |
| `diting capabilities [--json]` | json-object | discover the surface |

`status` exits `1` when the host is not associated (the snapshot is still
well-formed). `scan` runs Wi-Fi + BLE when no sensor flag is given, and keys
its JSON by sensor (`wifi`/`ble`/`lan`/`mdns` — only the requested keys); if a
sensor is unavailable its value is a `{"error": ..., "code": ...}` object and
the others still return. `stream` emits the canonical event-log JSONL — the
exact schema `analyze` consumes — so a captured stream round-trips through
`analyze`.

`stream --sensors a,b,…` selects which sensors the capture engine drives, from
`wifi`, `latency`, `rf`, `ble`, `lan`, `mdns`, plus `all`. The default is
`wifi,latency,rf` (the historical headless set), so an unflagged `stream` never
starts BLE scanning or LAN active-probing unasked. Opt into the rest with, e.g.,
`--sensors all` or `--sensors wifi,ble,lan`; when BLE/LAN/mDNS are active the
stream emits their device-discovery events (`ble_device_seen`/`_left`,
`lan_host_seen`/`_left`, `bonjour_service_seen`/`_left`) on the same JSONL
stream, and `session_meta.monitors` reports exactly what was wired.

`--duration` (on `scan` / `stream`) and `--since` (on `analyze`) share
one grammar: a bare integer (seconds) or an integer with an `s` / `m` /
`h` suffix — `30`, `45s`, `5m`, `2h`.

## Contracts you can rely on

- **stdout is pure.** Under `--json`, stdout carries only JSON. Every
  banner, hint, scene line, and deprecation notice goes to stderr. Pipe
  stdout straight into `jq` without filtering.
- **errors are structured.** A failed `--json` run prints
  `{"error": "<message>", "code": <int>}` to stderr and exits with the
  matching code. The CLI never prints a Python traceback (set
  `DITING_DEBUG=1` to restore it while debugging).
- **exit codes are stable.** `0` success · `1` runtime error (including
  `status` when not associated) · `2` usage error (unknown flag, bad
  argument, unknown subcommand).
- **keys are locale-stable English.** JSON keys and values stay English
  regardless of `--lang`; only human prose on stderr localizes.

## Patterns

Discover, then read one signal:

```bash
diting capabilities --json | jq -r '.commands[].name'
diting status --json | jq '.connection.rssi_dbm'
```

One-shot environment snapshot:

```bash
diting scan --json | jq '{aps: (.wifi | length), ble: (.ble | length)}'
```

Capture a bounded full-sensor window, then analyze it:

```bash
diting stream --sensors all --duration 5m --out /tmp/cap.jsonl
diting analyze /tmp/cap.jsonl --json | jq '.insights'
```

Tail a live stream for a specific event:

```bash
diting stream | jq -c 'select(.type == "roam")'
```

## Deprecated verbs

`once`, `watch`, and `monitor` still work — they print one deprecation
notice to stderr and forward to `status`, `stream`, and `stream`. The
manifest's `deprecated_aliases` map is the source of truth; migrate to
the canonical names.

## What's not here yet

The headless stream can now observe the full sensor set (Wi-Fi, latency,
RF, BLE, LAN, mDNS) via `--sensors`. Still tracked as follow-up work:
diting-managed background capture sessions (start / status / stop / tail).
For now, a long watch is `diting stream --sensors all --out FILE`
backgrounded by your harness, then `diting analyze FILE`.
