# fix-bssid-zero-padding — design

## Context

Three BSSID producers feed the app: CoreWLAN scan / helper scan
(zero-padded), CoreWLAN `iface.bssid()` (padded in practice), and the
SCDynamicStore `CachedScanRecord` fallback (NOT padded — macOS formats
those octets `%x`). Every consumer — `_merge_current`, AP grouping,
roam detection, the familiarity store, `aps.yaml` inventory matching —
compares plain strings after `.lower()`. The repo has already fixed
this exact quirk twice at other boundaries (`lan.py` ARP parse,
`ble.py` MiBeacon MAC), each with a local `zfill(2)` pass.

## Goals / Non-Goals

**Goals:**

- One canonical BSSID spelling (`aa:bb:cc:dd:ee:0f`, lowercase,
  zero-padded) everywhere downstream of the producers.
- The 2026-06-07 duplicate-row symptom (and the phantom-roam /
  split-familiarity hazards it implies) cannot recur from any of the
  three producer paths.

**Non-Goals:**

- Migrating historical JSONL logs or the existing familiarity store
  (old `ap:…:b`-style keys age out within the 30-day retention; not
  worth a migration).
- Unifying the LAN/BLE MAC helpers into one function — their input
  shapes differ (ARP junk tolerance, 12-hex no-separator form); a
  shared Wi-Fi-shaped helper keeps each boundary honest without a
  mega-normalizer.

## Decisions

- **Normalize at producer boundaries, compare-normalize as defense.**
  `normalize_bssid()` lives in `models.py` (next to the dataclasses it
  guards) and is applied where BSSIDs enter: `_dynamic_store` (the
  actual culprit), `macos_backend.get_connection` + `scan`, `_helper`
  scan parse. `_merge_current` additionally normalizes both sides of
  its comparison so injected backends (tests, snapshot fakes) cannot
  resurrect the bug. Alternative — normalizing only in consumers —
  rejected: there are many consumers (grouping, roam, familiarity,
  inventory) and exactly three producers.
- **Fail-soft for non-MAC strings.** Anything that doesn't split into
  six 1–2-char hex octets is returned lowercased as-is, never raised —
  matching the decoder convention; a malformed vendor string must not
  crash the poll loop.

## Risks / Trade-offs

- [Existing familiarity records keyed on the un-padded spelling split
  history with the padded one] → bounded: the store ages entities out
  after 30 days, and the padded spelling is the overwhelmingly common
  one (the un-padded form only appears for the *currently associated*
  AP via the TCC fallback).
- [A future macOS surface emits a different separator (dashes, no
  separator)] → out of scope; fail-soft passes it through unchanged,
  which is today's behaviour.
