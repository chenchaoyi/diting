<sub>**English** · [中文](docs/zh/CHANGELOG.md)</sub>

# Changelog

All notable changes to wifiscope are recorded here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/), and
the project follows [Semantic Versioning](https://semver.org/) where
practical. The leading `v0.x` line is allowed to break minor
behaviours between releases.

## [Unreleased]

_No unreleased changes._

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
