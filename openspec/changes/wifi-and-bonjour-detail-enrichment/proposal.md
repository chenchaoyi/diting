## Why

The Wi-Fi and Bonjour detail modals today render every field of the
selected `ScanResult` / `BonjourDevice` — but they stop at "what
this single row says about itself" and never tell the user
**context** they could read elsewhere in the TUI: stability over
time, sibling radios of the same physical AP, the roam events the
session has already recorded, or whether the Bonjour host is the
same device they can see broadcasting BLE.

The information is already collected. The modals just don't
surface it. Result: a user pressing `i` to learn more about an AP
that's been flapping all morning sees `RSSI -55 dBm` (a single
number) instead of `RSSI -55 dBm · σ 4.2 dB over the last hour ·
3 roams to this BSSID since launch`. Same for Bonjour: a user
opening detail on the user's-own-Mac's AirPlay row sees one
service in isolation when their Mac is actually announcing three.

## What Changes

### Wi-Fi detail (`wifi-detail-modal`)

Four new sections (each omitted entirely when its data is absent
or trivially `None`, matching the existing
"sections-omitted-when-absent" pattern):

- **Signal history** — extends the existing Signal section. Adds
  an RSSI history sparkline (last ~hour, drawn from the per-BSSID
  ring that `EnvironmentMonitor` already maintains) and a `σ X dB
  · stable / active / noisy` label sourced from the same monitor's
  baseline state. Reuses the σ-band classification the diagnostics
  panel already uses.
- **Same physical AP** — when `NetworkInventory.resolve()` groups
  this BSSID with sibling radios under one AP (auto-clustered or
  via `aps.yaml`), list the siblings with their channel / band /
  RSSI. Mark which siblings the user could reach on the same
  scan tick.
- **Roam history** — filter the App's `EventRing` for `RoamEvent`s
  whose `to_bssid` or `from_bssid` matches this BSSID. Render as
  `<HH:MM:SS>  [same-AP|cross-AP]  from <BSSID> → to <BSSID>` and
  cap at the most recent 10. Empty section is omitted.
- **Recommendation** — when there is a clearly-better same-SSID
  candidate visible in the current scan (the same `clearly-better`
  rule the diagnostics panel's "Roam score" already uses, lifted
  into a shared helper), render `consider switching to <BSSID>
  on <band> · +N dB`. Otherwise omit.

### Bonjour detail (`bonjour-detail-modal`)

- **Other services on this host** — when the same `host` (or same
  shared address tuple) announces more than one service-instance,
  list the other categories with their `last_seen` age. The detail
  modal stays service-instance-keyed (so `up` / `down` still walks
  service-instances, not hosts) but the new section reframes the
  inspection from service-centric to device-centric.
- **Decoded TXT keys** — extends the existing TXT section. Common
  Apple keys (`model`, `osxvers`, `srcvers`, AirPlay `features`
  bitmask, RAOP `ft` bitmask, Companion-link `rpFl` flags) parse
  into named friendly fields rendered above the raw TXT table. The
  raw table remains for unknown keys.
- **Vendor resolution trace** — inline annotation on the existing
  Identity section's vendor row, naming which of the 5 chain
  steps (`txt-vendor`, `oui`, `hostname-pattern`,
  `service-type-hint`, `abstain`) resolved this vendor. Style
  matches the `(associated)` annotation the Wi-Fi modal uses.
- **Cross-surface correlation** — new section. When the announced
  IPv4 / IPv6 addresses match a peer the user has seen on the
  link (e.g. the local Mac's IP) OR when a TXT MAC field aligns
  with a BLE-side OUI lookup, surface the cross-surface link as
  `also on BLE as <name | category> · <RSSI>` or `local Mac
  (this host is you)`. **This is the heaviest piece** and may be
  deferred to a follow-up change if implementation cost runs
  long — see `design.md:D7`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `wifi-detail-modal`: the "modal SHALL render every `ScanResult`
  field, grouped into sections" requirement extends from 5
  sections to up to 9 (the 4 originals plus the 4 new optional
  ones).
- `bonjour-detail-modal`: the "modal SHALL render every
  `BonjourDevice` field, grouped into sections" requirement
  extends from 4 sections to up to 7 (3 new optional sections,
  plus an inline annotation on Identity).

## Impact

- `src/diting/tui.py`:
  - `WifiDetailScreen` — new `_section_signal_history`,
    `_section_siblings`, `_section_roam_history`,
    `_section_recommendation` methods. Reuse existing
    `_label` / `_heading` helpers.
  - `BonjourDetailScreen` — new `_section_other_services`,
    `_section_decoded_txt`, `_section_cross_surface`; extend
    `_section_identity` with the vendor-trace annotation.
  - `WifiDetailScreen.__init__` gains an `environment_monitor`
    arg (for σ + history) and an `event_ring` arg (for roam
    history); `BonjourDetailScreen.__init__` gains a
    `latest_mdns` snapshot ref and (for cross-surface) the
    `latest_ble` + `latest_connection` refs. App-side call
    sites that construct these modals update accordingly.
- `src/diting/mdns.py` and a new `txt_decoders.py` — small
  per-key TXT decoder registry that mirrors the BLE decoders'
  `@register` pattern. Decoders never raise; abstain returns
  `None`.
- `src/diting/roam.py` (or wherever the `clearly-better` rule
  lives today) — extract the rule into a pure function the
  modal can call. Single-source-of-truth for the diagnostics
  panel and the modal.
- New tests: `tests/test_tui_helpers.py` adds renderers for each
  new section against synthetic fixtures; `tests/test_tui_smoke.py`
  adds an assertion per modal that the new sections appear when
  expected and are omitted otherwise.
- No new external dependencies. No new helper-bundle schema
  changes — every signal already lives in the Python TUI.
- TESTING.md (EN + ZH) gains one row per new requirement.
