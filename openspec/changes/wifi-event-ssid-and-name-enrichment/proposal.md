## Why

User report (2026-05-18): the Events panel renders Wi-Fi-side
events as raw BSSIDs only.

```
09:49:30  [漫游]  1c:28:af:5d:2b:b4 -> 1c:28:af:5e:9d:b4   [跨 AP 漫游]
09:49:56  [扰动]  ?af:5e:9d 处 RF 扰动   σ 4.8 dB  ·  中
09:50:04  [扰动]  ?af:5e:9d 处 RF 扰动   σ 4.9 dB  ·  中
```

For a user with multiple SSIDs on the same physical link (home
guest + private, office corp + IoT, café open + 5 GHz) the BSSIDs
alone don't say which network experienced the roam / disturbance.
The AP-name half is already handled by `format_bssid` when
`aps.yaml` has the BSSID mapped — but the SSID is never surfaced.

The fix is small and additive: carry the associated SSID at the
moment the event fires (the poller / environment monitor already
have it on the `Connection` they observed) and render it on the
event line. AP-name rendering keeps its existing inventory-lookup
behaviour; users with sparse `aps.yaml` files still see the
cluster-label or raw BSSID, but at minimum they now know which
SSID was affected.

## What Changes

### `events` — RoamEvent + RFStirEvent carry SSID
- **MODIFIED:** `RoamEvent` SHALL carry `previous_ssid: str | None`
  and `new_ssid: str | None`. Both are the SSID associated with
  the previous / new BSSID at the moment the roam was observed,
  taken from the `Connection.ssid` field. Optional with
  default-None for backwards compat with any code path that
  constructs the event without going through the poller.
- **MODIFIED:** `RFStirEvent` SHALL carry `ssid: str | None`. It
  is the SSID associated with the BSSID at the moment the σ
  threshold was crossed (the environment monitor reads it from
  the current `Connection`). Optional with default-None for the
  same reason.
- **MODIFIED:** `event_to_jsonl` SHALL serialise the new fields
  under English keys (`previous_ssid`, `new_ssid`, `ssid`).
  Existing keys SHALL NOT change.

### `roam-detection` — poller fills SSIDs on RoamEvent
- **MODIFIED:** the roam detector (`WiFiPoller._maybe_emit_roam`)
  SHALL remember the SSID of the previous connection alongside
  the BSSID, and SHALL pass both `previous_ssid` and `new_ssid`
  when constructing the `RoamEvent`. Hidden SSIDs (`""`) and
  TCC-redacted SSIDs (`None`) flow through verbatim; the
  formatter handles them gracefully.

### `environment-monitor` — RFStirEvent picks up current SSID
- **MODIFIED:** the environment monitor SHALL pass the current
  `Connection.ssid` to `RFStirEvent` when a threshold crossing
  fires. The monitor already accepts the `Connection` snapshot;
  this is a single extra field on the constructor call.

### `tui-shell` — event line renders SSID
- **MODIFIED:** `_format_roam_event` SHALL show the SSID
  alongside the BSSID/AP-name annotation. When `previous_ssid`
  and `new_ssid` are identical (the typical band-switch case),
  the line surfaces a single `SSID: <name>` segment. When they
  differ (a true SSID hop), both SSIDs SHALL be rendered with
  an `→` between them. When both SSIDs are None, the segment
  SHALL be omitted (no `SSID: n/a` clutter).
- **MODIFIED:** `_format_rf_stir_event` SHALL append `· SSID
  <name>` after the location/AP-name segment when `event.ssid`
  is non-None. When `event.ssid` is None the segment SHALL be
  omitted entirely.
- AP-name rendering is unchanged: it continues to come from
  `format_bssid` (roam) and `event.location` (rf_stir), which
  both read `aps.yaml` via `NetworkInventory`.

## Out of Scope

- Backfilling SSIDs for `LatencySpikeEvent` / `LossBurstEvent`.
  Those events are anchored on a target IP (Router / WAN), not
  a BSSID; SSID context is already captured upstream by
  `NetworkChangeEvent` (control-plane) and the Diagnostics
  panel's connection line.
- Restructuring `RoamEvent` into a strict union of "band switch"
  vs "inter-AP roam" subtypes. The existing single struct with
  inventory-driven labelling stays; only the field set grows.
- Surfacing AP host alongside SSID in the headless JSONL. That
  would expand the analyser's read schema; this PR keeps the
  JSONL additive (new keys only).
