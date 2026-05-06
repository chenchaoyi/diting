<sub>**English** · [中文](../docs/zh/HELPER.md)</sub>

# wifiscope-helper

A minimal Cocoa `.app` that owns macOS Location Services permission so
the Python TUI can read **unredacted SSID and BSSID** for every AP in
the scan list, not just the currently associated one.

## Why

CoreWLAN's `bssid()` / `ssid()` are TCC-redacted on macOS 14.4+ unless
the calling process belongs to a `.app` bundle that has been granted
Location Services. CLI tools launched from a terminal cannot get on
that list — wifiscope's main `wifiscope` CLI works around this for the
*current connection* via an SCDynamicStore side-channel, but the
neighbour list has no equivalent. This bundle is the proper fix:
register a real `.app` with TCC, grant once, and CoreWLAN unredacts
everything for any subprocess of the bundle.

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

## Two roles in one binary

```bash
wifiscope-helper            # GUI: request Location Services, park
wifiscope-helper scan       # CLI: print one JSON document, exit
```

The first form is what runs when the user double-clicks the bundle in
Finder. The second is what `MacOSWiFiBackend` invokes from Python.
TCC bundles its policy by bundle, not by binary path, so the CLI
subprocess inherits the GUI bundle's permission grant.
