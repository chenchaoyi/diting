# wifiscope

A terminal WiFi monitor for macOS, focused on **roaming visibility** —
which AP your Mac is on, when it switches, and how strong the signal
is, all in one screen.

Built for multi-AP home / SMB networks (AC + panel APs, mesh systems)
where the same SSID is broadcast by 5+ radios and you cannot tell at
a glance whether sticky roaming is causing your Zoom call to drop.

## What you see

- **Current connection**: SSID, BSSID, RSSI, noise, tx rate, channel,
  width, band, PHY mode, security
- **Roam events**: tagged `[band switch on <AP>]` for same-AP radio
  changes vs `[inter-AP roam]` for genuine moves between physical APs
- **Nearby APs**: scan list (every 5 s) sorted by signal strength
- **Friendly names** for each AP from a YAML inventory (you provide
  AP-level mgmt MACs; wifiscope figures out the per-radio attribution)

## Status

v0.1 (TUI + AP inventory + roam classification, scan list TCC-redacted)
shipped — see [the v0.1.0 release](https://github.com/chenchaoyi/wifiscope/releases/tag/v0.1.0).

v0.2 in progress: a Swift `.app` sidecar at [`helper/`](helper/) owns
Location Services and unredacts the scan list. macOS only; Linux is
still on the long roadmap.

## Install & run

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:chenchaoyi/wifiscope.git
cd wifiscope
uv sync
```

Three modes — the TUI is the default:

```bash
uv run wifiscope          # Textual TUI dashboard (default)
uv run wifiscope once     # one-shot snapshot, exit
uv run wifiscope watch    # stream events as plain text until Ctrl+C
```

In the TUI:

- top panel: current connection (AP name, SSID/BSSID, signal bar)
- middle panel: nearby APs sorted by RSSI, your current one starred
- bottom panel: roam log, tagged `[band switch on …]` or
  `[inter-AP roam]`
- bindings: `q` quit · `p` pause · `r` force rescan · `s` cycle sort
  (signal / by AP) · `c` force re-roam (disassociate so macOS picks
  the strongest BSSID for the current saved network — fastest fix
  when your Mac is sticking to a weak AP despite a stronger one
  being in range)

### One-time helper grant (automatic on first launch)

The Nearby APs panel needs Location Services permission to show each
neighbour's SSID and BSSID; without it everything in the scan list
comes back `(redacted)`. wifiscope handles this automatically on first
launch:

1. `uv run wifiscope`
2. wifiscope detects the missing permission, builds the Swift helper
   bundle (`helper/build.sh`, requires Xcode CLT) if needed, then
   `open`s it so macOS shows its Location Services prompt.
3. Click Allow. The helper window auto-closes; wifiscope's terminal
   detects the grant within ~2 seconds and launches the TUI.

The grant is persistent — subsequent runs go straight to the TUI.
Ctrl+C during the wait skips the grant and starts the TUI with
redacted scan rows. See [`helper/README.md`](helper/README.md) for
manual control (custom install path, override via `WIFISCOPE_HELPER`,
etc.).

`watch` only prints when something meaningful changes — identity
fields differ, RSSI moves ≥ 5 dBm, or a 10-second heartbeat fires —
so it stays readable over long sessions, and is handy for piping
into a logger.

## Configure: AP inventory

Most WiFi controllers (H3C, Aruba, Ubiquiti, Cisco, ASUS mesh, ...)
only expose the AP-level **management MAC**, not the per-radio BSSIDs
the AP actually broadcasts. List the mgmt MACs once; wifiscope derives
radio attribution at runtime.

Drop an `aps.yaml` at `~/.config/wifiscope/`:

```yaml
aps:
  - name: 1F-bedroom
    mgmt_mac: 40:fe:95:8a:3c:07
  - name: 2F-living
    mgmt_mac: 40:fe:95:8a:3c:54
```

Output then renders `2F-living (5G) (40:fe:95:8a:3c:58)` instead of
the raw BSSID, and roam events read `[band switch on 2F-living: 5G
-> 2.4G]` or `[inter-AP roam]`. Override the config path with
`WIFISCOPE_INVENTORY=/some/aps.yaml`.

For vendors that randomize per-radio MACs (rare; some Cisco Meraki
SKUs), add a `radio_overrides` map; see [`aps.example.yaml`](aps.example.yaml).

## How it works (design notes)

**Resolving an AP from a BSSID.** Two rules in order, both gated by a
last-byte proximity check:

1. **First five octets match + last-byte window.** Radios and VAPs
   are allocated as `mgmt + N` for small N (typically 1..6). When
   several APs share an OUI block the first five octets alone are
   not enough — e.g. an H3C controller assigning APs at
   `…3c:07`, `…3c:15`, `…3c:54` would map every BSSID with the
   common prefix to the first list entry. We require the BSSID's
   last byte to fall within 8 above the AP's mgmt MAC last byte and
   pick the closest one. Three APs in the same OUI now resolve
   independently.
2. **Octets 2..5 match + same window.** Some vendors — H3C in
   particular — assign one OUI block to a chip's "user" SSIDs
   (`40:fe:95:…`) and a sibling OUI block to the same chip's
   "vendor-internal" SSIDs (`44:fe:95:…`). Octets 2..5 carry the
   chip's serial bits and stay the same across both blocks, so this
   rule reliably groups them. False-match probability against an
   unrelated nearby AP is ~1/2³².

If neither rule fits a deployment (rare; some Cisco Meraki SKUs
randomise per-radio MACs), explicit `radio_overrides` entries win
above both rules.

**Band labels (2.4G / 5G).** Derived from the channel number, never
the MAC: 1–14 → 2.4G, 32–177 → 5G. Vendor-independent.

**SCDynamicStore fallback for the connection's SSID / BSSID.** macOS
14.4+ redacts CoreWLAN's `bssid()` / `ssid()` to `None` unless the
host process has Location Services permission. On macOS 26 terminal
apps (Warp, Terminal.app, iTerm) often do not appear in the Location
Services list at all — there is no "+" to add them. wifiscope reads
`CachedScanRecord` from SCDynamicStore at
`State:/Network/Interface/<iface>/AirPort`; the nested NSKeyedArchiver
bplist describing the currently associated AP keeps its real BSSID
and SSID even though the dictionary's top-level fields are also
redacted. Almost certainly an Apple oversight that may be closed in
a future release.

**Swift helper sidecar for the scan list.** The same TCC redaction
hits every neighbour in the scan list, and SCDynamicStore has no
neighbour-list equivalent to tunnel through. The fix is a tiny
Cocoa `.app` (`helper/`) that exists solely to own Location
Services. When installed and granted, `MacOSWiFiBackend.scan()`
shells out to it as a subprocess and gets unredacted JSON for every
visible AP. Without the helper the backend silently falls back to
direct CoreWLAN — RSSI / channel / band still work, identity comes
back redacted.

**Channel from the cache, not the radio, in fallback mode.** macOS
does periodic background scans while associated. A 1 Hz CoreWLAN
poll catches the radio mid-scan often enough that
`wlanChannel().channelNumber()` oscillates between the AP's real
channel and the scan target. `CachedScanRecord` describes the AP
itself, so its channel is stable; we use it whenever the SCDynamicStore
fallback is active.

**Pluggable backend.** `WiFiBackend` is an ABC with `get_connection`,
`scan`, and `permission_state` methods; macOS lives in
`MacOSWiFiBackend`. A future Linux backend (`nl80211` / `iw`) drops
in without touching the polling, alias, or UI layers.

**`Tx Rate` vs `Max Link Speed`.** Apple's `transmitRate` and
`maximumLinkSpeed` use different definitions and can diverge —
`transmitRate` reports the data link rate at the moment of polling
(can include frame aggregation), while `maximumLinkSpeed` is the
radio capability ceiling derived from the negotiated PHY/MCS/NSS at
the current channel width. Reading "current ≤ max" is therefore not
guaranteed; we expose both with a footnote in the Connection panel
rather than hide the discrepancy.

## License

MIT. See [LICENSE](LICENSE).
