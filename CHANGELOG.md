<sub>**English** · [中文](docs/zh/CHANGELOG.md)</sub>

# Changelog

All notable changes to wifiscope are recorded here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/), and
the project follows [Semantic Versioning](https://semver.org/) where
practical. The leading `v0.x` line is allowed to break minor
behaviours between releases.

## [Unreleased]

### Added
- **Spec-driven development workflow** (`openspec/`). Every
  behaviour-affecting capability is now pinned by a canonical spec
  under `openspec/specs/<name>/spec.md`; new work goes through
  `openspec/changes/<name>/` proposals, archived after merge.
  Workflow rules: `docs/workflow.md` (EN) / `docs/zh/workflow.md`
  (ZH). 15 capabilities backfilled in this release.
- **CI hardened** — `.github/workflows/test.yml` now runs three
  jobs: pytest matrix, TUI snapshot regression (uploads
  `snapshot-output/` on failure), and `openspec validate --strict`.
  PR template at `.github/pull_request_template.md` enforces the
  branch / spec / test / docs / archive checklist.
- **`/opsx:test` slash command** delegates the full self-test
  (pytest + regression + spec validation) to a subagent so the
  parent context stays clean.
- **Per-protocol BLE decoders** under `src/wifiscope/decoders/`:
  iBeacon, Eddystone (UID/URL/TLM), Apple Continuity (Nearby Info
  / Find My / Handoff with multi-subtype walking), Microsoft CDP
  + Swift Pair, RuuviTag Format 5. Plug-in framework via
  `@register`; output keys protocol-namespaced.
- **BLE detail modal** (`i` / `enter`) with keyboard up/down +
  mouse click-to-inspect, RSSI history sparkline (per-device
  `BLEHistory` ring buffer), distance estimate, raw-byte hex
  dumps for manufacturer / service data, and a "Decoded payload"
  section.
- **Helper schema-4 raw passthrough** — `service_data`,
  `tx_power_dbm`, `solicited_service_uuids`,
  `overflow_service_uuids`, and `manufacturer_hex` now reach
  `BLEDevice` so downstream decoders can read CoreBluetooth's
  full advertisement view without re-implementing the bridge.
- **31 Apple BT-MAC OUIs** added to `wifi_ouis.json` so connected
  Magic Keyboard / Trackpad rows resolve to "Apple, Inc." instead
  of `(unknown)`.
- **Vendor lookup chain** now consults `service_data` keys (not
  just `service_uuids`), recovering Xiaomi MiBeacon / Google Fast
  Pair / Microsoft Find My devices that previously dead-ended at
  `(unknown)`. Real-environment coverage improved from 64 % → 99.5 %.
- **`(anonymous)` vs `(unknown)` distinction** — silent broadcasts
  render as `(anonymous)` (physical limit); lookup-chain misses
  with data render as `(unknown)` (actionable decoder gap).

### Changed
- **STIR legend** now reads `current σ > baseline ×2.5 (≥3 dB)` —
  pulled from `DEFAULT_SPIKE_RATIO` / `DEFAULT_SPIKE_MIN_DB` so it
  cannot drift from the firing logic. Previously read `×3`,
  conflating the ratio with the absolute floor.
- **BSSID singular / plural grammar** — `1 wide 2.4 GHz BSSID` vs
  `27 wide 2.4 GHz BSSIDs` now both render correctly in EN.
- **BLE vendor column** truncation signalled with `…` and 16
  consumer-brand aliases (`Hewlett Packard En` → `HP Enterprise`).
- **ZH translation polish** — 16 awkward / ambiguous strings
  rewritten: `σ 是 RSSI 抖动` → `σ 是 RSSI 标准差` (technical
  accuracy), `宽带 BSSID` → `宽信道 BSSID`, `最近` 同屏歧义拆为
  `最强` / `最近见到`, `扫描频率 7s` → `扫描间隔 7s`, etc.
- **`scripts/tui_snapshot.py` explore mode** respects
  `WIFISCOPE_LANG=zh` so audits can run in the ZH UI.

### Fixed
- BLE row navigation keys (`↑` / `↓` / `enter`) win over
  `VerticalScroll`'s built-in scroll handlers via `priority=True`.
  Mouse click on a BLE row also selects + opens detail.
- Diagnostics panel rendering stability in regression — seed helper
  pins `_link_diagnostic_tuple` / `_environment_diagnostic_tuple`
  on the App so a stray refresh cannot wipe seeded Link /
  Environment rows.
- **Help-modal ZH translation for `force re-roam`** — the catalog key
  in `i18n.py` was `cycle WiFi off/on` but the call site at
  `tui.py:426` used `cycle Wi-Fi off/on`, so ZH lookup silently
  fell back to English. Catalog key now matches the call site.

### Docs
- **Spec coverage matrix** in `tests/TESTING.md` (and ZH mirror) —
  every requirement under `openspec/specs/<capability>/spec.md`
  now points to a real test, a `(review-enforced)` convention,
  a `(regression-only)` snapshot scenario, or an honest `(gap)`.
  Coverage holes (cooldown / rearm logic, EventRing length cap,
  footer grouping, subtitle, fit_cells, network-change probe
  reset, atexit writer close, several CLI dispatch paths) are
  now visible instead of implicit.
- **`Wi-Fi` / `WiFi` normalisation** across user-visible prose
  (README, help modal, force-reroam toast). Internal class
  names (`WiFiBackend`, `WiFiPoller`) intentionally untouched.

## [0.7.0] — 2026-05-07

The "is the link actually working + what's stirring around me"
release. RSSI alone never tells you whether your gateway is queueing
packets or whether someone just walked past the laptop; v0.7.0 adds
two continuous probes that do.

### Added
- **Continuous latency / loss probe** (1 Hz ICMP via `/sbin/ping`)
  against the user's gateway and an auto-detected WAN anchor — the
  system's currently-configured DNS server, read straight from
  `SCDynamicStoreCopyValue("State:/Network/Global/DNS")` (with a
  `scutil --dns` subprocess fallback). Resolution order: the
  `WIFISCOPE_LATENCY_WAN_TARGET` env var beats auto-detect; when
  the only configured DNS is the gateway itself, the WAN probe is
  skipped and the diagnostic line reads `WAN n/a (DNS == gateway)`
  so the user knows why. DNS detection re-runs every 60 s so a
  network switch updates the anchor without restarting wifiscope.
  Pure ICMP — no raw socket, no sudo. The Diagnostics panel gains a
  `Link  gw 12 ms · 0% loss · WAN 18 ms · 0% loss · jitter 3 ms`
  row; loss / very-high-rtt / unreachable states render with a ⚠
  glyph and red styling.
- **Beacon IE depth in the helper.** `runScanAndDumpJSON` now walks
  CoreWLAN's `informationElementData` for each `CWNetwork` and
  decodes BSS Load (Element ID 11 → `bss_load_pct` +
  `bss_station_count`), Mobility Domain (54 → `supports_802_11r`),
  RM Enabled Capabilities (70 → `supports_802_11k`), and Extended
  Capabilities bit 19 (127 → `supports_802_11v`). Each field is
  emitted only when the IE is present, so v2 / partial-IE consumers
  remain forward-compatible. Schema number stays 3; the new fields
  are additive.
- **Environment monitor.** A new module computes per-BSSID rolling
  RSSI σ, fires `RFStirEvent` when both spec thresholds are met
  (current 5 s σ > 2.5 × trailing 5-min median σ AND > 3 dB
  absolute floor), and surfaces a `stable` / `active` / `quiet`
  qualifier on a new `Environment  σ 1.4 dB / 5s` Diagnostics row.
  Per-AP fusion modes auto-classify by median RSSI: `co_located`
  (>= -65 dBm) does redundancy fusion (a spike on >= 2 co-located
  APs counts as high-confidence); `spatial_channel` (-65 .. -85)
  fires events labelled with the AP's inventory name; `ignored`
  (< -85) is dropped as too noisy. NEVER claimed as people-counting
  or motion detection — the wording on every surface is "something
  changed".
- **Unified Events panel + modal `m` browser.** The v0.6.0 Roam
  log panel becomes the Events panel: same widget slot, same
  height, but accepts roam / rf_stir / latency_spike / loss_burst /
  link_state events through one `append_event` entry point. Each
  row carries a typed prefix (`[ROAM]` / `[STIR]` / `[LATENCY]` /
  `[LOSS]` / `[LINK]`). The new `m` binding opens an
  `EventsScreen` modal — full-screen browser of the last 100
  events, filterable via 1/2/3/4/0 subkeys, with a per-AP σ
  baseline mini-table and a sparkline of σ over the last hour at
  the bottom.
- **`wifiscope monitor` and `wifiscope calibrate` subcommands.**
  `monitor` is a headless long-run that streams JSONL events to
  stdout (or `--out path.jsonl`), with `--notify` raising macOS
  Notification Centre alerts on high-confidence events. Designed
  for Home Assistant / log-pipeline integration. `calibrate`
  records a configurable duration (default 5 min) of "empty room"
  RSSI samples per visible BSSID and writes
  `./wifiscope-baseline.json`; the Environment monitor reads that
  file at startup and switches the diagnostic line label to
  `quiet` / `active` from the default `stable` / `active`.
- **`WIFISCOPE_LATENCY_WAN_TARGET` env var** to pin the WAN probe
  IP for one-off invocations or networks where DNS auto-detection
  picks the wrong anchor.
- **`make monitor` Makefile target** (alias for `uv run wifiscope
  monitor`) for discoverability.
- **EventsScreen preview SVGs** (English + Chinese) so the README
  shows the modal browser. The existing 4 SVGs (Wi-Fi + BLE × EN +
  ZH) remain; `make preview` is now 6.
- **40+ new tests across 4 modules** covering ping output parsing,
  spike / loss-burst detectors, all 7 DNS auto-detection shapes
  the spec calls out, refresh cadence, env-var override, the
  scutil fallback parser, σ → event firing, mode classification,
  redundancy fusion, calibration round-trip, every event-format
  line, the Diagnostics body containing both new rows, and the
  modal open / close flow.

### Changed
- Diagnostics panel now has 7 lines (was 5): adds `Link` and
  `Environment` after the existing visible-networks / warnings /
  recommendations / health / score block.
- The "Roam log" panel is now "Events" — same slot, same height,
  same time-ordered ring, but it accepts every v0.7.0 event type.
- ScanResult dataclass gains `bss_load_pct`, `bss_station_count`,
  `supports_802_11r`, `supports_802_11k`, `supports_802_11v`. Each
  defaults to None so v2 helpers / pre-v0.7.0 cached scans remain
  parseable.

### Known limitations
- The adaptive baseline drifts overnight — leaving the office at
  6 PM and returning at 8 AM will briefly fire false-positive
  events the next morning. `wifiscope calibrate` corrects this for
  users who care.
- `/sbin/ping` reports millisecond precision only; sub-millisecond
  wired LAN reads as 0 or 1 ms.
- Loss-burst detection lags up to 5 s (3-of-5 rule).
- Environment events are correlation, not causation — a neighbour's
  AP rebooting can fire a stir event you did not cause.
- DNS auto-detection ignores DoH / DoT (Firefox encrypted DNS,
  Tailscale MagicDNS); we ping whatever the OS resolver believes
  its upstream is.

## [0.6.0] — 2026-05-07

The "what kind of device + what's actually connected" release. Two
questions the v0.5.0 BLE panel could not answer cleanly: *what is
this thing labelled "Apple, Inc. (anonymous) Find My"?* and *where
are the AirPods I'm listening to right now in this list?* — both
have answers now.

### Added
- **Tier-1 deep identification of public BLE advertisement formats.**
  The Swift helper's new `BLEAdParser` recognises iBeacon (Apple
  manufacturer type `0x02`), AirTag / Find My target (Apple type
  `0x12` ± Find My service `FD5A`), Eddystone in all four frame
  variants (UID / URL / TLM / EID via service `FEAA`), Tile (`FEED` /
  `FEEC`), Samsung SmartTag (Samsung company ID + `FD5A`,
  disambiguated from Apple Find My on the same UUID), and Microsoft
  Swift Pair (Microsoft company ID + leading `0x03`). Apple Nearby
  Info type `0x10` is decoded for its unencrypted device-class
  nibble: `iPhone`, `iPad`, `Mac`, `Apple TV`, `HomePod`, `Apple
  Watch`. Each row's "services" column now leads with this label so
  the panel reads `AirTag · Find My` instead of just `Find My`. Out
  of scope by design: per-model identification (iPhone 14 vs 15
  needs proprietary GATT) and decryption of Continuity payloads
  (lock state, Music-playing — encrypted, per-device-key).
- **Currently-connected peripherals in their own section.** The
  helper periodically calls `retrieveConnectedPeripherals` over a
  fixed union of common service UUIDs (Audio, HID, Heart Rate /
  Battery, Find My, Eddystone, Tile) and emits one
  `{"connected": true, ...}` JSON line per returned peripheral plus
  a `connected_snapshot` sentinel that lets the Python side prune
  rows when a device disappears. The BLE panel renders these as a
  separate `── Connected (N) ──` block above the existing
  `── Advertising (N) ──` block, with `—` in the RSSI column (we
  deliberately do not call `readRSSI()` against an active link —
  too invasive). Connected entries sort alphabetically by name and
  skip the fuzzy merger.
- **`Connected` diagnostic row** appears below the Categories line
  whenever at least one peripheral is connected, with a per-category
  breakdown (`Connected  3 peripherals · 2 Audio · 1 HID`). The
  Categories line itself folds in deep-ID types so iBeacons,
  AirTags, and labelled iPhones surface alongside Audio / HID /
  Heart Rate counts.
- **Schema-3 helper output.** Optional `type` and `device_class`
  fields on each advertisement JSON line; a separate `connected:
  true` channel for connected-peripheral rows. The Python TUI
  tolerates schema-2 helpers (no deep-ID, no connected list) so a
  freshly-upgraded TUI keeps working until the user rebuilds the
  helper bundle.
- **20 new BLE unit tests** in `tests/test_ble.py` plus 7 new TUI
  helper tests covering the deep-ID detection algorithm
  (parameterised across all six Apple device classes), the
  connected-dict routing, the `connected_snapshot` sentinel
  pruning, schema-2 back-compat, mixed-stream routing, and the
  `BLEScanUpdate.connected` propagation through the poller. Plus
  a smoke test that mounts the App, seeds both buffers, presses
  `n`, and asserts both sections render.
- **i18n catalog entries** for the section headers (`已连接` /
  `正在广播`), the peripherals-count phrasing, and the new
  `Find My target` label. Brand-name types (iBeacon, AirTag, Tile,
  SmartTag, Swift Pair, Eddystone-{UID,URL,TLM,EID}) and Apple's
  device-class names stay English in both locales by design — they
  are proper nouns.

### Changed
- BLE preview SVGs (English + Chinese) now show both the
  `Connected (2)` section (AirPods Pro + Magic Keyboard) and the
  `Advertising (8)` section with at least one of each Tier-1
  category labelled (iPhone / AirTag / iBeacon / Eddystone-URL /
  Tile / Mi Band 7 / etc.) so the README hero reflects the v0.6.0
  shape.
- `pyproject.toml` version bumped to 0.6.0.

### Known limitations
- **Apple Continuity encrypted bits stay opaque.** Lock state,
  Music-playing flag, AirDrop session info — all behind a per-device
  key Apple does not publish. We surface device_class via type
  `0x10` only.
- **Connected peripherals have no RSSI / vendor metadata.**
  `retrieveConnectedPeripherals` returns much less than a fresh
  advertisement; the panel renders `—` for the missing signal column
  and leaves the vendor blank rather than fabricating one.
- **Service-UUID enumeration in `retrieveConnectedPeripherals` is
  required.** The hard-coded service list will miss obscure
  peripherals (Bluetooth Mesh nodes, exotic Health Devices). That
  is acceptable for v0.6.0.
- **MAC randomisation persists.** Even with deeper labels, a phone
  seen across a 30-minute window may rotate identifiers several
  times. The fuzzy merger now has more signals to work with (`type`,
  `device_class`) but still cannot guarantee 1:1.

## [0.5.0] — 2026-05-06

The "what electronic devices are around me right now?" release.

### Added
- **Nearby BLE devices view**, toggled with the new `n` binding.
  Replaces the Nearby BSSIDs panel in the same vertical slot
  (Diagnostics, Connection, and Roam log are unchanged) with a
  scrollable list of every BLE peripheral advertising in range —
  AirPods, Apple Watches, BLE keyboards, Find My beacons, smart-home
  gadgets, iBeacons, etc. Both pollers run in parallel from app
  mount, so toggling between the two views is instant and never
  shows a stale "scanning…" state.
- **Bluetooth permission via the existing helper bundle.** The Swift
  sidecar at `helper/wifiscope-helper.app` gains a second TCC
  entitlement (`NSBluetoothAlwaysUsageDescription`) and a new
  `ble-scan` subcommand that streams advertisement events as JSON
  Lines. The helper's GUI mode now requests both Location Services
  and Bluetooth on launch — one Allow click covers both. No new
  Python deps; the existing "permission isolation" architecture
  stays intact.
- **Bundled Bluetooth SIG vendor snapshot** at
  `src/wifiscope/data/bluetooth_vendors.json` (4021 entries) plus a
  new `make update-vendors` target that fetches the upstream YAML,
  records the source commit hash, and rewrites the file. No network
  calls at runtime.
- **UUID-rotation fuzzy merger.** Modern BLE devices rotate their
  identifier for privacy; the merger folds entries sharing
  `(vendor_id, name)` with RSSI within ±10 dB into a single row and
  shows a `(merged N)` badge so the merge is visible, never
  silently. Anonymous beacons (no vendor, no name) are never merged
  to avoid conflating unrelated devices.
- **BLE preview SVGs** at `docs/preview-ble.svg` and
  `docs/preview-ble.zh.svg`, alongside the existing Wi-Fi preview.
  README hero block now shows both with a small caption indicating
  which view each represents.
- **8 new BLE unit tests** in `tests/test_ble.py` covering JSONL
  parsing, vendor lookup, service category inference (Heart Rate /
  HID / Audio / Find My), TTL expiry, fuzzy merging, permission
  denied handling, subprocess crash resilience, and malformed JSON
  recovery.
- **i18n catalog entries** for every new user-visible string —
  panel title, view subtitle, service categories (`音频` / `键盘` /
  `心率` / `查找网络`; iBeacon stays English per spec), placeholder
  messages, and the merged badge.

### Changed
- `make preview` now regenerates four SVGs instead of two; new
  `preview-ble-en` and `preview-ble-zh` sub-targets handle the BLE
  view individually. Wi-Fi targets unchanged.
- Help modal documents the new `n` binding.
- Header subtitle gains a `view: wifi` / `view: ble` segment so the
  active view is always visible.

### Known limitations
- macOS Bluetooth Classic / BR-EDR is out of scope; this release is
  BLE only.
- No Linux / Windows BLE backend yet.
- No GATT connect, pairing, or per-device deep-dive modal.
- Apple Continuity / Handoff payloads are shown as a generic Apple
  device — we do not reverse-engineer the proprietary format.

## [0.4.0] — 2026-05-06

The "speak Chinese too" release.

### Added
- **Simplified Chinese UI**. Every panel title, footer hint, status
  message, diagnostics line, roam-log tag, Help modal section, and
  Wi-Fi Basics term has a Chinese translation that reads naturally
  rather than as a word-for-word port. Industry acronyms (SSID /
  BSSID / RSSI / dBm / SNR / WPA2 / OPEN / ENT / MCS / NSS / Tx / Max)
  stay in English in both languages by design.
- **Static-at-launch language switch.** New `--lang en|zh` CLI flag
  and `WIFISCOPE_LANG` environment variable; with neither, wifiscope
  autodetects from `LC_ALL` / `LC_MESSAGES` / `LANG` (`zh_*` →
  Chinese, anything else → English).
- **CJK-aware column padding.** New `wifiscope.i18n.pad_cells` and
  `fit_cells` use `rich.cells.cell_len`, so a Chinese inventory name
  like `1F-书房` or a translated table header like `频段` consumes its
  two cells per glyph instead of one byte per char. The Connection
  panel labels and the Nearby BSSIDs table header / cells are routed
  through these helpers.
- **Chinese mirror of every doc** under `docs/zh/`: `README.md`,
  `CHANGELOG.md`, `TESTING.md`, `HELPER.md`. Each English original
  carries a `English · 中文` switcher at the top, and each Chinese
  doc links back.
- **Chinese preview SVG** at `docs/preview.zh.svg`, generated from
  the same fake backend as the English `preview.svg`. Run
  `WIFISCOPE_LANG=zh uv run python docs/_capture_preview.py` to
  refresh.

### Changed
- **AP-aliases default path** moves from
  `~/.config/wifiscope/aps.yaml` to `./aps.yaml` (resolved against
  the current working directory). This is a breaking change for
  anyone who already populated the XDG path; `WIFISCOPE_INVENTORY`
  still overrides, so `export WIFISCOPE_INVENTORY=~/.config/wifiscope/aps.yaml`
  preserves the old behaviour. Rationale: most uses run wifiscope
  from the cloned repo, so a CWD-local file lives next to
  `aps.example.yaml` and skips the `mkdir -p ~/.config/wifiscope`
  ceremony. Added `aps.yaml` to `.gitignore` so users do not
  accidentally commit their network topology.
- README's AP-config section reframed as **AP aliases (optional)**
  with a clearer explanation of where mgmt MACs come from (router /
  controller management UI), and an explicit "skip this on
  enterprise networks" note.
- Help modal "Tunables" section now lists `WIFISCOPE_LANG=en|zh` next
  to the existing scan / inventory / helper overrides.
- README "Configuration" table gains a `WIFISCOPE_LANG` row alongside
  the existing env vars.

### Added
- **Makefile** at the repo root with `test`, `test-all`, `preview`,
  `preview-en`, `preview-zh`, `helper`, and `help` targets so the
  bilingual workflow ("UI change → regenerate both preview SVGs")
  is one command instead of remembering an env var.
- README "Maintaining bilingual UI / docs" subsection codifying the
  three sync rules between English and Chinese surfaces (strings,
  docs, preview SVGs).

## [0.3.0] — 2026-05-06

The "make dense Wi-Fi scans understandable" release.

### Added
- **Diagnostics panel** with visible BSSID totals, band distribution,
  hidden-in-this-scan count, open/no-password BSSID count, wide
  2.4 GHz channel warnings, country-code spread, current-channel
  peer count, least-crowded channel hints, current-link health, and
  a simple roam score.
- **Same-SSID roam candidate scoring**. wifiscope now compares the
  current BSSID with clearly better same-name BSSIDs and explains
  when pressing `c` may help the Mac re-roam.
- **Wi-Fi Basics modal** on `b`, explaining SSID, BSSID, AP host,
  RSSI, noise/SNR, band, channel, width, security, roam, and roam
  score in plain language.
- **Scrollable Nearby BSSIDs panel**, so dense office scans can be
  inspected beyond the visible terminal height.
- **Security badges** in scan rows, including an obvious `OPEN`
  marker for no-password BSSIDs.
- **Security decoding** from the macOS helper scan payload.

### Changed
- Nearby scan terminology now uses **BSSID** instead of AP/network
  where the underlying row is one radio identity.
- The scan-list `ch` column is now `channel`, with wider spacing
  around `band`.
- Diagnostics wording distinguishes **hidden in this scan** from
  visible BSSID totals, since hidden SSID beacons can vary between
  CoreWLAN scan snapshots.
- Least-crowded channel hints say `(no AP heard)` when the suggested
  channel was absent from the current scan sample.

## [0.2.0] — 2026-05-06

The "macOS scan list is no longer redacted, and the tool grew up"
release.

### Added
- **Swift helper sidecar** at `helper/`. Tiny Cocoa `.app` whose only
  job is to own macOS Location Services permission so the Python
  TUI can read unredacted SSIDs and BSSIDs for every BSSID in the
  scan list. wifiscope auto-builds and `open`s it on first launch;
  the bundle window auto-quits 1.5 s after the user clicks Allow.
  Subsequent runs go straight to the TUI.
- **`c` binding** to force re-roam by cycling the WiFi radio off
  then on. Cleaner than `disassociate()` (which was unreliable on
  802.1X enterprise networks): the off/on path goes through full
  auto-join with Keychain credentials.
- **`s` binding** to cycle the Nearby APs sort between by-AP
  (default; groups every BSSID under its physical AP with a per-
  group summary line) and by-signal (flat RSSI-sorted).
- **`h` binding** opens a HelpScreen modal that documents the tool,
  the panels, every binding, the inventory schema, and the helper.
- **AP inventory model** refactored to AP-level entries: `aps` list
  with `name` + `mgmt_mac`, plus an optional `radio_overrides` map.
  Resolution is two rules: first-five-octet match with a last-byte
  proximity window (catches H3C controllers that allocate adjacent
  APs out of one OUI block), then octets-2..5 match (covers vendor
  alternate-OUI allocations like H3C `40:` vs `44:`).
- **Auto-discovered cluster labels** (`?XX:YY:ZZ`) for unaliased
  BSSIDs — every radio of one chip collapses under one label even
  without inventory configuration.
- **Connection panel** gained MCS index, NSS, `This Mac` (interface
  MAC), country code, IP / Router, and a Tx vs Max footnote.
- **Per-row signal bar** in the Nearby APs panel matching the
  Connection panel's colour bands (green / yellow / red).
- **Synthetic current-AP row** in the scan list when CoreWLAN's
  scan omits the associated AP, so the user always sees their own
  row at the top with star + inverted background.
- **Hidden network labelling**: empty-SSID beacons render as
  `(hidden)` rather than `(no SSID)`.
- **`WIFISCOPE_SCAN_INTERVAL` env var** to override the 7 s default
  scan cadence (3 s minimum).
- **Test suite under `tests/`** with 83 cases (58 functions; some
  parametrised) covering inventory resolution, helper JSON parsing,
  TUI merge / group helpers, and a headless `run_test` smoke pass
  over every binding. [`tests/TESTING.md`](tests/TESTING.md) is the
  canonical test plan — every automated case has a row in that
  document and changes start there.
- **GitHub Actions CI** running pytest on macOS-latest against
  Python 3.11 / 3.12 / 3.13 for every push and pull request to
  `main`.
- **`CHANGELOG.md`** (this file) and CI / release / license badges
  in the README.
- **User-first README**: hero screenshot, problem statement up
  front, technical design notes deferred. Logo + a deterministic
  TUI preview SVG live under `docs/`.

### Changed
- Scan-list `AP` column renamed to `AP host`. The original "AP" was
  ambiguous with the column to its right (`BSSID`, which also
  identifies an AP); the new label clearly identifies the physical
  device hosting the BSSID.
- Default sort mode is now by-AP. The grouped view is more readable
  on dense corporate scans.
- Scan interval default raised to 7 s. CoreWLAN's scan throttle is
  empirically ~5 s; running below it produces alternating empty
  scans (silent because of the panel's last-non-empty cache, but
  pure waste).
- Channel resolution now reads SCDynamicStore's top-level CHANNEL
  field (the OS's view of the radio's current associated channel),
  falling back to `CachedScanRecord.CHANNEL` only if absent. This
  fixes a mismatch where wifiscope reported the radio's mid-scan
  tune target while macOS's native WiFi panel showed the AP's
  actual operating channel.

### Fixed
- Three APs sharing a `40:fe:95:8a:3c:..` prefix used to all map to
  the first inventory entry. Last-byte proximity now disambiguates.
- `(redacted)` rows are now visually distinct from `(hidden)` and
  from real APs with empty SSIDs.
- `Tx` vs `Max` divergence in the Connection panel is documented in
  a footnote rather than hidden.
- Footer binding hints are no longer stolen by an over-eager
  attribution bar.

### Removed
- The `aliases.yaml` flat BSSID-to-name format. Replaced by the
  AP-level inventory described above; migration is documented in
  the README and on the help screen.

## [0.1.0] — 2026-05-05

First release. macOS-only TUI with three panels (Connection, Nearby
APs, Roam log), AP alias support via a flat `aliases.yaml`, and a
SCDynamicStore tunnel that surfaces the *current* connection's SSID
and BSSID even when CoreWLAN is fully redacted by Location Services
denial. Scan-list identity remains redacted in this release; v0.2's
helper bundle is the proper fix.

See the [v0.1.0 release notes](https://github.com/chenchaoyi/wifiscope/releases/tag/v0.1.0)
for the full changelog of the eight-step initial implementation.
