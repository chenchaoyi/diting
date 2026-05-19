## Why

The v1.2.0 LAN inventory landed (#93) and a real-environment Meituan
corp-network audit surfaced two gaps in the LAN host detail modal
(`LANDetailScreen`, opened via `i` from the LAN view):

1. **`(unknown)` dominates the Vendor row.** The bundled OUI map
   `wifi_ouis.json` is a hand-curated ~250-entry subset originally
   built for BLE. It misses Apple OUIs the user actually has
   (`84:2f:57`), HP / HPE switch OUIs (`14:51:7e`), and most
   enterprise / consumer router brands. The data file is what's
   missing, not the lookup logic.

2. **The modal is informationally thin.** Identity / Network /
   Bonjour services / Activity is correct but doesn't surface
   *reachability* — the user can't tell whether the host
   responded to ICMP this sweep, or how far it is in RTT terms.
   The Bonjour services section also disappears entirely when
   empty, so the user has no signal that channel was checked.

Two follow-ups to address both:

- A **full IEEE OUI sync** (~35k entries) replaces the curated
  subset. A `scripts/refresh_ouis.py` script downloads the IEEE
  Registration Authority's MA-L CSV at any time so future refreshes
  are a single command. Pure data change; lookup function logic is
  unchanged.
- New **`last_rtt_ms`** and **`last_reachable_at`** fields on
  `LANHost`, populated from the sweep's per-host ping results.
  The detail modal renders both as `Latency` and `Reachable` rows
  in the Network section; the Bonjour services section gains a
  `(no Bonjour services)` placeholder when empty.

## What Changes

### `lan-inventory`

- **MODIFIED:** `_ping_one(ip, timeout_ms)` SHALL return
  `tuple[bool, float | None]` — `(reachable, rtt_ms)` — by
  parsing the `time=X.XXX ms` line from macOS `ping`'s stdout.
  The boolean half preserves the existing reachable contract.
  RTT is `None` when the host did not respond.
- **MODIFIED:** `_sweep(hosts)` SHALL return a dict
  `{ip: (reachable, rtt_ms | None)}` instead of returning None,
  so the merge step can populate the new `LANHost` fields without
  re-running the kernel ARP read against per-host results.
- **ADDED:** `LANHost` SHALL gain two fields:
  - `last_rtt_ms: float | None` — RTT of the most recent
    successful ICMP echo for this host's current IP, in
    milliseconds; `None` until the host has responded to ICMP at
    least once.
  - `last_reachable_at: datetime | None` — UTC timestamp of the
    most recent successful ICMP echo; `None` until the host has
    responded at least once. Distinct from `last_seen` (which
    tracks ARP cache entries, including stale ones).
- **ADDED:** the merge step SHALL preserve `last_rtt_ms` and
  `last_reachable_at` across sweeps that don't get an ICMP reply
  (so a temporarily silent host still shows its last-known RTT
  in the modal).

### `tui-shell`

- **MODIFIED:** `LANDetailScreen`'s Network section SHALL render
  two additional rows when the data is available: `Latency`
  (formatted `XX.X ms` from `last_rtt_ms`) and `Reachable`
  (formatted as `this sweep` when `last_reachable_at` is within
  the last sweep cadence, otherwise relative duration via
  `_format_duration_short`). When `last_rtt_ms` is None the
  Latency row is omitted (no information to show); when
  `last_reachable_at` is None the Reachable row is rendered as
  `never` (informative — tells the user diting has not seen a
  ping reply for this host yet this session).
- **MODIFIED:** `LANDetailScreen`'s Bonjour services section
  SHALL render a single dim-italic placeholder line
  `(no Bonjour services)` (EN) / `（无 Bonjour 服务）` (ZH) when
  the host has no Bonjour services. This replaces the current
  behaviour of hiding the section entirely; users had no signal
  that the cross-reference channel was checked.

## Out of Scope

Documented in the explainer but explicitly NOT in this MVP:

- **MA-M (28-bit) and MA-S (36-bit) OUI sub-allocations.** A
  separate spec ADDS these when a real user surfaces a MA-M /
  MA-S device the MA-L lookup misses.
- **Latency history sparkline.** Showing a rolling N-sample RTT
  chart in the modal would require a per-host history buffer
  similar to `BLEHistory`. Defer.
- **Runtime OUI fetch.** `diting --update-ouis` to pull fresh
  data without re-installing — defer; the bundled snapshot
  refreshes per release, which is enough for now.
- **Hop count from ICMP TTL.** Useful but adds parsing
  complexity; skip in this pass.

## Migration / Defaults

- `LANHost.last_rtt_ms` / `last_reachable_at` default to None on
  first observation. Existing snapshots (in-memory state across
  the upgrade) continue to work — both fields are additive.
- The OUI data file grows from ~10 KB to ~3 MB. Lookup is still
  O(1); first-load parse adds 50-100 ms but it's already
  lazy-cached.
- IEEE attribution added to `_meta` and `README.md`.
