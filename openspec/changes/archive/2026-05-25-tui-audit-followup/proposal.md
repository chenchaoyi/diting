## Why

The 2026-05-25 `/tui-audit` run against a real corporate Wi-Fi + dense
BLE environment surfaced three rendering bugs that make the TUI read
worse than the underlying data warrants. Each is small in isolation
but each one degrades the user's ability to trust what the panels say:

1. **LAN detail shows truncated MACs.** macOS `arp -an` strips leading
   zeros per octet, so the gateway's MAC renders as
   `14:51:7e:71:5a:1` in `LANDetailScreen`. The user assumes the
   parser broke; the value is also unhelpful for copy/paste.
2. **BLE rows render rotating-identifier strings as device names.**
   Apple Continuity Find-My beacons publish 22-char base64 names
   (`NZ1NhvIw3H5T5cSy3kULrJ`); Huami / Amazfit watches publish serials
   (`Z-GM0YXG6A`). The list reads as if these were real local names —
   they're not, and the user has no way to distinguish "device with no
   useful name" from "device named like a hash".
3. **Events modal is a flood of anonymous BLE-seen rows.** Each Apple
   Continuity or Microsoft CDP advertisement rotates its identifier,
   and each rotation fires a fresh `BLEDeviceSeenEvent`. Source-side
   dedup is correct per-identifier, but the modal renders 100 nearly
   identical `device seen: Apple, Inc. · (anonymous)` lines and
   buries the events that matter (AP roam, link drop, DHCP rotation,
   LAN host arrival).

All three are display-layer fixes — the underlying data models do not
change. None are blocking, but together they cut into the polish that
`/tui-audit` is meant to enforce.

## What Changes

### Fix 1 — Zero-pad MAC octets at ARP-cache ingest

In `src/diting/lan.py:_read_arp_cache`, normalise each captured MAC to
`"".join` of zero-padded octets before handing it to the merger. The
fix lives at the data boundary so every downstream consumer (LAN list
column, detail modal, JSONL event log) sees the canonical form. OUI
lookup already tolerates either form; behaviour is preserved.

### Fix 2 — BLE name sanity guard

In the BLE list row renderer (`src/diting/tui.py`, the row formatter
for `live_ble`), introduce a `_looks_like_rotating_id(name)` helper.
When a non-empty `name` matches the high-entropy pattern
`^[A-Za-z0-9+/=_-]{16,}$`, contains no whitespace, and does NOT start
with one of the known Apple product prefixes (`iPhone`, `iPad`, `Mac`,
`AirPods`, `HomePod`, `Apple TV`, `Apple Watch`), the row SHALL
render `(rotating ID)` in place of the raw string. The raw string
SHALL remain visible in the BLE detail modal under a new `Raw name:`
row so users investigating a specific device can still see exactly
what the helper reported.

### Fix 4 — ZH catalog gaps surfaced by the 18:55 ZH-locale audit

Running the same audit under `DITING_LANG=zh` surfaced seven copy
defects, all confined to `src/diting/i18n.py`:

- the entire shift-P / public-scene help line is missing from the ZH
  catalog and falls back to raw English in the help modal
- `"service"` is self-mapped (`"service" → "service"`), so the
  Bonjour panel renders `排序：service` instead of `排序：服务`
- the basics-modal section heading `Noise / SNR` is self-mapped
  while every peer (`RSSI / 信号`, `频段`, `信道`, `带宽`, `加密`,
  `漫游`, `房间`) is translated
- `" ago" → "前"` drops the leading space, producing `8s前` in the
  LAN diagnostics / detail "可达" row and the BLE detail Activity
  rows, while the `"  · {n}s ago"` template form renders `5s 前扫描`
  with the space — two duration shapes coexist in the same screen
- `Apple Companion → Apple 配对` reads as "Bluetooth pairing" in
  Chinese, a different mental model than what
  `_companion-link._tcp` actually represents (Apple Continuity)
- `Apple Nearby Info → Apple 邻近` is a half-translation that reads
  as an incomplete adjective phrase
- the ZH catalog entry for the Activity ad-interval hint preserves
  EN word order (`(~1772 ms 两次广播间隔)`) where ZH idiomatic
  ordering puts the value last (`(两次广告间隔约 1772 ms)`)

### Fix 3 — Events modal collapses consecutive duplicate BLE-seen rows

In the events modal renderer (Events panel in `src/diting/tui.py`,
sourced from `event_log.EventRing`), group adjacent
`BLEDeviceSeenEvent` rows whose `(vendor, name_or_anonymous_label)`
tuple is identical into a single line with a `×N` suffix. Grouping is
purely cosmetic and applies only to the modal render path; the
underlying `EventRing` and the JSONL log are unchanged. Non-`BLE` event
types reset the grouping; this keeps the relative ordering of
heterogeneous events intact.

## Capabilities

### New Capabilities

(none — all changes land in existing capabilities.)

### Modified Capabilities

- `lan-inventory`: MAC normalisation contract added to the ARP ingest
  requirement; every `LANHost.mac` is now guaranteed zero-padded.
- `bluetooth-scanning`: new requirement that the BLE panel SHALL
  substitute `(rotating ID)` for high-entropy local names while
  preserving the raw value in the detail modal.
- `tui-shell`: new requirement under EventsScreen that the modal
  renderer SHALL collapse runs of identical consecutive
  `BLEDeviceSeenEvent` rows with a `×N` suffix. The JSONL contract
  in `event-log` is unchanged — this is a display-layer addition
  only.
- `i18n`: new requirement that the ZH catalog SHALL ship
  translations for the seven copy defects above; in particular,
  no self-mapped ZH entry where a peer key is translated, no
  partial-translation Apple-Continuity protocol names, and a
  uniform `{n}s 前` (with leading space) shape for the bare
  `" ago"` key.

## Impact

- **Code**: `src/diting/lan.py` (MAC normalisation in
  `_read_arp_cache`); `src/diting/tui.py` (BLE row renderer + events
  modal grouping + BLE detail modal new `Raw name:` row);
  `src/diting/i18n.py` (EN + ZH for `(rotating ID)` and `Raw name`).
- **Tests**: extend `tests/test_lan.py` (zero-pad on ingest);
  extend `tests/test_tui.py` (rotating-ID guard, events-modal
  grouping); update `tests/TESTING.md` + `docs/zh/TESTING.md` with
  one section per fix.
- **Snapshot regression**: existing synthetic fixtures continue to
  pass — none of them rely on un-padded MACs or high-entropy BLE
  names. A regression fixture that *would* have triggered the
  rotating-ID guard is added so the heuristic is exercised in CI.
- **Dependencies**: none.
- **Permissions / privacy**: none. All three changes are
  display-only.
- **Spec deltas**: `lan-inventory`, `bluetooth-scanning`, `tui-shell`, `i18n`.
