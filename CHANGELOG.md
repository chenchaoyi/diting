# Changelog

All notable changes to wifiscope are recorded here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/), and
the project follows [Semantic Versioning](https://semver.org/) where
practical. The leading `v0.x` line is allowed to break minor
behaviours between releases.

## [Unreleased]

_No unreleased changes._

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
