## Why

Diting reveals what macOS hides at the **radio layer** (Wi-Fi RSSI, BLE
advertisements). It's silent about the **network layer** — yet most
modern devices announce themselves via mDNS / Bonjour all day long:
AppleTVs, HomePods, printers, NAS, Chromecasts, smart TVs, HomeKit
accessories, your colleague's `Macbook-Pro.local`. The local Mac
already receives every one of these announcements; the system Wi-Fi
menu doesn't tell the user about any of them.

That's an unclaimed surface that fits the project's "your Mac hears
more than it tells you" identity. Closing the radio-layer-only gap
turns diting from a Wi-Fi + BLE monitor into a full local-airspace
monitor (Wi-Fi + BLE + Bonjour) without changing the project's
brand, dependencies, or scope philosophy.

## What Changes

- **New TUI panel** listing mDNS / Bonjour-announced devices on the
  current link: vendor, name, service categories (AirPlay / IPP
  printing / SMB / Chromecast / etc.), and host (`*.local`).
  Mirrors `BLEPanel`'s row structure but simpler — no RSSI, no
  connected-vs-advertising split, no per-device history.
- **View toggle expanded from 2-way to 3-way.** The `n` key today
  cycles Wi-Fi ↔ BLE. After this change it cycles
  Wi-Fi → BLE → mDNS → Wi-Fi. The third slot reuses the same
  panel-swap mechanism the BLE view rides on.
- **Diagnostics panel gains an mDNS row** under the BLE view
  diagnostics: one-line summary `mDNS  N total · K services · top
  vendors …` analogous to `BLE  N total · K connectable · …`.
- **Listen-only discovery**. The new poller subscribes to the
  link-local multicast group (`224.0.0.251` / `ff02::fb`) via the
  Python `zeroconf` library. No active probes, no service-resolve
  storms, no cross-VLAN reach — diting only surfaces what's already
  broadcast.
- **Service category mapping** mirrors the existing BLE category
  catalogue: well-known service types (`_airplay._tcp`,
  `_ipp._tcp`, `_smb._tcp`, `_googlecast._tcp`, `_sonos._tcp`,
  `_hap._tcp`, `_workstation._tcp`, …) translate to friendly
  English / 中文 labels. Unknown service types pass through as raw
  underscore-form for honesty.
- **Vendor resolution** reuses the BLE OUI map (Bonjour TXT
  records expose MAC-like host identifiers) plus a name-pattern
  chain (`Apple-` / `HP-` / `Synology` / `Sonos` …) matching the
  existing BLE name-pattern table.
- **No new event types.** mDNS state is a snapshot view (like the
  BLE list), not an event stream. Devices appearing / disappearing
  don't fire JSONL events in v1 — that's a deliberate follow-up
  decision once we see how the data behaves.

## Capabilities

### New Capabilities

- `mdns-scanning`: passive Bonjour / mDNS device enumeration on
  the local link. Owns: subscription lifecycle, service-type →
  category mapping, vendor resolution chain, snapshot model,
  expiry TTL, the `BonjourDevice` data shape, the `BonjourPanel`
  rendering contract.

### Modified Capabilities

- `tui-shell`: the `n` toggle's contract changes from a 2-way swap
  to a 3-way cycle. One MODIFIED Requirement on the existing
  view-toggle Requirement.

## Impact

- **Files**:
  - `src/diting/mdns.py` (new — `BonjourPoller`, `BonjourDevice`,
    service-category map, name-pattern vendor chain).
  - `src/diting/tui.py` — new `BonjourPanel`, view-mode triple
    state, helper for the diagnostics row, footer label changes.
  - `src/diting/data/bonjour_services.json` (new — well-known
    service-type → category mappings).
  - `src/diting/i18n.py` — EN / ZH for the new panel labels and
    diagnostic strings.
  - `tests/test_mdns.py` (new).
  - `tests/test_tui_smoke.py` (extend for the 3-way toggle).
  - `tests/TESTING.md` + `docs/zh/TESTING.md` (new rows under the
    new `mdns-scanning` capability + updated `tui-shell` row).
  - `CHANGELOG.md` + `docs/zh/CHANGELOG.md` `[Unreleased] → ###
    Added`.
  - `pyproject.toml` — new dependency `zeroconf >= 0.130` (pure
    Python, well-maintained, no native code).
- **Tests**: unit tests for the parser / category map / vendor
  chain. One TUI smoke test for the 3-way toggle.
- **CI gates**: pytest, snapshot regression (16/16 baseline
  unaffected — synthetic scenarios don't exercise mDNS), specs
  strict.
- **External**: one new third-party dependency (`zeroconf`).
  No version bump — accumulates under `[Unreleased]` until the
  maintainer cuts the next release.
