<sub>**English** · [中文](../docs/zh/HELPER.md)</sub>

# wifiscope-helper

A minimal Cocoa `.app` that owns macOS Location Services AND Bluetooth
permissions so the Python TUI can read **unredacted SSID and BSSID**
for every AP in the scan list and **stream nearby BLE advertisements**
in the BLE view.

## Why

CoreWLAN's `bssid()` / `ssid()` are TCC-redacted on macOS 14.4+ unless
the calling process belongs to a `.app` bundle that has been granted
Location Services. CoreBluetooth's `CBCentralManager` similarly refuses
to enter `.poweredOn` for processes without an `NSBluetoothAlwaysUsage
Description` entitlement. CLI tools launched from a terminal cannot
get either grant — wifiscope's main `wifiscope` CLI works around the
Wi-Fi side for the *current connection* via an SCDynamicStore
side-channel, but the neighbour list has no equivalent and BLE has no
side-channel at all. This bundle is the proper fix: register a real
`.app` with TCC, grant once for both permissions, and the bundle's
CLI subprocesses inherit the trust for both CoreWLAN and CoreBluetooth.

## Build

Requires Swift 5.9+ (Xcode command line tools or full Xcode).

```bash
cd helper
./build.sh
```

Produces `helper/wifiscope-helper.app`.

## Install

Just leave `wifiscope-helper.app` where `build.sh` produced it
(`helper/wifiscope-helper.app`) and grant once:

```bash
open helper/wifiscope-helper.app
```

The bundle window appears and requests Location Services + Bluetooth.
Click Allow on each prompt, close the window. `wifiscope` auto-detects
the in-place bundle on the next launch — no further setup.

> Earlier versions of this README suggested moving the bundle into
> `/Applications/`. **That is no longer recommended.** TCC keys
> permission grants by the bundle's cdhash, and copying / moving the
> bundle changes neither the cdhash nor the grant *if* you re-run
> `build.sh` over the same path — but a copy creates a second TCC
> subject and forces you to re-grant. Easiest path: build in place,
> grant in place, run in place.

Override the location with `WIFISCOPE_HELPER=/full/path/to/wifiscope-helper.app`
if you really do want to install it elsewhere.

## How wifiscope finds it

`MacOSWiFiBackend` resolves the helper at construction time via
`src/wifiscope/_helper.py:find_helper`, in this order:

1. `WIFISCOPE_HELPER` env var (path to bundle or binary)
2. `helper/wifiscope-helper.app` next to this README (the recommended
   location — `build.sh` produces it here, grant once with `open`)
3. `/Applications/wifiscope-helper.app` (back-compat for users who
   moved it there before this guidance changed)
4. `~/Applications/wifiscope-helper.app` (same)

If found, `scan()` shells out to `<binary> scan` and parses one JSON
document of unredacted networks. If absent or the subprocess fails,
the backend falls back to direct CoreWLAN, which still gives RSSI /
channel / band but leaves SSID / BSSID redacted on macOS 26 without
permission.

## Three roles in one binary

```bash
wifiscope-helper            # GUI: request Location Services AND Bluetooth, park
wifiscope-helper scan       # CLI: print one JSON document of CoreWLAN scan, exit
wifiscope-helper ble-scan   # CLI: stream JSONL CoreBluetooth ads until SIGTERM
```

The first form is what runs when the user double-clicks the bundle in
Finder. The second is what `MacOSWiFiBackend` invokes from Python for
the Wi-Fi scan list. The third is what `wifiscope.ble.BLEPoller`
spawns as a long-running subprocess for the BLE view — every
advertisement event becomes one JSON object on stdout, parsed line by
line on the Python side.

TCC bundles its policy by bundle, not by binary path, so all three
forms inherit the same permission grants.

## Permissions in Info.plist

The bundle declares two TCC entitlements:

- `NSLocationUsageDescription` / `NSLocationWhenInUseUsageDescription`
  — required so CoreWLAN returns unredacted SSID / BSSID for every
  network in the scan list.
- `NSBluetoothAlwaysUsageDescription` (added in 0.5.0) — required so
  `CBCentralManager` enters `.poweredOn` and starts delivering
  `centralManager(_:didDiscover:advertisementData:rssi:)` callbacks.

Both are requested by the GUI mode on launch; one Allow click per
prompt covers both CLI subcommands.

## ble-scan output schema

One JSON object per line (no enclosing array, no trailing comma) so
the Python side can read line-by-line. The stream interleaves three
kinds of rows:

**Schema-3 advertisement (the per-ad event):**

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "id": "550E8400-E29B-41D4-A716-446655440000",
  "name": "AirPods Pro",
  "rssi_dbm": -52,
  "is_connectable": true,
  "service_uuids": ["180D", "1812"],
  "manufacturer_id": 76,
  "manufacturer_hex": "4c001907...",
  "type": "AirTag",          // optional, schema-3 only
  "device_class": "iPhone"   // optional, schema-3 only
}
```

The optional `type` and `device_class` fields are populated by the
helper's `BLEAdParser` from public-format detection. `type` covers
`iBeacon`, `AirTag`, `Find My target`, `Eddystone`, `Eddystone-UID`,
`Eddystone-URL`, `Eddystone-TLM`, `Eddystone-EID`, `Tile`,
`SmartTag`, and `Swift Pair`. `device_class` covers Apple Nearby
Info: `iPhone`, `iPad`, `Mac`, `Apple TV`, `HomePod`, `Apple Watch`.
Both fields are absent when nothing is recognised — the Python side
defaults them to `None` so a schema-2 helper bundle still parses
cleanly.

**Schema-3 connected-peripheral row** (emitted every ~5 s for each
peripheral returned by `retrieveConnectedPeripherals`, deduplicated
across services):

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "connected": true,
  "id": "AA000000-1111-2222-3333-444455556666",
  "name": "Magic Keyboard",
  "service_uuids": ["1812", "180F"]
}
```

Vendor / `device_class` / `type` are intentionally omitted —
`retrieveConnectedPeripherals` returns much less metadata than a
fresh advertisement. RSSI is not reported (we deliberately do not
call `readRSSI()` against an active link).

**Schema-3 connected-snapshot sentinel** (emitted once per snapshot
cycle, after the per-peripheral rows):

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "connected_snapshot": true,
  "count": 2,
  "ids": ["AA000000-...", "BB000000-..."]
}
```

The Python side uses this to prune entries that disappeared between
snapshots — a Magic Keyboard the user just powered off shows up in
one batch's `ids` and is absent from the next, signalling it should
be removed from the Connected section.

Permission denial emits a single `{"error": "..."}` line on stdout
and exits with code 3 so the Python poller can distinguish "no grant"
from "no devices yet" or "subprocess crashed".

The Wi-Fi `scan` payload's `schema` field is bumped from `2` to `3`
in v0.6.0 so the Python side can detect a BLE-capable bundle at a
glance, even before it spawns the BLE subprocess.

## Wi-Fi scan IE fields (v0.7.0+)

The schema-3 `scan` payload's per-network rows can now include up to
five additional fields parsed out of the AP's beacon information
elements. Each is emitted only when the IE is present, so v2-shape
consumers and partial-IE rows (the AP did not advertise this
particular IE) keep parsing.

```json
{
  "ssid": "Office-WiFi",
  "bssid": "aa:bb:cc:11:22:53",
  ...
  "bss_load_pct": 78,
  "bss_station_count": 12,
  "supports_802_11r": true,
  "supports_802_11k": true,
  "supports_802_11v": true
}
```

| Field | IE | Meaning |
|---|---|---|
| `bss_load_pct` | Element ID 11 (BSS Load) | Channel utilisation as a percentage. The spec example diagnostic — "your AP is at 78% utilisation" — comes from this byte (the 0..255 value is normalised to 0..100). |
| `bss_station_count` | Element ID 11 (BSS Load) | Associated-station count (uint16, little-endian). |
| `supports_802_11r` | Element ID 54 (Mobility Domain) | Presence alone signals 802.11r (Fast BSS Transition) support. |
| `supports_802_11k` | Element ID 70 (RM Enabled Capabilities) | Presence alone signals 802.11k (Radio Measurement) support. |
| `supports_802_11v` | Element ID 127 (Extended Capabilities) bit 19 | BSS Transition Management — the 802.11v feature most commonly meant by "supports v". |

The Python side's `ScanResult` dataclass adds these as
`int | None` / `bool | None` slots. Defaults are `None`, so an
older helper that ships schema=3 *without* the IE fields remains
forward-compatible with the v0.7.0 Python TUI.
