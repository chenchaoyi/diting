## Context

`lan.py` today is strictly passive: ICMP echo to populate the kernel
ARP cache, then read `arp -an`, then enrich with OUI lookup + reverse
DNS + Bonjour cross-reference. The module docstring explicitly excludes
"port scanning, SSDP / UPnP probing, NetBIOS queries, TCP banner grabs,
raw-socket ARP injection" — a deliberate posture from when scene
awareness did not exist yet.

Scene awareness (v1.6.0) now gives us a clean axis to relax that
posture **only where the user has a moral claim to the network**. We
can default `home / office / audit` to active probing while keeping
`public` passive — and add a one-shot user-consent escape hatch in
public for the "I know what I'm doing" case.

Today's identification gap on a typical home network (observed
2026-05-23): ~24 LAN hosts, ~3 enriched via Bonjour, the remaining 21
showing `(unknown)` or `(random MAC)` in the vendor column and blank
in the Name column. Detail modal for the gateway row shows only
`Vendor + Latency + Reachable` — Network section is sparse, no model,
no class, no DHCP-supplied name.

## Goals / Non-Goals

**Goals:**

- Multi-source identification: vendor (multi-tier OUI), reverse DNS,
  Bonjour, NBNS, UPnP friendly-name + model, mDNS active query.
- Scene-aware default behaviour: home / office / audit probe;
  public is passive.
- Public-scene **explicit user consent override** with a confirmation
  modal modelled on the existing Wi-Fi reconnect flow.
- Device-class inference surfacing a one-word category in the row +
  detail modal.
- Visual freshness signal (`[new]` chip) for hosts new today.
- Zero new third-party dependencies; zero new TCC permissions.

**Non-Goals:**

- TCP port scanning, banner grabbing, fingerprinting via deep packet
  inspection.
- Manual `lan.yaml` user-annotation file — deliberately deferred (not
  in this scope; can land later as a thin layer).
- `/etc/hosts` lookup — deliberately deferred.
- Apple-sub-row folding — deliberately deferred.
- ARP injection / spoofing / raw-socket access.
- Re-architecting the lan-inventory poller — additions only, no
  changes to the state-machine shape.

## Decisions

### D1. Active discovery layered as a separate module, not inlined into `lan.py`

New module `src/diting/lan_probes.py` owns the NBNS / UPnP M-SEARCH /
active-mDNS senders. `lan.py` keeps owning the sweep loop +
state-machine + ARP merge; on each tick, if active probing is enabled
for the current scene, it calls into `lan_probes` with the per-host
candidate list and merges the returned enrichments.

**Alternatives considered:** inline in `lan.py`. Rejected — `lan.py`
is already 724 lines and the probe protocols are orthogonal to the
ARP/ICMP merge logic. Separate module also lets us unit-test the
probe parsers (NBNS response decoding, SSDP HTTP parsing) without
mocking the full poller.

### D2. Scene gate via `scene_defaults()["lan_active_probe"]`, env via `DITING_LAN_PROBE`

`scenes.spec.md` already defines `scene_defaults(scene)` as the canonical
knob-mapping function. Add the bool `lan_active_probe`:

| Scene | `lan_active_probe` |
|---|---|
| `home` | `True` |
| `office` | `True` |
| `audit` | `True` |
| `public` | `False` |

Env override `DITING_LAN_PROBE=0|1` forces off / on regardless of
scene. Per-process CLI flag deliberately omitted — scene is the
contract; env is the escape hatch.

Resolution order at startup: `DITING_LAN_PROBE` > `scene_defaults`.

### D3. Public-scene override: one-shot, modal-confirmed, JSONL-audited

In public scene with `DITING_LAN_PROBE` unset, the LAN view binds `P`
(uppercase, lowercase `p` already = pause) to push a `LANProbeConsentScreen`
modal. The modal:

- Shows current scene + connected SSID.
- Enumerates **what packets** will be sent (NBNS UDP 137 unicast,
  SSDP UDP 1900 multicast, mDNS UDP 5353 multicast).
- States the **consequences** (other guests' devices receive the probes;
  IDS may flag; captive portal may rate-limit).
- Has a **2-second cooldown** before the confirm key (`y`) activates —
  defeats muscle-memory press-through.
- On confirm: fires a one-shot probe sweep, writes a
  `lan_active_probe_consented` JSONL event, sets `_one_shot_probe_armed = True`
  on the poller so the **next** sweep tick runs the probe layer once
  and clears the flag.

Re-confirm required on every `P` press — no sticky state. The
override does NOT change the scene or the env var.

**Alternative considered:** sticky "enable for this session" toggle.
Rejected — sticky state is the failure mode (you forget you turned it
on, walk into a hotel, leak probes). One-shot is the principled
default.

### D4. OUI multi-tier lookup, longest-prefix wins

IEEE registers OUIs in three sizes:

- MA-L: 24-bit prefix (the current dataset, 39 k entries).
- MA-M: 28-bit prefix — a smaller manufacturer assigned a slice of a
  MA-L block. Lookup must match the longer prefix BEFORE falling back
  to the 24-bit.
- MA-S: 36-bit prefix — even smaller manufacturer. Same fallback
  pattern.

Implementation:

1. `scripts/refresh_ouis.py` extended to fetch + emit
   `wifi_ouis_ma_m.json` and `wifi_ouis_ma_s.json` alongside the
   existing 24-bit file.
2. `lookup_oui_vendor(mac, *, ma_l, ma_m, ma_s)` tries 36-bit, then
   28-bit, then 24-bit. First match wins.
3. `ble.py` and `lan.py` both load all three tables via a shared
   helper `load_ouis_layered()`.

**Alternative considered:** single merged dict with longest-key
disambiguation. Rejected — separate dicts keep the data files
auditable and the lookup function trivially testable.

### D5. Vendor name normalization is a pure post-processing pass

After lookup returns the raw IEEE string, run it through
`_normalize_vendor(name)`:

- Strip trailing `CO.`, `CO.,LTD`, `CO., LTD`, `CORPORATION`, `CORP`,
  `LTD`, `LTD.`, `INC`, `INC.`, `GMBH`, `LLC`, `B.V.`, `S.A.`, `LIMITED`,
  `COMPANY`, `TECHNOLOGIES`, `TECHNOLOGY`, `ELECTRONICS`, `ELECTRONIC`.
- Strip leading `SHENZHEN `, `HANGZHOU `, `BEIJING `, `SHANGHAI `,
  `GUANGZHOU ` (Chinese city prefixes that bloat names without
  identifying the company).
- Apply titlecase, preserving common acronyms (HP, IBM, ASUS, ASRock,
  H3C, TP-Link, D-Link).
- Truncate to 16 cells (column width).

The raw IEEE string is preserved on `LANHost.vendor_raw` for the
detail modal — the row shows the normalized form, the modal can show
both ("displayed: `New H3C`; IEEE: `NEW H3C TECHNOLOGIES CO., LTD`").

**Alternative considered:** ship a per-vendor manual rename table.
Rejected — high maintenance cost, low information return. Normalisation
rules handle 95 % of the noise mechanically.

### D6. NBNS Name Query: single-packet unicast, 100 ms budget

NBNS Name Query (RFC 1002) is a 50-byte UDP packet to port 137. The
target responds within ~10 ms on LAN with a Status Response carrying
the NetBIOS name(s).

Per sweep, the probe loop picks hosts that have:

- responded to ICMP this sweep (so we know they're alive),
- no Bonjour name,
- no reverse-DNS hostname.

For each, send NBNS Status Query, wait up to 100 ms for response,
parse the name table, store the WORKSTATION (`0x00`) name as
`LANHost.nbns_name`. Concurrency capped at 30 (same semaphore the
ping sweep uses). Total NBNS phase budget ≤ 1 s for /24.

Stdlib `socket` (UDP, IPv4) — no new deps.

### D7. SSDP / UPnP M-SEARCH: single multicast, parse + optional LOCATION fetch

Send one `M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n`
to 239.255.255.250:1900. Listen on the same socket for 3 s.

Each response is HTTP/1.1-style headers:
```
SERVER: Linux/3.10 UPnP/1.0 HiSenseTV/2024.01
LOCATION: http://192.168.1.5:1900/description.xml
USN: uuid:...::upnp:rootdevice
```

Parse `SERVER:` for a vendor + product token (regex
`([A-Z][\w.-]+)[\s/]([\d.]+)`). Optionally fetch `LOCATION:` (HTTP
GET, 500 ms timeout) and parse `<friendlyName>` + `<modelName>` from
the XML. Store as `LANHost.upnp_server` + `LANHost.upnp_friendly_name`
+ `LANHost.upnp_model`.

LOCATION-fetch is gated by a separate flag `DITING_LAN_UPNP_FETCH=0|1`
(default `1` for home/office/audit, `0` for public override — the
override only sends the M-SEARCH, doesn't follow up with TCP fetches).

### D8. Active mDNS query: one-shot `_services._dns-sd._meta._tcp.local`

The existing `BonjourPoller` only listens passively. Add a method
`BonjourPoller.send_meta_query()` that sends a single mDNS query for
the meta-service record `_services._dns-sd._meta._tcp.local` (RFC 6763
§9). Most Apple devices respond with their full service list within
~500 ms.

Called once per sweep when active probing is on. Existing passive
listener captures the responses through the normal path — no parser
duplication.

### D9. TTL fingerprint extracted from ping output

macOS `ping -c 1` stdout includes `ttl=N`. Existing `_PING_RTT_RE`
regex captures the time; add `_PING_TTL_RE = re.compile(r"ttl=(\d+)")`.

Round to nearest "common base" (64 / 128 / 255) and store as
`LANHost.ttl_class` (`"unix"` / `"windows"` / `"router"` / `None`).
The raw TTL value also kept on `LANHost.ttl` for the detail modal.

Same `_ping_one` function, same packet — zero additional traffic.

### D10. Device-class inference rules table

`src/diting/lan_classify.py` (new) — pure function
`classify(host: LANHost) -> str | None` consuming the augmented
`LANHost`. Rules table (excerpt):

```python
RULES = [
    # (predicate, class)
    (lambda h: h.bonjour_services and "AirPrint" in h.bonjour_services, "printer"),
    (lambda h: h.bonjour_services and "AirPlay" in h.bonjour_services
              and "Apple TV" in (h.upnp_friendly_name or ""), "tv"),
    (lambda h: h.upnp_server and "SmartTV" in h.upnp_server.lower(), "tv"),
    (lambda h: h.vendor_raw and any(t in h.vendor_raw.lower()
              for t in ("hikvision", "dahua", "axis communications")), "camera"),
    (lambda h: h.bonjour_services and "_companion-link._tcp" in str(h.bonjour_services), "phone"),
    (lambda h: h.vendor_raw and "TP-LINK" in h.vendor_raw.upper(), "router"),
    (lambda h: h.is_gateway, "router"),
    # ... ~30 rules total
    (lambda h: h.ttl_class == "windows", "desktop"),  # weak fallback
]
```

First match wins. Return None when no rule fires (row shows blank
class).

Classes: `phone | laptop | desktop | tv | camera | smart-home | printer | nas | gaming | speaker | router`.

**Class vocabulary rationale (from Fing UX reference, see D14):** the
`iot` class from the original draft was too coarse — Fing's data
shows that on CN home networks IP cameras (`hikvision` / `dahua` /
`tapo` / `imou`) and smart-home hubs (`tuya` / `xiaomi` / `aqara`)
co-exist in large numbers and have very different security
implications. `camera` is broken out as its own class because
"how many cameras are silently on my Wi-Fi" is a top concern;
`smart-home` replaces `iot` so the label reads as a domain rather
than an opaque acronym.

### D11. `[new]` chip on rows new today

When `(now - host.first_seen) < 24 h`, the LAN row prepends a
`[new]` chip in the same style as `[home]` / `[paused]`. Detail
modal also shows "first seen X minutes ago" in bold.

The "today" window is 24 h, not calendar day — calendar day creates
edge-case confusion at midnight.

### D12. JSONL event for consent

New event type `LANActiveProbeConsentedEvent`:

```python
@dataclass(frozen=True, slots=True)
class LANActiveProbeConsentedEvent:
    timestamp: datetime
    scene: str           # at-time scene name
    ssid: str | None     # connected network
    sweep_dir_packets: int  # how many NBNS + UPnP + mDNS were sent
    user_pressed: bool   # always True for this event (event exists = user confirmed)
```

Emitted via the existing `EventLogger.append()` path. Lands in JSONL
as one line, indexed under `lan_active_probe_consented` type.

### D13. UI surface — class column first, no layout disruption

`_COL_LAN_CLASS = 8` cells, inserted as the **first** data column —
to the left of vendor. Existing vendor / name / IP / MAC / age
columns retain their widths and order. New chip prefix adds
`[new]  ` to rows that qualify.

Final row layout (left → right):

```
[new]  class    vendor              name                    IP               MAC                last seen
```

Putting class first follows the Fing UX reference (D14) — Type is
the column users scan with first, more than vendor. A H3C OUI can
be a router, an AP, a switch, or an IoT bridge; the class column
disambiguates faster than vendor.

Detail modal gets two new sections plus a `Class:` and `Model:`
line in the Identity section:

- Identity section gains `Class:` (from `device_class`) and
  `Model:` (preferring `upnp_model`, falling back to the
  parenthesised "(year)" / "(generation)" portion of
  `upnp_friendly_name` when no explicit model field).
- New `Active discovery` section consolidates NBNS name, UPnP
  server header, UPnP friendly name, and mDNS-meta extras.

### D14. Fing UX reference

Fing Desktop (4.0) was reviewed as a UX benchmark on 2026-05-23.
Adopted patterns:

- **Type-first column ordering.** Fing's leftmost data column is
  Type (Router / IP Camera / NAS / Laptop / etc.). Adopted as D13
  above — diting's class column moves to the leftmost data position.
- **Cross-protocol identification (NBNS + UPnP + mDNS).** Fing
  surfaces Hikvision DS Series for a /36 IoT camera that has no
  Bonjour publication; this is the NBNS+UPnP composite path D6
  / D7 already encode. Adopted as-is.
- **Class vocabulary granularity.** Fing's `IP Camera` /
  `Smart Device` / `Voice Control` taxonomy informed the
  D10 vocabulary split (separate `camera` class, `smart-home`
  replaces `iot`).
- **Model in detail view.** Fing's Model column (e.g.
  `Apple MacBook Pro M4 Pro (16") (2024)`) is the single most
  user-facing identification string. Detail modal gains a `Model:`
  row sourced from UPnP `modelName` + `friendlyName`.

Explicitly NOT adopted from Fing:

- Type icons (PNG glyphs) — TUI single-cell column can't host them
  legibly; would force a non-portable Unicode glyph set.
- Sidebar nav (Overview / Devices / People / Timeline / Internet /
  Setup / Security) — diting uses `n` to cycle between four panels,
  the established TUI idiom.
- "People" association — privacy / maintenance burden too high
  for the value.
- Active TCP probing / port-scan-style "Security" pane — conflicts
  with the lan-inventory ICMP-only / consented-active-probe posture.
- Right-side filter dropdowns (Status / Type / Brand) — `/`-search
  and `s` sort cover the same need with less screen budget.
- Status pill column ("Online") — `last seen` already conveys
  reachability; a separate column would duplicate.

## Risks / Trade-offs

- **Risk: NBNS / SSDP probes trigger corporate IDS in non-public
  scenes.** → Mitigation: env override `DITING_LAN_PROBE=0` documented
  in `--help` and explicitly mentioned in `scenes` spec change. Office
  users on high-sensitivity networks can disable globally.
- **Risk: SSDP M-SEARCH flooding subnets.** → Mitigation: rate-limit to
  one M-SEARCH per sweep interval (default 60 s). Add a min-interval
  guard so even forced sweeps cannot M-SEARCH faster than once per
  10 s.
- **Risk: UPnP LOCATION fetch hits an attacker-controlled server.** →
  Mitigation: LOCATION fetch capped at 4 KB response, 500 ms timeout,
  parsed with stdlib `xml.etree.ElementTree` in defusedxml-equivalent
  safe mode (no external entity resolution).
- **Risk: Public-scene override modal becomes a habit.** → Mitigation:
  2-second cooldown on confirm key, re-confirm required every time,
  no "remember my choice" option. The JSONL event makes habituation
  visible in post-hoc replay.
- **Risk: Multi-tier OUI lookup misses MA-M / MA-S because the registry
  doesn't auto-classify.** → Mitigation: `refresh_ouis.py` downloads
  the IEEE CSV which has an explicit registry column (`MA-L`/`MA-M`/`MA-S`);
  partition into three JSONs by that column.
- **Risk: Vendor normalization corrupts a name a user recognises.** →
  Mitigation: preserve `vendor_raw` and surface it in the detail modal.
  Normalisation only affects the row column, not the canonical record.
- **Risk: Device-class rules misclassify edge devices.** → Mitigation:
  class is presentational — incorrect class never affects events,
  analyzer reports, or JSONL data. Worst case: a row shows the wrong
  one-word label. User can disregard.
- **Trade-off: NBNS / UPnP / mDNS active phase adds ~2 s to each sweep
  on home/office/audit.** Default sweep interval stays 60 s so the
  user perceives no slowdown. Audit users wanting faster feedback can
  set `DITING_LAN_INVENTORY_INTERVAL=15`.
- **Trade-off: New OUI files add ~3 MB to the bundle (MA-M ≈ 1 MB,
  MA-S ≈ 2 MB).** Acceptable — `diting` total wheel is currently small;
  3 MB on disk for 90% improvement on small-vendor identification is a
  good ratio.

## Migration Plan

1. Phase 1 (passive, no wire changes): OUI multi-tier + vendor
   normalization land first. No user-visible behaviour change beyond
   "rows now show vendor names for more devices". Safe to ship as a
   point release if we wanted to (we won't — bundled here).
2. Phase 2 (active layer): NBNS / UPnP / active-mDNS go in behind the
   `lan_active_probe` scene knob. Default ON for home/office/audit;
   default OFF for public. Public-scene override key + modal landed in
   the same phase so the escape hatch ships when the gating ships.
3. Phase 3 (heuristics): TTL fingerprint + device class. Pure
   read-side classifier consuming Phase 1+2 fields.
4. Phase 4 (UX): `[new]` chip + class column + detail-modal sections.

Single OpenSpec change, single PR (or split if PR diff exceeds review
budget; phases gate within `tasks.md`). No feature flag required for
end users beyond `DITING_LAN_PROBE`.

Rollback: revert the change PR. The OUI data files can stay in `data/`
without harm if the lookup code regresses — old MA-L lookup ignores
the extra dicts.

## Open Questions

- Should the LAN detail modal section be called `Active discovery` or
  `Probe results`? Internal terminology vs user-facing. Probably
  `Active discovery` for the visible label and `probe` only in CLI /
  env / event names.
- Should the `[probing]` subtitle chip animate (dots) or stay static?
  Probably static for terminal-friendliness; animation can churn the
  Rich render tree.
- Public-scene override: should the confirm modal also block the
  display until probe results return, or fire-and-forget and let the
  panel update normally? Lean toward fire-and-forget — keeping the
  modal open while a 5 s probe window runs feels heavy.

## Deferred — shared host registry (revisit post-v1.7.0)

This change keeps the LAN ↔ Bonjour enrichment **pairwise**: each
side maintains its own `_state` map and the other side walks
through to enrich at render / sweep time. That shipped as v1.7.0:

- `lan.py:_build_bonjour_index` pulls Bonjour name / services /
  `model=` TXT into `LANHost`.
- `tui.py:_bonjour_borrow_vendor` + `BonjourDetailScreen._section_lan_cross_ref`
  pull LAN-side MAC / OUI vendor / class / TTL / NBNS / UPnP into
  the Bonjour render path.

This is fine for two sources but won't scale once a third lands
(BLE-via-RPA correlation, the deferred `lan.yaml` manual naming
layer, the edge-hardware sidecar from `project-edge-hardware-future`).

The architectural move — promote `{ip, mac} → HostRecord` into a
shared `host_registry` that both pollers update and both panels
read — is recorded in the `project-shared-host-registry` memory
note. Pick up when a third source needs to join, or when the
`lan.yaml` manual-naming feature ships.
