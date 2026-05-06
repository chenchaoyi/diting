<p align="center">
  <img src="docs/logo.svg" alt="wifiscope" width="320">
</p>

<p align="center">
  <strong>See which Wi-Fi AP your Mac is on, when it switches, and how strong the signal really is — all in your terminal.</strong>
</p>

<p align="center">
  <a href="https://github.com/chenchaoyi/wifiscope/actions/workflows/test.yml"><img src="https://github.com/chenchaoyi/wifiscope/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/chenchaoyi/wifiscope/releases"><img src="https://img.shields.io/github/v/release/chenchaoyi/wifiscope?display_name=tag" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/chenchaoyi/wifiscope" alt="license"></a>
</p>

---

<p align="center">
  <img src="docs/preview.svg" alt="wifiscope TUI" width="100%">
</p>

## Why

You set up multiple APs at home or at the office, you walk between
rooms, and your Mac stays glued to the AP it associated with five
hours ago at -75 dBm — even though there's a new AP within reach
broadcasting the same SSID at -45 dBm. Zoom stutters; you grumble;
you blame the WiFi.

Apple's WiFi panel will tell you the *current* signal but nothing
about *which AP* you're on, *whether you should be on a different
one*, or *when* the OS roamed (or didn't). `wifiscope` turns that
black box into a TUI:

- a top panel with everything Apple's "Option-click WiFi" panel
  shows, plus IP / Router / interface MAC / MCS / NSS / max link
  speed
- a middle panel listing every BSSID in range, **grouped by
  physical AP** so a single AP that broadcasts five SSIDs collapses
  into one labelled cluster
- a bottom panel that **logs roam events as they happen**, tagged
  `[band switch on <AP>]` for same-AP radio changes vs
  `[inter-AP roam]` for genuine moves between physical APs

Stuck on a weak AP? Hit `c` and `wifiscope` cycles the WiFi radio so
macOS re-runs auto-join and reassociates with the strongest BSSID.
That's the same path as click-menu-off-then-on, but in one keystroke.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/), plus the
Xcode Command Line Tools (the helper bundle is built from a small
Swift source on first launch).

```bash
git clone git@github.com:chenchaoyi/wifiscope.git
cd wifiscope
uv sync
uv run wifiscope
```

On first run, `wifiscope` builds and opens a tiny **helper bundle**
that asks for Location Services permission. Click Allow once; the
window auto-closes; the TUI launches with full SSID and BSSID for
every visible AP. Subsequent runs go straight to the TUI — the grant
is persistent.

> **Why the helper?** macOS 14.4+ redacts SSID and BSSID to None
> unless the calling process has Location Services. A Python CLI
> launched from Terminal cannot get on that list, but a tiny `.app`
> bundle can. `wifiscope` shells out to it for scan data and gets
> the real values back. Press `h` inside the TUI for the full
> story.

## Bindings

| Key | Action |
|-----|--------|
| `q` | quit |
| `p` | pause / resume polling |
| `r` | force a rescan now (CoreWLAN ~5 s throttle still applies) |
| `s` | cycle scan sort: by AP ↔ by signal |
| `c` | force re-roam — cycle Wi-Fi off/on so macOS re-picks the strongest BSSID |
| `h` | open / close the in-app help screen |

`watch` and `once` subcommands run wifiscope in plain-text modes —
useful for piping into a logger or for a one-shot diagnostic:

```bash
uv run wifiscope once     # snapshot of current connection, exit
uv run wifiscope watch    # streaming events until Ctrl+C
```

## Configuration

### AP inventory

Most controllers (H3C, Aruba, Ubiquiti, Cisco, ASUS mesh, …) only
expose AP-level **management MACs**, not the per-radio BSSIDs the
APs actually broadcast. List the mgmt MACs once at
`~/.config/wifiscope/aps.yaml`:

```yaml
aps:
  - name: 1F-bedroom
    mgmt_mac: 40:fe:95:8a:3c:07
  - name: 2F-living
    mgmt_mac: 40:fe:95:8a:3c:54
  - name: 3F-attic
    mgmt_mac: bc:22:47:ca:79:46
```

`wifiscope` then renders **`2F-living (5G)` (40:fe:95:8a:3c:58)** in
place of the raw BSSID, and roam events read `[band switch on
2F-living: 5G → 2.4G]` or `[inter-AP roam]`.

If your AP vendor randomises per-radio MACs (rare; some Cisco
Meraki SKUs), add a `radio_overrides` map mapping specific BSSIDs
to AP names. See [`aps.example.yaml`](aps.example.yaml).

Without any inventory file `wifiscope` still works — every BSSID
gets an auto-clustered label like `?AB:CD:EF` so radios of the same
chip group together visually.

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `WIFISCOPE_INVENTORY` | `~/.config/wifiscope/aps.yaml` | Path to the AP inventory YAML. |
| `WIFISCOPE_HELPER` | searched in `/Applications`, `~/Applications`, repo `helper/` | Path to the `wifiscope-helper.app` bundle or its binary. |
| `WIFISCOPE_SCAN_INTERVAL` | `7` | Seconds between scans. CoreWLAN throttles around 5 s, so values below ~6 yield empty scans every other call. Floor 3. |

## macOS caveats

**Some neighbours' SSIDs come back `(hidden)`.** That's the 802.11
hidden-SSID bit — the AP is broadcasting normally, just with the
SSID information element blanked. BSSID, channel, signal, and
capabilities are all still visible. Hidden ≠ undetectable.

**`Tx Rate` and `Max Link Speed` may diverge.** Apple's
`transmitRate` (current data rate, can include frame aggregation)
and `maximumLinkSpeed` (radio capability ceiling at the negotiated
PHY/MCS/NSS) come from different CoreWLAN APIs; "current ≤ max" is
not guaranteed. The Connection panel shows both with a footnote.

**Without the helper, the Nearby APs scan list is fully redacted.**
RSSI, channel, band, and width still come through, but every SSID
shows `(redacted)` and every BSSID `(redacted)`. The Connection
panel itself is unaffected — `wifiscope` reads SSID and BSSID for
the *current* AP through a separate SCDynamicStore tunnel that
macOS forgot to redact.

**`disassociate()` is unreliable for forcing a roam.** Earlier
versions of `wifiscope` used `iface.disassociate()` for the `c`
binding; on 802.1X enterprise networks it would tear down the link
and macOS would not auto-rejoin. Cycling power via
`setPower(false)` then `setPower(true)` mirrors the WiFi-menu
off/on path and reliably triggers full auto-join with Keychain
credentials.

## How it works

This section is for the curious; everyday use does not require
reading it.

**Resolving an AP from a BSSID.** Two rules, both gated by a
last-byte proximity check:

1. *First five octets match + last-byte window.* Radios and VAPs
   are allocated as `mgmt + N` for small N (typically 1..6). When
   several APs share an OUI block (e.g. an H3C controller handing
   out APs at `…3c:07`, `…3c:15`, `…3c:54`), the prefix alone is
   ambiguous; we require the BSSID's last byte to fall within 8
   above the AP's mgmt MAC last byte and pick the closest match.
2. *Octets 2..5 match + same window.* Some vendors split a chip's
   "user" SSIDs and "vendor-internal" SSIDs across sibling OUI
   blocks (H3C uses `40:fe:95:…` and `44:fe:95:…`). Octets 2..5
   carry the chip's serial bits and stay the same across both
   blocks; this rule groups them under one AP. False-match
   probability is ~1 / 2³².

`radio_overrides` always wins above both rules.

**Channel comes from `SCDynamicStore`'s top-level `CHANNEL` field**,
not from `CWInterface.wlanChannel().channelNumber()`. macOS does
periodic background scans while associated, and a 1 Hz CoreWLAN
poll catches the radio mid-scan often enough that the channel
appears to oscillate. The `SCDynamicStore` field reflects the OS's
notion of the radio's current associated channel and is stable.

**Pluggable backend.** `WiFiBackend` is an ABC with
`get_connection`, `scan`, and `permission_state` methods; macOS
lives in `MacOSWiFiBackend`. A future Linux backend (`nl80211` /
`iw`) drops in without touching the polling, alias, or UI layers.

## Development

```bash
uv sync --all-groups          # installs runtime + dev deps (pytest)
uv run pytest                 # runs the full test suite
```

[`tests/TESTING.md`](tests/TESTING.md) is the canonical test plan —
every automated test corresponds to a row in that document, and
changes to test scenarios start there before touching the test
files. **Read it first** when reviewing a PR or extending coverage.

GitHub Actions runs the suite on every push and pull request to
`main`, against Python 3.11 / 3.12 / 3.13 on macOS. CoreWLAN and
SCDynamicStore are not exercised live in CI — those surfaces are
mocked at the subprocess and dynamic-store boundaries.

See [`CHANGELOG.md`](CHANGELOG.md) for the version-by-version log.

## Roadmap

- **CSV / JSONL session logging** — a `wifiscope log` mode that
  appends every connection / scan / roam event to a file for later
  analysis.
- **Trend graphs in the TUI** — RSSI over time, time-on-AP per BSSID.
- **Linux backend** — `nl80211` via `pyroute2` or shelling out to
  `iw scan`.
- **Optional menu-bar app** for ambient awareness without keeping a
  terminal open.

## License

MIT. See [`LICENSE`](LICENSE).
