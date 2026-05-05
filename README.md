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

v0.1 — macOS 11+ only. TUI ships. Linux backend is on the long roadmap;
the abstract `WiFiBackend` exists so a future `nl80211`/`iw` impl drops
in without touching the polling, alias, or UI layers.

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
- bindings: `q` quit · `p` pause · `r` force rescan

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

**Resolving an AP from a BSSID.** A BSSID and a known mgmt MAC are
treated as the same physical AP when their first five octets match.
This works because chipsets allocate radio and VAP MACs from one NIC
by varying only the last octet — a hardware-level convention shared
across most consumer + SMB gear. The bypass for outliers is the
explicit `radio_overrides` map.

**Band labels (2.4G / 5G).** Derived from the channel number, never
the MAC: 1–14 → 2.4G, 32–177 → 5G. Vendor-independent.

**SCDynamicStore fallback for redacted SSID/BSSID.** macOS 14.4+
redacts CoreWLAN's `bssid()` / `ssid()` to `None` unless the host
process has Location Services permission. On macOS 26 terminal apps
(Warp, Terminal.app, iTerm) often do not appear in the Location
Services list at all — and there is no "+" to add them. wifiscope
works around this by reading `CachedScanRecord` from SCDynamicStore
at `State:/Network/Interface/<iface>/AirPort`; the nested
NSKeyedArchiver bplist describing the currently associated AP keeps
its real BSSID and SSID even though the dictionary's top-level
`BSSID` / `SSID_STR` are also redacted. Almost certainly an Apple
oversight that may be closed in a future release. When the fallback
is in use, the CLI prints a one-line `note:`; if both paths fail,
BSSIDs come back `n/a` and a `WARNING:` is printed with remediation
steps. A bundled `.app` distribution that owns its own TCC entry is
the intended long-term fix (v0.2 roadmap).

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

## License

MIT. See [LICENSE](LICENSE).
