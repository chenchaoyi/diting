<p align="right">
  <strong>English</strong> · <a href="docs/zh/README.md">中文</a>
</p>

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
  <img src="docs/preview.svg" alt="wifiscope TUI – Wi-Fi view" width="100%">
  <br>
  <sub><i>Wi-Fi view (default)</i></sub>
</p>

<p align="center">
  <img src="docs/preview-ble.svg" alt="wifiscope TUI – BLE view" width="100%">
  <br>
  <sub><i>BLE view (press <code>n</code> to toggle) — Connected peripherals on top, Advertising devices below, each labelled with its public-format identification.</i></sub>
</p>

<p align="center">
  <img src="docs/preview-events.svg" alt="wifiscope TUI – Events modal" width="100%">
  <br>
  <sub><i>Events modal (press <code>m</code> to open) — last 100 roam / RF-stir / latency / loss / link events, per-AP σ baseline, last-hour σ sparkline.</i></sub>
</p>

## Why

You set up multiple APs at home or at the office, you walk between
rooms, and your Mac stays glued to the AP it associated with five
hours ago at -75 dBm — even though there's a new AP within reach
broadcasting the same SSID at -45 dBm. Zoom stutters; you grumble;
you blame the Wi-Fi.

Apple's Wi-Fi panel will tell you the *current* signal but nothing
about *which AP* you're on, *whether you should be on a different
one*, or *when* the OS roamed (or didn't). `wifiscope` turns that
black box into a TUI:

- a top panel with everything Apple's "Option-click Wi-Fi" panel
  shows, plus IP / Router / interface MAC / MCS / NSS / max link
  speed
- a Diagnostics panel that translates a dense scan into plain
  findings: visible BSSID counts, open/no-password BSSIDs,
  channel crowding, least-crowded channel hints, current-link
  health, and a simple roam score
- a scrollable Nearby BSSIDs panel listing every BSSID in range,
  **grouped by physical AP** so a single AP that broadcasts five
  SSIDs collapses into one labelled cluster
- a bottom panel that **logs roam events as they happen**, tagged
  `[band switch on <AP>]` for same-AP radio changes vs
  `[inter-AP roam]` for genuine moves between physical APs
- a **Nearby BLE devices** view (press `n` to toggle in place of the
  scan list) split into two sections: **Connected** lists the
  peripherals you're using *right now* (AirPods, Magic Keyboard,
  Apple Watch — devices that are not advertising and so otherwise
  invisible to a BLE scanner), and **Advertising** lists every BLE
  device broadcasting nearby with **what kind of device it actually
  is** — `AirTag`, `iBeacon`, `Eddystone-URL`, `Tile`, `SmartTag`,
  `iPhone`, `Mac`, `Apple Watch`, `HomePod` — instead of the
  "Apple, Inc. (anonymous) Find My" wall
- two new **link-health** rows: a `Link` line that pings the gateway
  and your auto-detected DNS server every second so a -55 dBm AP
  reads as bad when the upstream is broken, and an `Environment`
  line that surfaces rolling RSSI variance with a `stable` /
  `active` qualifier (calibrate with `wifiscope calibrate` for a
  `quiet` baseline). Press `m` to open a full-screen Events
  browser of the last 100 roam / RF-stir / latency / loss / link
  events. **NOT** Wi-Fi sensing — see
  [`docs/explainers/wifi-sensing.md`](docs/explainers/wifi-sensing.md)
  for what we deliberately do not claim

Stuck on a weak AP? Hit `c` and `wifiscope` cycles the Wi-Fi radio so
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

## Switching language

```bash
uv run wifiscope --lang zh           # force Chinese
WIFISCOPE_LANG=zh uv run wifiscope   # via env var
```

With no override, `wifiscope` autodetects the system locale —
`LANG=zh_CN.UTF-8` defaults to Chinese; everything else stays English.

## Bindings

| Key | Action |
|-----|--------|
| `q` | quit |
| `p` | pause / resume polling |
| `r` | force a rescan now (CoreWLAN ~5 s throttle still applies) |
| `s` | cycle scan sort: by AP ↔ by signal |
| `n` | toggle Nearby view: Wi-Fi BSSIDs ↔ BLE devices |
| `c` | force re-roam — cycle Wi-Fi off/on so macOS re-picks the strongest BSSID |
| `m` | open / close the Events modal — last 100 roam / stir / latency / loss / link events |
| `h` | open / close the in-app help screen |
| `b` | open / close Wi-Fi Basics: SSID, BSSID, channel, band, security, roam score |

`watch`, `once`, `monitor`, and `calibrate` subcommands run
wifiscope without the TUI:

```bash
uv run wifiscope once                       # snapshot of current connection, exit
uv run wifiscope watch                      # streaming text events until Ctrl+C
uv run wifiscope monitor                    # headless JSONL events to stdout
uv run wifiscope monitor --out events.jsonl # append JSONL to a file
uv run wifiscope monitor --notify           # macOS Notification Centre alerts on high-confidence events
uv run wifiscope calibrate                  # 5 min "empty room" RSSI baseline → ./wifiscope-baseline.json
```

The `monitor` subcommand is the long-run / Home Assistant
integration target — every roam, RF stir, latency spike, loss
burst, and link-state change emits one well-formed JSON line. The
schema lives in
[`docs/specs/v0.7.0-network-ground-truth-and-environment-monitor.md`](docs/specs/v0.7.0-network-ground-truth-and-environment-monitor.md#single-eventsjsonl-schema-for-all-three-layers).

## Configuration

### AP aliases (optional)

`wifiscope` works fine without any AP-name configuration — every
BSSID gets an auto-clustered label like `?AB:CD:EF` so radios of the
same physical AP group together visually, and roam classification
between APs still works.

If you want **human-readable AP names** (`2F-living` instead of
`?40:fe:95`) in the scan list and roam log, drop a file at
`./aps.yaml` (next to the executable / the cloned repo's
`aps.example.yaml`):

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

**Where the mgmt MACs come from.** Most controllers (H3C, Aruba,
Ubiquiti, Cisco, ASUS mesh, …) expose only an AP-level **management
MAC** per access point, not the per-radio BSSIDs each AP actually
broadcasts. Read those off the controller's **AP list page** —
typically at the controller's web UI under "Access Points" / "AP
列表" / "Devices" — then paste them into `aps.yaml` with whatever
spatial labels make sense to you.

**When to skip this entirely.** On enterprise / shared / unfamiliar
networks where you can't access the controller, just don't create
`aps.yaml`. The auto-cluster labels (`?AB:CD:EF`) already correctly
group every radio of one physical AP under a single label — you
lose the friendly name, but every other feature works.

If your AP vendor randomises per-radio MACs (rare; some Cisco
Meraki SKUs), add a `radio_overrides` map mapping specific BSSIDs
to AP names. See [`aps.example.yaml`](aps.example.yaml).

Set `WIFISCOPE_INVENTORY=/some/path/aps.yaml` to load the file from
somewhere other than the current working directory.

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `WIFISCOPE_LANG` | autodetected | UI language: `en` or `zh`. Equivalent to `--lang`. |
| `WIFISCOPE_INVENTORY` | `./aps.yaml` (CWD-relative) | Path to the AP-aliases YAML. The file is optional; if absent, wifiscope uses auto-cluster labels. |
| `WIFISCOPE_HELPER` | searched in `/Applications`, `~/Applications`, repo `helper/` | Path to the `wifiscope-helper.app` bundle or its binary. |
| `WIFISCOPE_SCAN_INTERVAL` | `7` | Seconds between scans. CoreWLAN throttles around 5 s, so values below ~6 yield empty scans every other call. Floor 3. |
| `WIFISCOPE_LATENCY_WAN_TARGET` | autodetected from `scutil --dns` | IP for the WAN latency anchor. Default picks the first non-gateway nameserver from `SCDynamicStoreCopyValue("State:/Network/Global/DNS")`; if the only configured DNS *is* the gateway, the WAN probe is skipped and the diagnostic line reads `WAN n/a (DNS == gateway)`. Override to pin an explicit IP (e.g. `1.1.1.1` for networks that allow it). |

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

**The Diagnostics panel is a guide, not an RF survey tool.** Channel
recommendations and roam scores are estimated from the BSSIDs
visible to CoreWLAN in the latest scan. They reward stronger RSSI,
better SNR, cleaner bands, and less crowded channels, and they
penalize open networks and security mismatches. Treat them as
"where to look next" hints rather than as Apple's official roaming
decision.

**`OPEN` means no Wi-Fi-layer password/encryption.** Captive portals
can still ask for login after association, but the radio link itself
is open. The Nearby BSSIDs panel marks these rows so you can assess
guest networks and accidentally-open SSIDs quickly.

**Without the helper, the Nearby BSSIDs scan list is fully redacted.**
RSSI, channel, band, and width still come through, but every SSID
shows `(redacted)` and every BSSID `(redacted)`. The Connection
panel itself is unaffected — `wifiscope` reads SSID and BSSID for
the *current* AP through a separate SCDynamicStore tunnel that
macOS forgot to redact.

**BLE devices rotate their identifier for privacy.** The same
physical device (an AirTag, a phone, an Apple Watch) appears under
multiple CoreBluetooth UUIDs over time. wifiscope's fuzzy merger
collapses obvious duplicates into one row by matching `(vendor_id,
name)` plus an RSSI window, and shows a `(merged N)` badge on the
combined entry, but the heuristic is conservative — anonymous
beacons (no vendor, no name) are never merged because conflating
them would silently remove signal. Expect to see one or two extra
rows per rotating device when names disagree.

**BLE range is short** (~10 m vs Wi-Fi's ~30 m), so the BLE list
will feel "smaller" than the Wi-Fi scan even on a busy floor.

**macOS hides the underlying BLE MAC**. CoreBluetooth gives only
a per-host UUID; vendor identification goes through the
manufacturer-data company ID field exclusively. wifiscope decodes
the *public* portions of Apple Continuity (the Nearby Info
device-class nibble — `iPhone` / `iPad` / `Mac` / `Apple TV` /
`HomePod` / `Apple Watch`) and the Find My / iBeacon signatures,
but the encrypted payloads (lock state, AirDrop, Music-playing,
Handoff session info) stay opaque. Per-model identification
(iPhone 14 vs 15) is *not* in any public ad packet — anyone
claiming to do that is reading proprietary GATT services after
connecting, which we will not do.

**The Environment line is *not* Wi-Fi sensing.** wifiscope sits in
Tier 0 of the Wi-Fi-sensing capability ladder: rolling RSSI variance
on the data CoreWLAN already exposes. We surface a binary
`stable` / `active` (or `quiet` after `wifiscope calibrate`)
qualifier — never people-counting, never motion-with-pose, never
breathing rate. Channel State Information (the data the academic
sensing literature actually uses) is not exposed by macOS, and even
where it is exposed (ESP32, Intel 5300 under Linux) the Tier-3+
demos require a research stack, not a `pip install`. See
[`docs/explainers/wifi-sensing.md`](docs/explainers/wifi-sensing.md)
for the full story; the `Environment` line is the live example of
what we honestly do with RSSI.

**Connected peripherals have no RSSI.** `retrieveConnectedPeripherals`
gives us the list of devices currently associated with the Mac
(AirPods you're listening to, Magic Keyboard you're typing on),
but reading their signal mid-session would require `readRSSI()`
against an active connection — an invasive perturbation we
deliberately avoid. The Connected section shows `—` for the
signal column and sorts alphabetically by name.

**`disassociate()` is unreliable for forcing a roam.** Earlier
versions of `wifiscope` used `iface.disassociate()` for the `c`
binding; on 802.1X enterprise networks it would tear down the link
and macOS would not auto-rejoin. Cycling power via
`setPower(false)` then `setPower(true)` mirrors the Wi-Fi-menu
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

## Specifications

Wifiscope runs on OpenSpec-style SDD. Every behaviour-affecting
capability has a canonical contract under `openspec/specs/<name>/spec.md`.

- **Workflow** (English): [`docs/workflow.md`](docs/workflow.md)
- **Workflow** (中文): [`docs/zh/workflow.md`](docs/zh/workflow.md)
- **Agent rules**: [`openspec/AGENTS.md`](openspec/AGENTS.md)
- **Test plan**: [`tests/TESTING.md`](tests/TESTING.md) ([中文](docs/zh/TESTING.md))
- **PR template**: [`.github/pull_request_template.md`](.github/pull_request_template.md)
- **CI gates**: pytest matrix · regression · `openspec --strict` validation

| Capability | What it owns |
|---|---|
| [`macos-helper`](openspec/specs/macos-helper/spec.md) | Swift helper bundle (TCC, subprocess contract, schemas) |
| [`wifi-scanning`](openspec/specs/wifi-scanning/spec.md) | What a scan row promises; redaction handling |
| [`bluetooth-scanning`](openspec/specs/bluetooth-scanning/spec.md) | Schema-4 raw passthrough, vendor resolution chain, anonymous-vs-unknown |
| [`ble-decoders`](openspec/specs/ble-decoders/spec.md) | Per-protocol decoder framework (iBeacon / Eddystone / Apple Continuity / MS CDP / RuuviTag) |
| [`ble-detail-modal`](openspec/specs/ble-detail-modal/spec.md) | Per-device inspect modal: selection, sparkline, decoded payload |
| [`link-health`](openspec/specs/link-health/spec.md) | Gateway/WAN ping aggregates, jitter/loss bursts |
| [`environment-monitor`](openspec/specs/environment-monitor/spec.md) | RF stir detector, σ baselines, calibration |
| [`events`](openspec/specs/events/spec.md) | Five-event vocabulary, ring buffer, JSONL serialisation |
| [`event-log`](openspec/specs/event-log/spec.md) | JSONL writer for `--log` and `wifiscope monitor` |
| [`analyze`](openspec/specs/analyze/spec.md) | Pure-rules log post-processor + heuristic catalogue |
| [`inventory`](openspec/specs/inventory/spec.md) | `aps.yaml` resolution, OUI vendor map, cluster labels |
| [`roam-detection`](openspec/specs/roam-detection/spec.md) | 0–100 link score, +10 dB candidate threshold, press-`c` re-roam |
| [`i18n`](openspec/specs/i18n/spec.md) | EN / ZH UI invariants, JSONL English-keys rule, column-cell math |
| [`tui-shell`](openspec/specs/tui-shell/spec.md) | Four-panel layout, view-toggle, modal lifecycle, GroupedFooter |
| [`cli`](openspec/specs/cli/spec.md) | Subcommand vocabulary, `--lang` precedence, `--log`, exit-hint |

Future capability work flows through `openspec/changes/<name>/`
proposals; no edits to canonical specs outside the archive step
of a merged change.

## Development

```bash
uv sync --all-groups          # installs runtime + dev deps (pytest)
make test                     # full pytest suite
make preview                  # regenerate BOTH preview SVGs (EN + ZH)
make help                     # list all make targets
```

[`tests/TESTING.md`](tests/TESTING.md) is the canonical test plan —
every automated test corresponds to a row in that document, and
changes to test scenarios start there before touching the test
files. **Read it first** when reviewing a PR or extending coverage.

GitHub Actions runs the suite on every push and pull request to
`main`, against Python 3.11 / 3.12 / 3.13 on macOS. CoreWLAN and
SCDynamicStore are not exercised live in CI — those surfaces are
mocked at the subprocess and dynamic-store boundaries.

### Maintaining bilingual UI / docs

Two languages live in this repo and they must move together:

1. **Strings.** Every user-visible literal in `src/wifiscope/`
   routes through `i18n.t(...)`. When you add or edit one, also
   add the matching key to `_ZH` in `src/wifiscope/i18n.py`. A
   missing key falls back to the English source, so a stale
   catalog never breaks the app — but it does silently skip
   translation, so translation lag is on the author of the change.
2. **Docs.** Every English doc has a Chinese mirror under
   `docs/zh/`. When you edit one, edit the other in the same
   commit. The cross-link strip at the top of each file
   (`English · 中文`) makes drift visible to readers.
3. **Preview SVGs.** `docs/preview.svg` (English) and
   `docs/preview.zh.svg` (Chinese) are both rendered from the
   same fake backend in `docs/_capture_preview.py`. **Any UI
   change that affects rendering means rerunning `make preview`**
   so both SVGs stay in sync with the code. A drift here is
   immediately visible in the README hero shot.

`make test-all` exercises the suite under EN, ZH, and locale-
autodetected ZH defaults to catch any binding-order or catalog-
shape regression that one language would not surface alone.

See [`CHANGELOG.md`](CHANGELOG.md) for the version-by-version log.

## Roadmap

Planned, in rough priority order. Things below the divider are
nice-to-have but not on a near-term release schedule.

### Tracked for upcoming releases

- **Latency / packet-loss / jitter probe** — continuous 1 Hz ping
  to gateway and a public DNS, surfaced in Diagnostics. Closes the
  "RSSI looks fine but Zoom is bad" gap that pure radio metrics
  cannot answer; signal strength is necessary but not sufficient
  for "is the link actually working".
- **mDNS / Bonjour LAN device discovery** — new `m`-toggleable view
  alongside Wi-Fi / BLE listing every Sonos, AppleTV, HomePod, NAS,
  printer, AirDrop-capable Mac, HomeKit hub, Time Capsule, and
  other service-advertising peer on the local network. Answers
  "what is on my network and is it alive" with a much richer answer
  than ARP alone, especially in Apple-heavy environments.
- **Beacon Information Element parsing** — surface BSS Load
  (current channel utilization %), 802.11k neighbour reports,
  802.11r fast-roaming capability, and 802.11v BSS Transition
  support per BSSID. The bytes are already in CoreWLAN scan output;
  the helper just doesn't decode them yet. Lets diagnostics say
  "your AP is at 78% utilization" or "3 candidate APs do not
  support fast roaming" instead of guessing from BSSID density.
- **RSSI history sparklines** — a small `▁▂▃▄▅▆▇█` strip in each
  Nearby BSSID row showing the last N scans for that BSSID, so
  trends ("dropping", "stable", "improving") are visible at a
  glance without staring at the panel.
- **JSONL session logging + replay** — `wifiscope log session.jsonl`
  appends every connection / scan / roam / latency event; a
  `wifiscope replay <file>` mode feeds them back through the TUI
  for after-the-fact analysis of an incident.
- **Trend graphs in the TUI** — RSSI / latency / channel utilization
  over time, time-on-AP per BSSID. Builds on JSONL logging.

### Further out

- **Linux backend** — `nl80211` via `pyroute2` or shelling out to
  `iw scan`. Architecturally already abstracted behind `WiFiBackend`.
- **Auto-roam mode** — gated, conservative. When a clearly-better
  same-SSID candidate persists for ≥ N seconds, automatically
  cycle the radio. Solves the original sticky-AP pain hands-free.
- **Optional menu-bar app** for ambient awareness without keeping a
  terminal open.
- **Continuity / Personal Hotspot / iCloud Private Relay state** —
  Mac-specific integrations exposed in Diagnostics.

## License

MIT. See [`LICENSE`](LICENSE).
