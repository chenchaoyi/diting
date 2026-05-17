## Why

The 2026-05-17 `/tui-audit` against the user's real environment
(`/private/tmp/wfs-tui-audit-20260517-140538/`) produced six
findings: three actionable bugs, three discoverable improvements.
This change rolls the actionable three + the first two improvements
into a single polish PR.

The three bugs all let through visible state the user wouldn't
expect:

1. **`live_main.svg`** showed the same hidden BSSID
   `40:fe:95:89:c7:e5` four times in a row, all identical RSSI /
   channel / SSID. CoreWLAN's `scanForNetworksWithName_error_`
   intermittently returns multiple scan-dwell instances of the
   same BSSID; we never deduped, so the "Nearby BSSIDs (24)" count
   and the table both inflate.
2. **`live_ble_detail.svg`** rendered the empty Services section as
   `(none advertised)—`. The em-dash is an accidental "no value"
   suffix from `_label(name, None)` — the placeholder string was
   sent in via the wrong helper.
3. **The Tx Rate field on the Connection panel flickers to `n/a`**
   between captures when `transmitRate()` returns 0 for a single
   poll. The radio is idle, not absent — we should hold the last
   non-zero rate with an `(idle)` annotation instead.

The two improvements address discoverability of the mDNS view:

4. The Bonjour panel renders one row per service, so a single
   physical HomePod with four advertised services takes four rows
   and the "Visible Bonjour 21 total" count overstates how many
   physical devices are around.
5. The mDNS diagnostics' unknown-vendor bucket reads as `? 5`,
   which scans as a typo. Other panels use `(unknown)` for the
   same case.

## What Changes

### `wifi-scanning` — dedup BSSID rows + Tx Rate idle cache
- **ADDED:** the scan path SHALL deduplicate by lowercase BSSID
  before returning. When CoreWLAN reports the same BSSID more
  than once in a single scan, the helper / backend SHALL keep
  the row with the strongest RSSI and drop the rest. First-seen
  order across distinct BSSIDs is preserved.
- **MODIFIED:** the `MacOSWiFiBackend` SHALL cache the last
  non-zero `tx_rate_mbps` per associated interface and surface
  it on the next poll if `transmitRate()` reports 0 (radio
  idle). The cached value SHALL be marked with the
  `tx_rate_idle: bool` flag on the `Connection` snapshot so the
  TUI can render `144.0 Mbps (idle)` instead of `n/a`. The
  cache SHALL be cleared when the associated SSID / BSSID
  changes (so a stale rate from a previous AP never bleeds
  across a roam).

### `ble-detail-modal` — services placeholder rendering
- **MODIFIED:** the Services section's empty-state SHALL render
  as a standalone "(none advertised)" dim-italic line — NOT as
  a label-with-empty-value (which currently appends an em-dash
  suffix). The same convention SHALL apply to any other
  section that prints "(none …)" placeholders when no rows
  exist (extra UUID lists, other services on the same host).

### `mdns-scanning` — by-host sort mode + unknown-vendor label
- **ADDED:** the `BonjourPanel` SHALL accept a `by-host` sort
  mode in addition to the existing default. The `by-host` mode
  groups rows by `host` (Bonjour's stable identifier per
  device), prints one row per host with the host's vendor / name
  / age, and folds the per-host services list into the services
  column as a comma-joined string. The default `service` mode
  is unchanged.
- **MODIFIED:** the mDNS diagnostics "Top vendors" line SHALL
  render the unknown-vendor bucket as `(unknown) N`, matching
  the column placeholder convention. The literal `?` glyph
  SHALL NOT appear for this bucket.

## Out of Scope

- Iteration 3's deeper question (when *is* the radio idle vs
  actually-zero rate) — we don't try to distinguish those,
  we just preserve the last non-zero rate and let it age
  naturally on a real change.
- A `g`-key shortcut to toggle by-host vs by-service — keeping
  this on the existing `s` cycle for now; if the new option
  feels lost on `s` we can revisit.
- The remaining audit findings (iterations 5+6) are noted in
  the findings file; no behaviour change.
