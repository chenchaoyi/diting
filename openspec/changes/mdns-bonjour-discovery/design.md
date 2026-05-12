## Context

Diting today covers two radio surfaces:
- **Wi-Fi** via `MacOSWiFiBackend` + `WiFiPoller` (CoreWLAN scan + SCDynamicStore fallback).
- **BLE** via the Swift helper `diting-tianer ble-scan` + `BLEPoller`.

Both are passive radio observers. The TUI's third panel slot already
hosts a 2-way swap between them, driven by the `n` key binding and the
`_view_mode` state on `DitingApp` (`"wifi"` ↔ `"ble"`).

mDNS / Bonjour is a third passive observation surface that diting
doesn't touch. It runs at the IP / link layer rather than the radio
layer — every device on the same link that wants to be findable sends
multicast DNS announcements describing its services. The Mac is
already receiving them; the OS browser (`dns-sd -B`) can list them on
demand but the system Wi-Fi menu never shows them.

Python's `zeroconf` library (pure-Python, well-maintained, used in
Home Assistant + many other projects) provides the listen-only browser
that produces a callback per service-instance announcement.

The user-facing pitch from proposal.md: a third panel that mirrors
the existing BLE list's structure but simpler. The technical question
is *how to integrate this with the existing 2-panel architecture
without disturbing it.*

## Goals / Non-Goals

**Goals:**

- One additional view mode without overloading the BLE poller or the
  Wi-Fi scan path. `BonjourPoller` is its own dedicated async
  consumer mirroring `BLEPoller`'s shape.
- Same row-rendering vocabulary the user already knows: vendor +
  name + service-categories + age + short id columns. CJK-safe
  alignment via `pad_cells` / `fit_cells`.
- Passive only — diting subscribes to the multicast group, never
  initiates probes for arbitrary service types.
- Vendor + service-category resolution reuse existing diting
  infrastructure (OUI map, name patterns) so the data feels
  consistent across BLE and mDNS rows.
- Zero impact on the Wi-Fi and BLE paths. A user who never presses
  `n` a second time sees no behavior change.
- Pure-Python dep (`zeroconf`); no helper changes.

**Non-Goals:**

- **No active probing of arbitrary service types.** Diting only
  listens to the well-known categories enumerated in
  `bonjour_services.json`. No `_all-services._tcp.local.` storms.
- **No resolution of host A/AAAA records.** The service browser
  produces `(service_type, name, server, port, addresses)` —
  diting uses the announce-supplied data only. No DNS lookups
  on top.
- **No JSONL event types for mDNS in v1.** mDNS state is a snapshot;
  emitting `bonjour_appear` / `bonjour_disappear` events is a
  follow-up call once we understand the noise floor.
- **No filter UI for service categories.** Future-feature; v1
  shows everything in one list.
- **No active interaction.** Diting lists services, doesn't connect
  to them, mount them, or authenticate against them.
- **No cross-VLAN reach.** mDNS is link-local by design.
- **No persistence across sessions.** The snapshot resets on
  restart (same model as the BLE list).

## Decisions

### One new `BonjourPoller`, mirroring `BLEPoller`'s contract

`src/diting/mdns.py:BonjourPoller` exposes:

```python
class BonjourPoller:
    def __init__(self, *, snapshot_interval_s: float = 2.0,
                 ttl_s: float = 60.0) -> None: ...
    async def events(self) -> AsyncIterator[BonjourScanUpdate]: ...
    def stop(self) -> None: ...
```

`BonjourScanUpdate` carries `devices: list[BonjourDevice]` —
already-deduplicated, ready for the panel to render.

`BLEPoller`'s pattern is the proven model: helper-side process
emits raw events, a Python-side state container holds them with TTL
expiry, a snapshot loop emits a `dict[str, BonjourDevice].values()`
list every N seconds. `BonjourPoller` is the same minus the helper
process — `zeroconf` directly fires Python callbacks on the
multicast thread, which the poller marshals onto its asyncio queue.

Why not extend `BLEPoller`? Different transport (multicast vs
helper-stdin), different identifiers (service-instance key vs
peer-UUID), different TTLs (mDNS records carry their own TTL).
Keeping the two pollers separate matches their independent
lifecycles.

### Service-type → category mapping in `bonjour_services.json`

Bundle the well-known service-type → friendly-name mapping as a JSON
data file alongside the existing GATT services / OUI tables. v1
covers what users actually have:

- `_airplay._tcp` → `AirPlay`
- `_raop._tcp` → `AirPlay audio`
- `_googlecast._tcp` → `Chromecast`
- `_sonos._tcp` → `Sonos`
- `_ipp._tcp` / `_ipps._tcp` / `_printer._tcp` → `Printer`
- `_smb._tcp` / `_afpovertcp._tcp` → `File share`
- `_workstation._tcp` → `Mac`
- `_hap._tcp` → `HomeKit`
- `_companion-link._tcp` → `Apple Companion`
- `_homekit._tcp` → `HomeKit`
- `_rfb._tcp` → `Screen sharing`
- `_ssh._tcp` → `SSH`
- `_http._tcp` / `_https._tcp` → `HTTP`
- `_meshcop._udp` → `Thread`
- `_matter._tcp` → `Matter`

Unknown service types pass through as their raw underscore-form
(`_my-custom._tcp`) so the user can see exactly what was announced —
matching the existing BLE "raw UUID prefix" honesty policy.

### Vendor resolution: lookup chain mirrors BLE

`BonjourDevice.vendor` is resolved via the same deterministic chain
as `BLEDevice`, adapted to mDNS data:

1. **TXT-record vendor field** if the service announces a `vendor=`
   or `manufacturer=` TXT entry (some Sonos / Roku devices do).
2. **OUI lookup** if the service announces a MAC address in TXT or
   `addresses` (reuses `lookup_oui_vendor` from `ble.py`).
3. **Hostname pattern** (`Apple-...` / `HP-...` / `Synology-...` /
   `Sonos-...`) — reuses the existing `_NAME_PATTERN_VENDORS`
   table from `ble.py`.
4. **Service-type vendor hint** — `_googlecast._tcp` implies Google,
   `_airplay._tcp` strongly implies Apple, etc. A small
   `_SERVICE_VENDOR_HINTS` table maps these.
5. Abstain. `vendor=None` renders as `(unknown)` / `(未知)`.

Reusing the BLE OUI map and name-pattern table is deliberate — those
tables capture the same hardware ecosystem the user sees on BLE.

### View toggle: 2-way → 3-way cycle

Today's `n` key swaps `_view_mode` between `"wifi"` and `"ble"`. The
extension is mechanical:

```python
_VIEW_MODES = ("wifi", "ble", "mdns")

def action_toggle_view(self) -> None:
    i = _VIEW_MODES.index(self._view_mode)
    self._view_mode = _VIEW_MODES[(i + 1) % len(_VIEW_MODES)]
    self._refresh_view_panels()
```

`_refresh_view_panels()` shows the panel that matches `_view_mode`
and hides the others — same display-toggle pattern the existing
2-way swap uses.

Footer label changes from `→ BLE` to a cycle hint. The simplest
honest label is `→ next view` (cycles through the three). Updating
the binding's translated label in `BINDINGS` plus the `tui-shell`
spec's view-toggle Requirement.

### `BonjourPanel` widget mirrors `BLEPanel`'s shape

Same composition (`VerticalScroll` containing a `Static` body),
same row format (vendor / name / services / age / id), same border-
title pattern. Differences:
- No RSSI column (no signal strength on mDNS).
- No connected-vs-advertising split (one flat list).
- No history sparkline (no per-device numeric series).

The `_bonjour_row_line` helper mirrors `_ble_row_line` minus the
RSSI / signal-bar / connected-state branches. Around 60 LOC total
for the renderer.

### Diagnostics row reuses the BLE-side helper pattern

When `_view_mode == "mdns"`, the diagnostics panel renders a
`BonjourPanel`-specific summary built by `_bonjour_diagnostic_lines`:

```
Visible Bonjour  14 total  ·  6 service types
Top services     AirPlay 5  ·  Printer 2  ·  Chromecast 2  ·  Mac 2
Top vendors      Apple, Inc. 7  ·  HP 2  ·  Sonos 2  ·  ? 1
```

Mirrors the BLE-view `_ble_diagnostic_lines` shape so users carry
their existing reading habits over.

### Snapshot model + TTL

Each Bonjour service instance is keyed by `(service_type, name)`.
The state map holds `{(service_type, name): BonjourDevice}` with
`last_seen` timestamps. Records are expired when:
1. `last_seen` is older than the service's own TTL (carried in the
   record).
2. Falling back to a `_BROWSE_TTL_S = 60` default when TTL is unset.

Snapshot cadence: 2 seconds (same as BLE) — fast enough that
appearing / disappearing devices feel responsive, slow enough that
the panel doesn't flicker on every multicast packet.

### `zeroconf` library: why this dep, why not a from-scratch parser

mDNS is a chatty wire format with multiple record types (PTR, SRV,
TXT, A, AAAA), name compression, and an evolving conformance
landscape. Writing a hand-rolled parser is a substantial effort
that mostly recreates what `zeroconf` does. The library is:

- Pure-Python (no native extensions).
- Used by Home Assistant, AsyncSSH-based projects, etc. — a known
  ecosystem dep.
- Actively maintained; bug fixes flow regularly.
- Listen-only when used via `ServiceBrowser` without registering
  any services of our own.

The trade-off is one new pyproject dependency. Mitigations:
- Lazy import inside `mdns.py` so users who never press `n` twice
  pay nothing.
- Pin a lower bound on a recent-enough version (`>= 0.130`); leave
  the upper bound unpinned so security fixes flow.

### Listening interface = the live Wi-Fi link

`zeroconf.Zeroconf(interfaces=InterfaceChoice.Default)` binds to all
"up" interfaces by default. For a typical laptop on one Wi-Fi link,
that's exactly what we want — we see the local airspace, nothing
else. If multiple interfaces are up (Wi-Fi + Ethernet + VPN)
discovery spans them — also fine, those ARE the user's local
airspaces. No need to override.

## Risks / Trade-offs

- **Risk**: the multicast browse for many service types could be
  CPU-noisy on a busy network (corporate Wi-Fi with hundreds of
  IoT devices announcing constantly).
  → **Mitigation**: we subscribe to a curated list of well-known
  service types (the entries in `bonjour_services.json`) — not to
  `_services._dns-sd._udp.local.` (the meta-browse that surfaces
  every service type). Curated list caps the inbound traffic to
  what users care about.

- **Risk**: the `zeroconf` library starts its own background
  thread; without careful cleanup the TUI may hang on exit.
  → **Mitigation**: `BonjourPoller.stop()` calls
  `zeroconf.Zeroconf.close()` synchronously, which the library
  documents as joinable. The TUI's existing `on_unmount` already
  calls `.stop()` on `BLEPoller`; we add the same call for
  `BonjourPoller`.

- **Risk**: mDNS records have a TTL of their own (often 4500 s for
  cached SRV); our 60-second default `_BROWSE_TTL_S` could expire
  rows the library still considers live.
  → **Mitigation**: prefer the library's `ServiceListener` events
  (`add_service` / `remove_service`) as the source of truth.
  Only use the fallback TTL for records we never see a remove
  for (e.g., the announcing device powered off cleanly).

- **Risk**: TXT-record vendor fields are inconsistent across
  vendors — `vendor=Apple Inc` vs `manufacturer=Apple` vs nothing.
  → **Mitigation**: the lookup chain falls through gracefully.
  Step 1 catches the consistent-vendor case; steps 2-4 catch the
  rest; step 5 abstains rather than guessing.

- **Trade-off**: link-local broadcast contains
  user-identifiable data (your colleague's `Macbook-Pro.local`
  shows up). Diting already surfaces real BSSIDs and BLE device
  names; this is consistent with prior privacy policy: passive
  observation of what's already broadcast, never persisted to
  the repo, sometimes redacted in shared screenshots.
  → **Acceptance**: same privacy story as BLE. Document in
  CLAUDE.md alongside the existing BSSID / BLE notes.

- **Risk**: `zeroconf` library bugs / security CVEs would
  affect diting.
  → **Acceptance**: same risk as any external dep. The library
  is mature and well-maintained; if a CVE lands we bump the lower
  bound.

## Migration Plan

1. Cut `feature/mdns-bonjour-discovery`.
2. Phase A: OpenSpec scaffolding (this set of artifacts).
3. Phase B: implement
   - `src/diting/data/bonjour_services.json`
   - `src/diting/mdns.py`
   - `src/diting/tui.py` — new `BonjourPanel`, 3-way view-mode,
     diagnostic helpers, footer label.
   - `src/diting/i18n.py` — EN / ZH entries for new panel + diag.
   - Tests: `tests/test_mdns.py` (unit) + extend
     `tests/test_tui_smoke.py` (3-way toggle).
   - `tests/TESTING.md` + `docs/zh/TESTING.md`.
   - `CHANGELOG.md` + `docs/zh/CHANGELOG.md`.
   - `pyproject.toml` (add `zeroconf >= 0.130`).
4. Self-test all four CI gates.
5. PR.
6. After merge: `openspec archive mdns-bonjour-discovery` to apply
   the new `mdns-scanning` capability spec into canonical
   `openspec/specs/`.

Rollback: revert the merge commit. `zeroconf` dep would auto-resolve
out via `pyproject.toml`.

## Open Questions

- **Curated service-type list size for v1**: ~15 well-known types
  feels right (covers AirPlay / Cast / printer / file-share / Mac /
  HomeKit / SSH / Thread / Matter). Should we ship more out of the
  gate (Spotify Connect, Roku, Plex, Synology-specific) or wait for
  user feedback?
- **Should the 3-way toggle remember the user's previous mode?**
  If a user toggles to mDNS, opens a modal, closes it, presses `n`
  — do they expect to land on the FOURTH mode (skip back to Wi-Fi),
  or move forward in the cycle? Current proposal: always forward.
  Open to feedback.
- **Future event types**: `bonjour_appear` / `bonjour_disappear`
  would let the watchdog notify on "AirTag entered the room" /
  "Printer went offline". Punt to a follow-up change once the v1
  data shape is stable.
