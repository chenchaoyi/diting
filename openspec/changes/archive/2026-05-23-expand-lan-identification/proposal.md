## Why

LAN panel today exposes only 4 weak signals — OUI vendor, reverse DNS,
Bonjour cross-reference, and ICMP RTT. On a typical CN home network this
yields rows where ~70 % of hosts show vendor `(unknown)` or
`(random MAC)`, blank Name column, and zero device context. The user
cannot answer "what is that device" without leaving diting and logging
into their router. Two structural reasons drive the gap:

1. **Passive-only discovery.** `lan.py` explicitly excludes SSDP / UPnP /
   NBNS / active mDNS, so IoT bridges, smart TVs, NAS, and Windows hosts
   that *would* reply to one UDP packet are silent in the panel.
2. **Single-tier OUI lookup.** The bundled IEEE registry holds only
   MA-L (24-bit) allocations, missing the MA-M / MA-S sub-blocks where
   most white-label IoT vendors register.

Scene awareness (shipped in v1.6.0) now gives us the right gate to add
network-active behaviour responsibly: home / office / audit can probe
freely; public stays passive unless the user explicitly opts in.

## What Changes

Layered into one capability, phased across four parts:

### Phase 1 — passive enrichment (no new packets on the wire)

- Multi-tier OUI lookup: MA-L (24-bit) → MA-M (28-bit) → MA-S (36-bit),
  longest-prefix wins. New bundled data files `wifi_ouis_ma_m.json` and
  `wifi_ouis_ma_s.json` (also reused by BLE).
- Vendor display normalization: strip `CO.`, `CORPORATION`, `LTD`, `INC`
  noise and titlecase the remainder. `"NEW H3C TECHNOLOGIES CO., LTD"` →
  `"New H3C"`.

### Phase 2 — active discovery layer (scene-gated)

- NBNS Name Query (UDP 137, unicast) per silent host with no reverse
  DNS + no Bonjour name → populates `nbns_name` field on `LANHost`.
- SSDP / UPnP M-SEARCH (UDP 1900, multicast `239.255.255.250`) once per
  sweep → captures `Server:` header and `LOCATION:` URL; optionally
  fetches the LOCATION XML for `<friendlyName>` and `<modelName>`.
- Active mDNS browse query (`_services._dns-sd._meta._tcp.local`) once
  per sweep → forces Apple-ecosystem and HomeKit devices to announce.
- Scene-aware defaults: **home / office / audit on; public off**.
  Knob exposed via `scene_defaults()` like `ble_presence_gate_s`.
- Env override `DITING_LAN_PROBE=0|1` forces the layer off / on
  regardless of scene.

### Phase 3 — heuristics

- TTL fingerprint captured from ping output → discriminates Linux/macOS/
  iOS/Android (TTL≈64) vs Windows (≈128) vs legacy routers (≈255).
- Device-class inference rules table — consumes (vendor, randomised
  flag, Bonjour services, NBNS name, UPnP Server header, TTL) →
  classifies into `phone | laptop | desktop | tv | iot | printer |
  nas | gaming | speaker | router | unknown`. Class surfaced as new
  one-character column in the LAN row and a `Class:` row in the detail
  modal.

### Phase 4 — UX

- `[new]` chip on rows whose `first_seen < 24 h`. Signals unfamiliar
  devices instantly.
- Public-scene **"user-accepts-risk" probe override**: in public scene
  the LAN view binds `P` to a confirmation modal that explicitly
  enumerates what packets will be sent and the consequences. Confirming
  triggers a **one-shot** probe (NBNS + UPnP + mDNS) and writes a
  `lan_active_probe_consented` JSONL event for audit replay. Two-second
  confirm cooldown to defeat muscle-memory. Re-confirm required on
  every press.
- `[probing]` subtitle chip while a probe sweep is in flight.

## Capabilities

### New Capabilities

(none — all changes land in existing capabilities.)

### Modified Capabilities

- `lan-inventory`: new active-discovery sources, OUI multi-tier
  lookup, vendor normalization, TTL fingerprint, device class,
  new-today flag, public-scene override binding + modal.
- `scenes`: extend `scene_defaults()` with `lan_active_probe`
  boolean (true for home/office/audit, false for public).
- `events`: new `lan_active_probe_consented` event.
- `event-log`: emit the new event type to JSONL.
- `tui-shell`: new `P` keybinding when on LAN view + public scene;
  `[probing]` subtitle chip; LAN-row class column + new chip.
- `i18n`: EN + ZH strings for vendor normalization output, class
  names, probe modal copy, `[new]` and `[probing]` chips.
- `cli`: new `DITING_LAN_PROBE=0|1` env var documented in `--help`.

## Impact

- **Code**: `src/diting/lan.py` (largest changes), `src/diting/scene.py`
  (new knob), `src/diting/data/` (new OUI files + maybe an OUI
  normalization rules file), `src/diting/tui.py` (`P` modal, class
  column, chip rendering), `src/diting/events.py`, `src/diting/event_log.py`,
  `src/diting/i18n.py`, `src/diting/cli.py`. New module
  `src/diting/lan_probes.py` for the NBNS / UPnP / mDNS senders to keep
  `lan.py` focused on the inventory state machine.
- **Tests**: new `tests/test_lan_probes.py`, `tests/test_oui_multitier.py`,
  `tests/test_device_class.py`, `tests/test_vendor_normalize.py`,
  extensive additions to `tests/test_lan.py` and `tests/test_tui.py`.
- **TESTING.md** + **docs/zh/TESTING.md**: new section per the
  test-first rule.
- **Snapshot regression**: new fixtures cover class column + new chip.
- **Dependencies**: zero new third-party packages. NBNS / UPnP / mDNS
  use stdlib `socket` + `asyncio`. OUI files refreshed via existing
  `scripts/refresh_ouis.py` (script extended to also pull MA-M / MA-S).
- **Permissions**: no new TCC prompts. NBNS / UPnP / mDNS use ordinary
  unprivileged UDP sockets the user's diting already opens (mdns
  poller already binds 5353 multicast).
- **Privacy / netiquette**: public scene stays passive by default;
  override is one-shot, requires confirmation, and is JSONL-audited.
- **Spec deltas**: `lan-inventory`, `scenes`, `events`, `event-log`,
  `tui-shell`, `i18n`, `cli`.
