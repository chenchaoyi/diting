<p align="right">
  <strong>English</strong> · <a href="docs/zh/README.md">中文</a>
</p>

<p align="center">
  <img src="docs/logo.svg" alt="diting" width="320">
</p>

<p align="center">
  <strong>Your Mac hears more than it tells you.</strong>
  <br>
  <sub>A macOS terminal listening post for Wi-Fi, BLE, link health, and the RF environment.</sub>
</p>

<p align="center">
  <a href="https://github.com/chenchaoyi/diting/actions/workflows/test.yml"><img src="https://github.com/chenchaoyi/diting/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/chenchaoyi/diting/releases"><img src="https://img.shields.io/github/v/release/chenchaoyi/diting?display_name=tag&cacheSeconds=300" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/chenchaoyi/diting?cacheSeconds=300" alt="license"></a>
</p>

---

<p align="center">
  <img src="docs/preview.svg" alt="diting TUI – Wi-Fi view" width="100%">
  <br>
  <sub><i>Wi-Fi view (default)</i></sub>
</p>

<p align="center">
  <img src="docs/preview-ble.svg" alt="diting TUI – BLE view" width="100%">
  <br>
  <sub><i>BLE view (press <code>n</code> to cycle through Wi-Fi / BLE / Bonjour) — Connected peripherals on top, Advertising devices below, each labelled with its public-format identification.</i></sub>
</p>

<p align="center">
  <img src="docs/preview-events.svg" alt="diting TUI – Events modal" width="100%">
  <br>
  <sub><i>Events modal (press <code>m</code> to open) — last 1000 roam / RF-stir / latency / loss / link events, per-AP σ baseline, last-hour σ sparkline.</i></sub>
</p>

## Why

macOS perceives a lot of signal around your Mac — Wi-Fi networks
coming and going, BLE devices broadcasting nearby, gateway latency
stretching, RF noise rising — and its built-in UI shows almost
none of it. Apple's Wi-Fi panel reports the *current* signal and
nothing else. Bluetooth Settings shows what you've paired, never
what's around. macOS has no surface at all for "is my gateway
healthy" or "did something just change in the room."

diting fills that gap. It runs in your terminal as a four-panel
TUI on top of the same APIs Apple uses internally:

- **Wi-Fi visibility.** Every BSSID in range, grouped by physical
  AP. Plain-language diagnostics on top of dense scan data —
  visible-BSSID counts, channel crowding, least-crowded channel
  hints, current-link health, a roam score with reasons. Roam
  events get logged as they happen, tagged
  `[band switch on <AP>]` vs `[inter-AP roam]`.
- **BLE deep identification.** Two sections: *Connected* peripherals
  you're using right now (AirPods, Magic Keyboard, Apple Watch —
  devices that don't advertise and so are invisible to plain BLE
  scanners), and *Advertising* devices broadcasting nearby —
  identified as `AirTag`, `iBeacon`, `Eddystone-URL`, `Tile`,
  `SmartTag`, `iPhone`, `Mac`, `Apple Watch`, `HomePod` instead of
  the "Apple, Inc. (anonymous) Find My" wall. Press `i` (or click a
  row) on any list view — Wi-Fi, BLE, or Bonjour — for a detail
  modal: every field the snapshot carries, decoded payloads, RSSI
  history sparklines and distance estimates where the data permits.
- **Link health.** Continuous gateway + WAN probes. The `Link` row
  reads `gw 12 ms · 0% · WAN 18 ms · 0% · jitter 3 ms` so a -55 dBm
  AP that *looks* fine reads correctly as bad when upstream is
  dropping packets.
- **RF environment monitor.** Rolling RSSI variance per AP with a
  `stable` / `active` qualifier (calibrate to `quiet` with
  `diting calibrate`). Surfaces "something changed" without making
  a presence claim — correlation, never causation. **NOT** Wi-Fi
  sensing — see
  [`docs/explainers/wifi-sensing.md`](docs/explainers/wifi-sensing.md)
  for what diting deliberately does not claim.
- **Unified events log.** Roam / RF stir / latency spike / loss
  burst / link state — all five event types stream into one ring
  buffer. Press `m` for a full-screen browser of the last 1000; use
  `diting stream` for headless JSONL output to a Home Assistant
  pipeline or a `tail -F` audit window.

For instance: you walk between rooms, your Mac stays glued to the
AP it associated with five hours ago at -75 dBm — even though
there's a new -45 dBm one within reach broadcasting the same SSID.
Zoom stutters and you blame the Wi-Fi. Apple's panel won't tell you
which AP you're on; diting will, and the `c` binding cycles the
radio so macOS re-runs auto-join and reassociates with the strongest
BSSID. Same path as menu-off-then-on, in one keystroke.

## What you can do with it

- **Diagnose home or office network issues.** When Zoom is bad — is
  it RSSI? gateway? WAN? a noisy channel? someone hammering the
  uplink? The Diagnostics panel + `Link` row + Events strip narrow
  it down without you reading raw packets.
- **Find Bluetooth things around you.** What IoT is in this room?
  Where's that AirTag? The BLE list resolves vendor + protocol on
  every advertising device; the detail modal's RSSI sparkline lets
  you walk a target down by signal strength. Anonymous adverts
  (vendor + RSSI only, no name) are gated by a 5-second presence
  window before they fire a `seen` event, which kills single-packet
  ghost flicker in dense RF environments while preserving real
  walk-bys; tune with `--ble-presence-gate DURATION` (`0` to
  capture every ephemeral advert).
- **See who's on your Wi-Fi.** The fourth panel (cycle to it via
  `n`) lists every host on your local subnet — IP, MAC, vendor,
  hostname, Bonjour name. ARP cache + ICMP sweep; no router
  login needed. Default /24 sweep; `DITING_LAN_INVENTORY_WIDE=1`
  unlocks a /22 sweep for wider home subnets.
- **Catch anomalous signals.** Latency spikes, loss bursts,
  unexplained RF variance — diting names what changed and when.
  Long-running sessions land in `--log` JSONL for after-the-fact
  analysis with `diting analyze`.
- **Read the rhythm of a long capture.** Point `diting analyze`
  at a single overnight log (or multiple files with `--since 7d`)
  and it surfaces what a per-session report misses: the BLE
  arrival rhythm (peak / quiet hours), a dwell distribution
  (foot-traffic vs residents), the distinct device population
  counted by *stable* identity (real devices, not rotated
  addresses), scene-aware off-hours activity, and cross-signal
  coincidences (loss concentrated in the busy arrival hours →
  airtime contention) — plus hour-of-day / heatmap / per-network /
  daily-trend / top-contributor charts.
- **Drive it from an agent or a script.** `once`, `watch`, and
  `analyze` accept `--json` for clean machine-readable output
  (keys stay stable English even under `--lang zh`); the CLI never
  prints a traceback and has documented exit codes. See
  [Use from an agent](#use-from-an-agent-or-a-script).
- **Hand it to an AI chat for richer interpretation.**
  `diting analyze --for-llm` writes one self-contained `.md`
  (analyst prompt + the full report) and copies it to your
  clipboard — open any AI chat (Claude / ChatGPT / DeepSeek /
  Gemini / Kimi / …), paste, and get back pattern clustering and
  hypothesis-ranking. Add `--anonymize` to scrub SSIDs / BSSIDs /
  RFC1918 IPs / hostnames / BLE identifiers before pasting into
  a public LLM. The handle↔original mapping prints to your
  terminal only — never into the file or onto the clipboard.
- **(Future) Room-presence sensing.** Long-term, hardware-assisted
  flagship. See [Roadmap](#roadmap).

## Scenes (`--scene SCENE`)

diting carries a notion of *where the user is right now*. Four
scenes ship today, each tuned for one class of environment:

| Scene | When to use | What it changes |
|---|---|---|
| `home` (default) | apartment / own Wi-Fi, ≤ ~15 BLE devices, single AP | BLE presence gate **5 s** — kills 0 s ghost flicker but keeps brief contacts |
| `office` | corp floor, enterprise Wi-Fi, dense BLE + many BSSIDs | BLE presence gate **15 s** — absorbs the Continuity RPA churn baseline |
| `public` | cafe / train / plane / public Wi-Fi | BLE presence gate **30 s** — almost everything is passers-by |
| `audit` | actively investigating (security research, debug, forensics) | BLE presence gate **0 s** — record every advert |

### Auto-detect (default)

When you don't pass `--scene` and don't set `DITING_SCENE`, diting picks the scene itself by inspecting the active Wi-Fi connection at startup. The rules are simple, deterministic, and run on local state only — no probes, no phone-home:

1. **Enterprise auth** (WPA2 Enterprise / WPA3 Enterprise / 802.1X) → `office`
2. **≥ 30 visible BSSIDs** in the most recent CoreWLAN scan → `office`
3. **otherwise** → `home`

`public` stays opt-in (captive-portal detection without active probing is unreliable). When the auto-detect runs, diting prints a one-line banner to stderr explaining what it picked and why:

```
$ diting
auto-detected scene: office (WPA2 Enterprise auth)
```

Suppress the banner with `DITING_SCENE_QUIET=1`.

### Pin per-network in `scenes.yaml`

For networks you visit regularly, copy `scenes.example.yaml` to `scenes.yaml` (git-ignored) and map SSID → scene:

```yaml
networks:
  - ssid: HomeNet
    scene: home
  - ssid: Meituan
    scene: office
  # Use gateway_mac when SSID is reused across networks (eduroam):
  - gateway_mac: 14:51:7e:71:5a:1a
    scene: office
```

A yaml hit wins over the auto-detect. The banner becomes:

```
pinned scene: office (matched "Meituan" in scenes.yaml)
```

Override the file location with `DITING_SCENES_FILE=/path/to/scenes.yaml`.

### Explicit override

CLI flag and env var still take precedence over scenes.yaml and the heuristic:

```
diting --scene office             # this session
DITING_SCENE=office diting        # persistent (e.g. shell rc)
```

The active scene is tagged into the JSONL session header
(`session_meta`) so `diting analyze` can group cross-session
aggregations by scene, and the `--for-llm` bundle injects the
scene's baseline expectation into the prompt template — the LLM
reads office-mode noise as "expected baseline" rather than
"anomalous", and home-mode novelty as "interesting" rather than
"signal in the bin".

`--ble-presence-gate D` continues to override the scene's gate
when you want fine control for one session.

## LAN identification

The LAN view (fourth `n` press) discovers every host on the local
/24 via ARP + ICMP sweep, then enriches each row through a layered
identification stack:

- **Multi-tier OUI lookup** — IEEE MA-L (24-bit) → MA-M (28-bit) →
  MA-S (36-bit), longest prefix wins. The bundled JSONs together
  carry ~57k vendor mappings, so small white-label IoT vendors
  (Tuya / Aqara / Tapo / Imou …) that only registered MA-S
  sub-allocations still resolve to a real name.
- **Vendor normalization** — the raw IEEE string is shortened for
  display (`NEW H3C TECHNOLOGIES CO., LTD` → `New H3C`,
  `SHENZHEN BILIAN ELECTRONIC CO.,LTD` → `Bilian`). The original
  text is preserved on a dim continuation line in the detail modal.
- **Reverse DNS + Bonjour cross-reference** — `gethostbyaddr`
  hostname when the router publishes PTR records, plus a sweep of
  the live Bonjour state for any device matching this IP.
- **Active discovery** — NBNS Status Query (UDP 137 unicast),
  SSDP M-SEARCH (UDP 1900 multicast), and an mDNS browse query
  for the meta-service record. Optionally fetches the UPnP
  LOCATION XML for `friendlyName` + `modelName`. Layered on top
  so a host that publishes neither Bonjour nor reverse DNS — most
  Windows machines, IP cameras, smart TVs, NAS — still becomes
  identifiable.
- **TTL fingerprint** — the ICMP echo already returns a TTL value;
  diting buckets it into `unix` (50-64), `windows` (100-128), or
  `router` (200-255). Surfaces in the detail modal as e.g.
  `TTL 64 (unix)`.
- **Device class** — a rules-table classifier consumes vendor,
  Bonjour categories, NBNS / UPnP fields, and TTL to assign one
  of: `phone | tablet | laptop | desktop | tv | camera | smart-home |
  printer | nas | gaming | speaker | router`. Rendered as the
  leftmost data column on each row.

Rows whose `first_seen < 24 h` are prefixed with a `[new]` chip
so unfamiliar devices stand out at a glance.

### Active probing is scene-aware

The active-discovery layer is the one piece of LAN identification
that **sends packets to other hosts**. To stay polite about that,
diting gates the layer through the active scene:

| Scene    | NBNS + SSDP + mDNS-meta | Why                                                                                  |
|----------|--------------------------|--------------------------------------------------------------------------------------|
| `home`   | on by default            | Your own network. Probes go to devices you bought.                                   |
| `office` | on by default            | Corp networks already see this traffic from every other device.                      |
| `audit`  | on by default            | You're actively investigating; probe everything.                                     |
| `public` | **off by default**       | Coffee shops / hotels / airports — you don't own the network, other guests do.       |

Two env vars override the scene default at startup:

- `DITING_LAN_PROBE=0|1` — force probing off / on regardless of
  scene.
- `DITING_LAN_UPNP_FETCH=0|1` — gate the optional HTTP fetch of
  UPnP LOCATION URLs (set to `0` to keep M-SEARCH on but skip the
  follow-up fetch). Default on.

### Public-scene one-shot consent

In `public` scene the LAN view binds uppercase **`P`** to a
consent modal:

```
┌─ Active LAN probing ──────────────────────────────────┐
│  Scene: public        Network: HotelGuest             │
│                                                       │
│  Active probing sends UDP packets to OTHER hosts on   │
│  this network:                                        │
│    · NBNS UDP 137 unicast                             │
│    · SSDP M-SEARCH UDP 1900 multicast                 │
│    · mDNS UDP 5353 multicast                          │
│                                                       │
│  On a public network you accept that:                 │
│    · other guests' devices receive your probes        │
│    · hotel / airport IDS may flag this as scanning    │
│    · captive portals may rate-limit or disconnect     │
│                                                       │
│  One-shot probe. Re-confirm next time.                │
│                                                       │
│  [ esc cancel ]   [ wait 2s ]                         │
└───────────────────────────────────────────────────────┘
```

Press `y` after a 2-second cooldown (defeats muscle-memory
press-through) to run **one** active-probe sweep and write a
`lan_active_probe_consented` line to your JSONL log. Subsequent
sweeps revert to passive — every press of `P` re-opens the
modal, no sticky state.

## The name

**diting (谛听)** is a mythical beast in Chinese Buddhist lore —
the divine mount of Kṣitigarbha Bodhisattva (地藏王菩萨). It is
said to hear every sound in heaven, on earth, and across the ten
directions; one ear pressed to the ground, it can tell truth
from falsehood, virtue from sin, and the present from the past.
Your Mac sits at the centre of a smaller ten directions of its
own — Wi-Fi networks coming and going, BLE devices whispering
nearby, upstream packets quietly dropping — and, left to itself,
it never relays a word of any of it.

**tianer (天耳)** — literally "heavenly ear" — is the ear
behind 天耳通, one of the Six Supernormal Powers (六神通) in
Buddhist tradition: the faculty of clairaudient hearing, by
which sounds too far, too faint, or too hidden for ordinary
ears can still be made out. 谛听's reputation for hearing all
ten directions rests on this faculty — the beast is the
listener, but 天耳 is the ear it listens through.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
diting
```

One command. No Python, no `uv`, no Xcode Command Line Tools on
your machine — the installer downloads a self-contained binary
plus the helper bundle and drops them in
`~/.local/share/diting/` and `~/Library/Application Support/diting/`.
On first run the helper opens a small status window and walks you
through three macOS permission prompts in order — Location → Bluetooth
→ Notifications — one at a time. Click Allow on each and the TUI
launches with full SSID, BSSID, and BLE data, plus diting-branded
notifications when the watchdog detects an anomaly.

> **Why the helper?** macOS 14.4+ redacts SSID and BSSID to None
> unless the calling process has Location Services. A Python CLI
> launched from Terminal cannot get on that list, but a tiny `.app`
> bundle can. `diting` shells out to it for scan data and gets the
> real values back. Press `?` inside the TUI for the full story.

Pin a specific release:

```bash
DITING_VERSION=v0.10.0 curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
```

From inside China? If the direct GitHub download stalls or times out
(`curl --max-time 20`), the installer walks a chain of public GitHub
mirrors (`ghfast.top` → `gh-proxy.com` → `ghproxy.net`), and validates
every download before trusting it — a mirror that answers with an HTML
error/landing page (a `200` that isn't the real file) is skipped and
the next one tried. `SHASUMS256.txt` is fetched GitHub-direct first
regardless of where the tarball comes from, and SHA256 verification
always anchors on it, so a hostile mirror can't slip in a forged
tarball. To skip the 20-second GitHub-first wait once you know GitHub
is unreachable from your network:

```bash
DITING_INSTALL_MIRROR=ghproxy curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
```

Other `DITING_INSTALL_MIRROR` values:

- `github` — canonical-only, no mirrors (single trust path).
- `https://your-proxy.example/` — a custom or self-hosted GitHub proxy
  used as the sole mirror (prefix form: `<proxy><github-url>`). Best
  if you run your own proxy and want full control of the trust path.

If even fetching `install.sh` fails — `curl: (35) … SSL_ERROR_SYSCALL
in connection to raw.githubusercontent.com:443` is the usual shape —
the block is upstream of the script, so no script logic can help.
Fetch the script itself through a chain proxy (same prefix
convention):

```bash
curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
```

Honest caveat: piping a proxy-served script to `bash` trusts that
proxy with the script's contents (the SHA256 verification inside it
only protects the release assets). If that bothers you, download the
script first, read it, then run it:

```bash
curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh -o install.sh
less install.sh   # it's ~700 lines of commented bash
bash install.sh
```

### From source (for contributors)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/), plus the
Xcode Command Line Tools (the helper bundle is built from Swift
sources on first launch).

```bash
git clone git@github.com:chenchaoyi/diting.git
cd diting
uv sync
make helper          # one-time: build + sign the Swift helper bundle
open helper/diting-tianer.app   # one-time: grant Location → Bluetooth → Notifications
uv run diting
```

`uv run diting` and the curl-installed `diting` can coexist on the
same machine — the developer flow keeps picking up the in-repo
helper, the installed binary uses its own copy under Application
Support.

## After-the-fact analysis (`diting analyze`)

Run `diting analyze <log.jsonl>` against a `--log`-produced
JSONL to get a rule-based report — heuristics that name what
went wrong (`Frequent inter-AP roams`, `Real packet loss
observed`, `Repeated disassociations`, etc.) plus a connection
timeline and an actionable TODO list per insight.

Point it at multiple files (shell glob) with an optional
`--since DURATION` filter to surface patterns single-session
reports can't:

```bash
diting analyze 'diting-*.jsonl' --since 30d
```

…produces, on top of the per-session block, **temporal &
population intelligence** whenever the capture is a long-timeline
run — a single overnight log (≥ 2 h), multiple files, or a
`--since` window:

- **BLE arrival rhythm** — the peak / quiet hours and whether
  activity is a concentrated daily cycle (people arriving /
  leaving) or a flat background
- **Dwell distribution** — transient pass-bys vs lingering vs
  resident devices (p50 / p90), reading a high transient share as
  foot-traffic rather than a fixed population
- **Device population** — distinct *physical* devices counted by
  **stable identity** (never the rotating BLE address, which would
  report thousands of phantoms), split into all-span fixtures vs
  single-hour pass-bys
- **Off-hours activity** — scene-aware: activity when the scene
  expects quiet (office overnight, home workday) is flagged as
  more noteworthy than the same activity in-hours
- **Cross-signal coincidence** — when loss / latency / stir
  concentrate in the busy arrival hours, a hypothesis (e.g.
  airtime contention as people arrive) with a concrete next
  capture window — never an asserted cause
- **Events by hour-of-day** / **Day × hour heatmap** — a 24-row
  ASCII bar chart + a 7×24 `▁▂▃▄▅▆▇█` density grid
- **Top networks** — events per associated BSSID, ranked
- **Daily trend** — per-day total + 7-day rolling average
- **Top contributors** — BSSIDs by roam + RF-stir count; **BLE
  devices by sighting count** (keyed on stable identity, so a
  privacy-rotating device's many addresses fold into one row);
  LAN hosts by DHCP-rotation count
- **Monitoring coverage** — which signals were watched, and what
  *silence* means: zero `latency_spike` under active probing reads
  as "latency probed, link stable," not "unknown"; an inactive
  monitor is "not observed." So a quiet capture says something
  instead of nothing.
- **Connection quality** — RSSI p50 / min / max, SNR, and the
  steady channel / band / PHY, so even a static single-BSSID
  session conveys signal strength.
- **Neighbors** — visible BSSID count + co-channel count, for
  interference context the roam events can't convey.

`--since` accepts `30d` / `7d` / `24h` / `90m` / `60s`. A short
single-session log (no `--since`, under ~2 h) keeps the lean
per-session layout. The whole report is also available as one
JSON document via `diting analyze --json` — see
[Use from an agent](#use-from-an-agent-or-a-script).

### Hand the data to an AI chat for richer interpretation

```bash
diting analyze 'diting-*.jsonl' --since 30d --for-llm
```

Writes **one** self-contained file —
`./diting-analysis-for-llm-<timestamp>.md` — and **copies it to your
clipboard**. The file holds the analyst prompt followed by the full
Markdown report inline (tables for ranked data, fenced code blocks for
the ASCII charts, a glossary of diting-specific terms), so the model
gets the instructions *and* the data in one piece. The workflow is just:

```
run → open any AI chat → ⌘V → submit
```

No drag-drop, no second copy. Under `--lang zh` the whole document
— the analyst prompt and the report — is written in Chinese and the
prompt asks the model to answer in Chinese, so you get a Chinese
analysis back (technical tokens like `ble_device_seen` stay verbatim).
Any capable chat works — Claude (`claude.ai`), ChatGPT
(`chat.openai.com`), DeepSeek (`chat.deepseek.com`), Gemini, Kimi, or
whatever you use. `-o PATH`
sets the output (`-o run.md` for a file, `-o dir/` for a directory). No
API key, no telemetry, no upload — diting writes the file locally and
puts it on your clipboard; you control who sees it.

Want the model to have the complete event log, not just the
distilled briefing? Add `--raw`:

```bash
diting analyze diting-20260608.jsonl --for-llm --raw
```

The briefing still goes to your clipboard; `--raw` additionally tells
you to **attach your existing `.jsonl`** to the same chat (it references
the original file — no copy, no rewrite), and the prompt tells the model
the raw log is attached for deep-dives (exact timestamps, RSSI sequences,
event ordering) while trusting the briefing's stable-identity figures for
counts. The raw log is large, so it's a file attachment, not a paste.
With `--anonymize`, the only file diting writes is a scrubbed
`diting-raw-anonymized-<timestamp>.jsonl` (real identifiers — including
device names — replaced with the briefing's handles), and that's what
you attach instead of the original.

Add `--anonymize` when pasting into a public LLM:

```bash
diting analyze 'diting-*.jsonl' --since 30d --for-llm --anonymize
```

SSIDs / BSSIDs / RFC1918 IPs / hostnames / BLE identifiers /
LAN MACs get replaced with stable handles (`SSID_1`, `AP_1`,
`IP_1`, `HOST_1`, `BLE_1`, `MAC_1`). Public IPs (`8.8.8.8`,
`1.1.1.1`) and vendor names (`Apple, Inc.`, `Cisco Systems`)
pass through unchanged. The handle↔original mapping prints
to the terminal only — never into the file or onto the
clipboard — so you can decode the LLM's references later
without leaking the mapping into the chat.

### Use from an agent or a script

The CLI is JSON-first and self-describing, so a coding agent (Claude
Code et al.) or a script can collect signals without scraping prose.
Start with `diting capabilities --json` to discover the whole surface:

```bash
diting capabilities --json | jq '.commands[].name'   # discover verbs
diting status --json | jq .connection.rssi_dbm       # current RSSI
diting scan --json | jq '.wifi | length'             # one-shot Wi-Fi + BLE
diting analyze diting-20260608.jsonl --json | jq .insights
diting stream --duration 5m | jq -c 'select(.type=="roam")'  # bounded JSONL
```

`status` / `scan` / `analyze` / `capabilities` each accept `--json` and
print one JSON document; `stream` emits canonical event-log JSONL (the
same schema `analyze` consumes). JSON goes to stdout, all human chrome
(banners, hints) to stderr, and JSON keys stay stable English regardless
of `--lang`. The CLI never prints a traceback — an unexpected error is
one `diting: <message>` line (a JSON `{"error", "code"}` object under
`--json`), and exit codes are stable: `0` ok · `1` runtime error (incl.
`status` when not associated) · `2` usage error. `DITING_DEBUG=1`
restores the traceback for debugging. Run `diting <subcommand> --help`
for per-command usage and examples, or see the
[agent guide](docs/agents.md).

The verbs were renamed for agent ergonomics: `once` → `status`, `watch`
/ `monitor` → `stream`. The old names still work as deprecation aliases
(one stderr notice, then they forward).

## Switching language

```bash
uv run diting --lang zh           # force Chinese
DITING_LANG=zh uv run diting   # via env var
```

With no override, `diting` autodetects the system locale —
`LANG=zh_CN.UTF-8` defaults to Chinese; everything else stays English.

## Bindings

| Key | Action |
|-----|--------|
| `q` | quit |
| `p` | pause / resume polling |
| `r` | force a rescan now (CoreWLAN ~5 s throttle still applies) |
| `s` | cycle sort — Wi-Fi: by AP ↔ by signal; Bonjour: service ↔ by-host |
| `n` | cycle Nearby view: Wi-Fi BSSIDs → BLE → Bonjour → LAN |
| `z` | zoom — maximize the Nearby list panel to the full screen (live updates, sorting and row selection keep working); `z` or Esc restores, and the zoom follows `n` across views |
| `c` | Wi-Fi view only: force re-roam — cycle Wi-Fi off/on so macOS re-picks the strongest BSSID |
| `m` | open / close the Events modal — last 1000 roam / stir / latency / loss / link events |
| `?` | open / close the in-app help screen |
| `b` | open / close Wi-Fi Basics: SSID, BSSID, channel, band, security, roam score |
| `j` | (in the Wi-Fi detail modal) join the inspected SSID — previously-saved networks confirm via Touch ID (or login password on Macs without a sensor) and join silently; new networks get a native macOS password prompt. Not hitless: a cross-SSID switch tears the current connection down for ~2-5 s. Enterprise / 802.1X is refused with a hint. |

The `status`, `scan`, `stream`, and `calibrate` subcommands run
diting without the TUI:

```bash
uv run diting status                     # snapshot of current connection, exit
uv run diting scan                       # one-shot Wi-Fi + BLE sensor snapshot
uv run diting scan --lan --mdns          # one-shot LAN host + Bonjour snapshot
uv run diting stream                     # headless canonical JSONL to stdout (wifi+latency+rf)
uv run diting stream --sensors all       # full sensor set (adds BLE / LAN / mDNS)
uv run diting stream --out events.jsonl  # append JSONL to a file
uv run diting stream --duration 5m       # bounded run, then exit
uv run diting stream --notify            # macOS Notification Centre alerts on high-confidence events
uv run diting capture start --name watch --sensors all  # detached long watch
uv run diting capture list               # sessions + live status
uv run diting capture tail --name watch -n 50 -f        # follow a session's JSONL
uv run diting capture stop --name watch  # clean SIGTERM stop (complete capture)
uv run diting setup                      # (re)grant the helper's macOS permissions
uv run diting setup --json               # check permission state (non-blocking)
uv run diting calibrate                  # 5 min "empty room" RSSI baseline → ./diting-baseline.json
uv run diting companion pair             # pair a phone — renders a QR for diting-mobile
uv run diting companion status           # show pairing + relay queue state
uv run diting capabilities --json        # machine-readable CLI manifest
```

The `monitor` subcommand is the long-run / Home Assistant
integration target — every roam, RF stir, latency spike, loss
burst, and link-state change emits one well-formed JSON line. The
schema lives in
[`docs/specs/v0.7.0-network-ground-truth-and-environment-monitor.md`](docs/specs/v0.7.0-network-ground-truth-and-environment-monitor.md#single-eventsjsonl-schema-for-all-three-layers).

### Pair with diting-mobile (`diting companion`)

Forward events to the companion **diting-mobile** app so your phone learns
what the Mac sees — anywhere, not just on the same Wi-Fi.
`diting companion pair` generates a channel + key and prints a QR; scan it in
the app. After that, a running `diting` (TUI or `monitor`) forwards
push-worthy events, and the phone pulls and decrypts them.

- **Encrypted by default.** The full event is sealed with libsodium secretbox
  under a key that only ever travels in the QR; the relay (a Cloudflare Worker)
  stores and forwards that ciphertext only. To make the notification useful at
  a glance, the push also carries a short one-line summary in cleartext (e.g.
  "BLE nearby: Magic Keyboard") — composed on the Mac, shown by the phone, and
  visible to the relay and Apple in transit. It names only the same
  low-sensitivity detail the app already shows; the structured event stays
  encrypted in the envelope.
- **Opt-in.** Nothing leaves the Mac until you pair. `diting companion unpair`
  stops it; `DITING_COMPANION=0` (or the `--no-companion` flag, e.g. for a
  self-test run that shouldn't spam your phone) disables forwarding without
  unpairing. When paired, the TUI header shows a `companion:` chip with the
  relay queue state.
- **Connected-count on the pairing screen.** The QR view (`k`) shows whether
  any phone is currently pulling this channel — a privacy-light count, not a
  device list (the relay tracks recent pullers by an opaque per-connection
  hash, no identity).
- **Honest limit.** The event source is this Mac — a sleeping laptop emits
  nothing. 24/7 home monitoring is a separate always-on device, not this.

Pairing state lives in `./diting-companion.json` (git-ignored — it holds the
secret key). Closed-app push needs APNs configured on the relay; see
[`relay/README.md`](relay/README.md).

## Configuration

### AP aliases (optional)

`diting` works fine without any AP-name configuration — every
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

`diting` then renders **`2F-living (5G)` (40:fe:95:8a:3c:58)** in
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

Set `DITING_INVENTORY=/some/path/aps.yaml` to load the file from
somewhere other than the current working directory.

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `DITING_LANG` | autodetected | UI language: `en` or `zh`. Equivalent to `--lang`. |
| `DITING_INVENTORY` | `./aps.yaml` (CWD-relative) | Path to the AP-aliases YAML. The file is optional; if absent, diting uses auto-cluster labels. |
| `DITING_HELPER` | searched in `/Applications`, `~/Applications`, repo `helper/` | Path to the `diting-tianer.app` bundle or its binary. |
| `DITING_SCAN_INTERVAL` | `7` | Seconds between scans. CoreWLAN throttles around 5 s, so values below ~6 yield empty scans every other call. Floor 3. |
| `DITING_LATENCY_WAN_TARGET` | autodetected from `scutil --dns` | IP for the WAN latency anchor. Default picks the first non-gateway nameserver from `SCDynamicStoreCopyValue("State:/Network/Global/DNS")`; if the only configured DNS *is* the gateway, the WAN probe is skipped and the diagnostic line reads `WAN n/a (DNS == gateway)`. Override to pin an explicit IP (e.g. `1.1.1.1` for networks that allow it). |
| `DITING_LAN_INVENTORY_WIDE` | unset | When set to `1`, the LAN view sweeps a /22 (1022 hosts) around your interface IP instead of the default /24 (254 hosts). Useful on home subnets wider than /24; on corporate /16+ VLANs the sweep is still capped at /22 around your IP. |
| `DITING_COMPANION` | unset | Set to `0` to disable companion forwarding without unpairing. Any other value (or unset) leaves it active when paired. |
| `DITING_COMPANION_STATE` | `./diting-companion.json` (CWD-relative) | Path to the companion pairing-state file (holds the secret key; git-ignored). |

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
panel itself is unaffected — `diting` reads SSID and BSSID for
the *current* AP through a separate SCDynamicStore tunnel that
macOS forgot to redact.

**BLE devices rotate their identifier for privacy.** The same
physical device (an AirTag, a phone, an Apple Watch) appears under
multiple CoreBluetooth UUIDs over time. diting's fuzzy merger
collapses obvious duplicates into one row by matching `(vendor_id,
name)` plus an RSSI window, and shows a `(merged N)` badge on the
combined entry, but the heuristic is conservative — anonymous
beacons (no vendor, no name) are never merged because conflating
them would silently remove signal. Expect to see one or two extra
rows per rotating device when names disagree. For how diting derives a
*stable* per-device identity across rotation (for familiarity / recurrence
— manufacturer payload → MiBeacon service-data MAC → company-id+name →
vendor group, never the spoofable name), see
[`docs/explainers/ble-identity.md`](docs/explainers/ble-identity.md).

**BLE range is short** (~10 m vs Wi-Fi's ~30 m), so the BLE list
will feel "smaller" than the Wi-Fi scan even on a busy floor.

**macOS hides the underlying BLE MAC**. CoreBluetooth gives only
a per-host UUID; vendor identification goes through the
manufacturer-data company ID field exclusively. diting decodes
the *public* portions of Apple Continuity (the Nearby Info
device-class nibble — `iPhone` / `iPad` / `Mac` / `Apple TV` /
`HomePod` / `Apple Watch`) and the Find My / iBeacon signatures,
but the encrypted payloads (lock state, AirDrop, Music-playing,
Handoff session info) stay opaque. Per-model identification
(iPhone 14 vs 15) is *not* in any public ad packet — anyone
claiming to do that is reading proprietary GATT services after
connecting, which diting will not do.

**The Environment line is *not* Wi-Fi sensing.** diting sits in
Tier 0 of the Wi-Fi-sensing capability ladder: rolling RSSI variance
on the data CoreWLAN already exposes. The line surfaces a binary
`stable` / `active` (or `quiet` after `diting calibrate`)
qualifier — never people-counting, never motion-with-pose, never
breathing rate. Channel State Information (the data the academic
sensing literature actually uses) is not exposed by macOS, and even
where it is exposed (ESP32, Intel 5300 under Linux) the Tier-3+
demos require a research stack, not a `pip install`. See
[`docs/explainers/wifi-sensing.md`](docs/explainers/wifi-sensing.md)
for the full story; the `Environment` line is the live example of
what diting honestly does with RSSI.

**Connected peripherals have no RSSI.** `retrieveConnectedPeripherals`
returns the devices currently associated with the Mac
(AirPods you're listening to, Magic Keyboard you're typing on),
but reading their signal mid-session would require `readRSSI()`
against an active connection — an invasive perturbation diting
deliberately avoids. The Connected section shows `—` for the
signal column and sorts alphabetically by name.

**`disassociate()` is unreliable for forcing a roam.** Earlier
versions of `diting` used `iface.disassociate()` for the `c`
binding; on 802.1X enterprise networks it would tear down the link
and macOS would not auto-rejoin. Cycling power via
`setPower(false)` then `setPower(true)` mirrors the Wi-Fi-menu
off/on path and reliably triggers full auto-join with Keychain
credentials.

## Contributing

Contributing? See [`DEVELOPMENT.md`](DEVELOPMENT.md) for the SDD
workflow, capability index, local development commands, bilingual
discipline, and an implementation deep-dive (BSSID resolution,
channel handling, pluggable backend).

Version history lives in [`CHANGELOG.md`](CHANGELOG.md).

## Roadmap

Three buckets: *near-term* gets actively worked, *mid-term* is on
the queue with a clear shape, *further out* is direction without a
timeline. No specific dates — diting is a personal project; the
ordering is intent.

### Near-term

- ~~**mDNS / Bonjour LAN inventory.**~~ **[shipped]** A
  `n`-toggleable view alongside Wi-Fi / BLE / LAN listing every
  Sonos, Apple TV, HomePod, NAS, printer, AirDrop-capable Mac,
  HomeKit hub, Time Capsule, and other service-advertising peer —
  a much richer answer than ARP.
- **Anomaly watchdog mode.** Headless long-runs that push macOS
  Notification Centre alerts on high-confidence events (stir,
  loss burst, latency spike). Today's `diting stream --notify`
  is the seed; it grows configurable thresholds and per-event
  silence windows.
- **Per-device proximity compass.** When the BLE detail modal is
  open and a row is selected, render a "getting warmer / colder"
  signal-strength compass. Walk down an AirTag, Tile, or any
  advertising device by RSSI gradient.
- **Cellular state, when the Mac silicon exposes it.** A few Mac
  models have cellular modems; tethered iPhone state is broadly
  available via `pymobiledevice3`-style access. Surface signal
  bars + carrier + technology when present, gracefully omit
  otherwise.

### Mid-term

- **Investigate / scenario mode.** A guided entry — `diting
  troubleshoot zoom`, `diting find <name>` — that walks a
  non-power-user through the relevant panels with plain-English
  conclusions. Keeps the dashboard view for power users.
- **JSONL session replay.** `diting replay <file.jsonl>` feeds a
  prior log back through the TUI as if events were happening live,
  for after-the-fact incident review.
- **Trend graphs in the TUI.** RSSI / latency / channel-util over
  time, time-on-AP per BSSID. Builds on the existing JSONL log.
- **Auto-roam mode.** Gated, conservative. When a clearly-better
  same-SSID candidate persists ≥ N seconds, cycle the radio
  automatically — sticky-AP pain hands-free.
- **Pin-a-BSSID join.** Extend the `j` action on the Wi-Fi detail
  modal so the user can deliberately associate to one specific
  BSSID within an ESS (right now CoreWLAN's
  `associate(toNetwork:password:)` accepts the SSID and the OS
  picks the BSSID — fine for normal use, useless for "is it this
  specific radio that's flaky?"). Likely path: temporarily disable
  auto-join + 802.11r/k/v roaming for the duration of the
  association, or fall through to a per-BSSID `CWConfiguration`
  profile. Diagnostics value — lets a user A/B their two ceiling
  APs without walking between rooms.

### Further out

- **Room-presence sensing — flagship.** Move the RF environment
  monitor from "something changed" to "someone entered the
  living room". This is hard; Tier-3+ sensing requires CSI (not
  exposed by macOS) or a small auxiliary hardware probe. Long-
  term, hardware-assisted, deliberate. See
  [`docs/explainers/wifi-sensing.md`](docs/explainers/wifi-sensing.md)
  for the honest read on what's possible.
- **Dedicated edge-hardware companion.** Pair diting with a small
  always-on box (Raspberry Pi-class) for the two things a
  foreground macOS TUI inherently can't do: **24/7 persistent
  observation** (a stranger joined the LAN at 3 a.m. for five
  minutes — your Mac was asleep) and **Wi-Fi sensing on a
  stationary radio in monitor mode** (prerequisite for Tier-1+
  in the sensing explainer). Separate product / codebase
  (Linux + Python), macOS TUI stays the front end and subscribes
  to the edge box over Bonjour. See also
  [`docs/explainers/lan-inventory-arp.md`](docs/explainers/lan-inventory-arp.md)
  for the LAN-inventory half that doesn't need the edge box.
- ~~**Any-device LAN inventory (ARP-based).**~~ **[shipped]**
  A fourth panel listing every host on the local /24 — IP,
  MAC, vendor (via OUI), hostname (via reverse DNS), Bonjour
  cross-reference, first/last seen. Cycle to it via `n`
  (fourth view). Default /24 sweep; set
  `DITING_LAN_INVENTORY_WIDE=1` for a /22 sweep on wider home
  subnets. Design lives in
  [`docs/explainers/lan-inventory-arp.md`](docs/explainers/lan-inventory-arp.md).
- **Optional menu-bar app** for ambient awareness without keeping
  a terminal open.
- **Linux backend.** `nl80211` via `pyroute2` or shelling out to
  `iw scan`. Architecturally already abstracted behind
  `WiFiBackend`; just unimplemented.
- **Continuity / Personal Hotspot / iCloud Private Relay state.**
  Mac-specific integrations surfaced in Diagnostics where they're
  load-bearing for "why is my network weird right now".

## Acknowledgements

- **MAC-OUI vendor names** come from the [IEEE Registration Authority](https://standards.ieee.org/products-programs/regauth/) MA-L (24-bit) registry. The bundled snapshot in `src/diting/data/*_ouis.json` is refreshed per release via `uv run python scripts/refresh_ouis.py`, which pulls the canonical CSV from `https://standards-oui.ieee.org/oui/oui.csv`.

## License

MIT. See [`LICENSE`](LICENSE).
