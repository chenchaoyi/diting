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

```bash
mv wifiscope-helper.app /Applications/   # or ~/Applications/
open /Applications/wifiscope-helper.app
```

The bundle window appears, requests Location Services, and tells you
when the grant has landed. Close the window; you do not need it open
during normal wifiscope use.

You can also leave the `.app` in this repo — `wifiscope` searches
common locations *and* the developer build at `helper/wifiscope-helper.app`.
Set `WIFISCOPE_HELPER=/full/path/to/wifiscope-helper.app` to override.

## How wifiscope finds it

`MacOSWiFiBackend` resolves the helper at construction time via
`src/wifiscope/_helper.py:find_helper`, in this order:

1. `WIFISCOPE_HELPER` env var (path to bundle or binary)
2. `/Applications/wifiscope-helper.app`
3. `~/Applications/wifiscope-helper.app`
4. The `helper/wifiscope-helper.app` next to this README (developer use)

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
the Python side can read line-by-line. Schema:

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "id": "550E8400-E29B-41D4-A716-446655440000",
  "name": "AirPods Pro",
  "rssi_dbm": -52,
  "is_connectable": true,
  "service_uuids": ["180D", "1812"],
  "manufacturer_id": 76,
  "manufacturer_hex": "4c001907..."
}
```

Permission denial emits a single `{"error": "..."}` line on stdout
and exits with code 3 so the Python poller can distinguish "no grant"
from "no devices yet" or "subprocess crashed".
