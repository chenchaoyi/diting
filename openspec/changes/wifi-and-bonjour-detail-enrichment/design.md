## Context

The Wi-Fi and Bonjour detail modals (`WifiDetailScreen` at
`src/diting/tui.py:3670`, `BonjourDetailScreen` at
`src/diting/tui.py:3897`) render their underlying dataclass's
fields. Both share the same shape: title bar with the row's
identifier, a vertical scroll of labelled sections, a close-keys
footer, live `up`/`down` navigation.

Three observations motivate this change:

1. **The TUI already collects more than each modal shows.** The
   diagnostics panel renders a Roam score, σ band, stability
   label, and roam events; none of those signals reach the
   modal. The detail modal's job is "tell me more about this
   row," and it's under-delivering against the data already in
   memory.
2. **Bonjour rows are service-instance-keyed**, but users think
   in terms of devices. A user's own Mac shows up as 3 separate
   rows (AirPlay, AirPlay audio, Companion). Opening detail on
   any one of them currently hides the fact that the host has
   other services on the same announcement.
3. **The three scan surfaces (Wi-Fi, BLE, mDNS) are isolated**
   from each other in the UI. The product tagline ("your Mac
   hears more than it tells you") is at its strongest when the
   same physical device is identified across surfaces — but
   today the user has to do that correlation in their head.

## Goals / Non-Goals

**Goals:**
- Surface σ / RSSI history, sibling radios, roam history,
  recommendation in the Wi-Fi detail modal.
- Surface other services from the same host, decoded TXT keys,
  vendor-resolution trace in the Bonjour detail modal.
- Take a first cut at cross-surface correlation between Bonjour
  and BLE / Wi-Fi peer state, accepting that the heuristics are
  approximate.

**Non-Goals:**
- Re-keying the Bonjour panel from service-instances to hosts.
  Service-instance-keyed list + a host-aware modal is the
  smaller, less risky shape.
- A device-identity model that holds across sessions. Whatever
  correlation we do is in-memory only; restart resets it.
- Adding new collection paths (no new helper schema, no new
  poller). Every signal here already lives in diting's process
  memory.
- Implementing all 8 additions atomically. Tasks are ordered
  so the highest-leverage sections land first; cross-surface
  correlation is the last and most deferrable.

## Decisions

### D1 — σ + RSSI history pulls from `EnvironmentMonitor`, not a new ring

`EnvironmentMonitor` already maintains a per-BSSID RSSI history
ring (used to compute the σ baseline and STIR events). The Wi-Fi
detail modal SHALL borrow read-access to that ring rather than
adding its own collection. The σ-band classification (`stable` /
`active` / `noisy`) lives in `src/diting/environment.py` and is
already i18n-translated; the modal calls into the same helper the
diagnostics panel uses.

**Sparkline width** — fit to `_COL_BLE_RSSI_HISTORY` style: 8
glyphs of unicode block characters spanning the per-BSSID
ring's most recent N seconds. Reuse `_render_sparkline` if it
exists; otherwise write a small util in `tui.py` next to the BLE
sparkline path.

### D2 — Sibling-AP grouping uses `NetworkInventory.group_by_ap`

The diagnostics panel already groups BSSIDs by physical AP for
its top-bar layout. The same grouping function is what the
modal's "Same physical AP" section calls. No new logic — the
modal filters the latest scan snapshot to BSSIDs sharing the
selected row's AP key, sorts by RSSI desc, renders.

Edge case: when `aps.yaml` is absent and the inventory falls
back to the auto-cluster heuristic (last byte ignored for
mgmt-MAC matching), a row whose cluster is itself singleton
SHALL omit the section rather than render "Same physical AP:
(only this)."

### D3 — Roam history reads the `EventRing`, no new state

The App's `EventRing` already buffers the last N events of every
type. Roam-history-for-this-BSSID is `[e for e in
event_ring.iter() if isinstance(e, RoamEvent) and
this_bssid in (e.from_bssid, e.to_bssid)]`. Cap at the most
recent 10. Newest first.

### D4 — "Recommendation" extracts the `clearly-better` rule

The diagnostics panel's `Roam score` line already runs a
"clearly-better same-SSID candidate" computation. Today this is
inline in the panel rendering. Refactor into a pure
`recommend_roam(scan, current_bssid, candidates) -> str | None`
function so the modal calls the same logic. The rule itself
SHALL NOT change in this proposal — only its locus.

### D5 — TXT decoder framework: registry, abstain-friendly

A small `src/diting/mdns_txt_decoders.py` (or under
`src/diting/decoders/mdns/` — TBD by the apply step) hosts
per-key decoders following the BLE decoder convention: each
decoder is `@register("<key-name>")`-decorated, takes the raw
TXT value, returns `(label, value)` or `None`. The TXT section's
renderer iterates decoders, harvests their tuples, then renders
"Decoded TXT" first followed by the raw TXT table for keys not
handled.

Initial decoder set (a starting kit; not exhaustive):

| Key | Source service | Decoded meaning |
|---|---|---|
| `model` | AirPlay, RAOP, _device-info | Apple model identifier (`MacBookPro18,1` → `MacBook Pro (M1 Pro, 2021)`) |
| `osxvers` | AirPlay | macOS major version |
| `srcvers` | AirPlay, Companion | source-firmware version |
| `features` | AirPlay | 64-bit bitmask of capabilities; decode top bits |
| `ft` | RAOP | similar bitmask (different mapping) |
| `rpFl` | Companion-link | flags |
| `deviceid` | AirPlay, RAOP | MAC address → OUI lookup |

Each decoder MUST tolerate malformed input (key absent, wrong
type, oversize) and return `None` rather than raise. The TXT
section renders both decoded and raw — never collapses raw away,
because raw is the source of truth.

### D6 — Vendor-resolution trace recorded at resolution time

`BonjourPoller`'s vendor resolution chain (the 5-step
`_resolve_vendor`) SHALL record which step won as a new
`vendor_trace: str | None` field on `BonjourDevice`. Frozen
dataclass, optional, defaults to `None` for backwards
compatibility. Schema fence: spec for `mdns-scanning` already
declares the field list — this proposal's spec delta extends
that list and the new field name.

The modal's Identity section appends ` · via <trace>` to the
vendor row when the trace is non-`None`. Style matches the
existing `(associated)` annotation.

### D7 — Cross-surface correlation: identity-mapping heuristics

The hardest piece. Three correlation rules, applied in this
order:

1. **Address match (Bonjour ↔ Wi-Fi peer)**: if the Bonjour host's
   announced IPv4 matches `Connection.local_ip` or the BSSID's
   own subnet's broadcast peer list, render `local Mac` (you)
   or `also on Wi-Fi as <SSID/BSSID>`.
2. **MAC match via `deviceid` TXT (Bonjour ↔ BLE)**: when the
   Bonjour host's `deviceid` TXT field is a MAC and that MAC
   appears in the BLE poller's snapshot (BLE peripherals
   sometimes advertise their MAC in manufacturer data), render
   `also on BLE as <category> · <RSSI>`.
3. **Hostname pattern (Bonjour ↔ BLE)**: if the Bonjour hostname
   matches an Apple `_NAME_PATTERN` (e.g.
   `Chaoyis-iPhone.local.`) AND a nearby BLE row carries the
   same Apple-Proximity hint, render the weaker form `likely
   the same device as BLE row <id>`.

Rules 1 and 2 are deterministic; rule 3 is probabilistic and
SHALL be flagged "likely" in its render so the user knows the
match isn't certain.

**Deferral path**: if rules 2 and 3 prove fiddly to implement
without false positives, the apply step MAY land rule 1 only
and defer 2 / 3 to a follow-up change. The proposal's spec
delta allows a graceful degraded section ("local Mac (this
host is you)" alone is still valuable).

### D8 — Modal constructor surface change

The two modals' `__init__` signatures grow:

- `WifiDetailScreen(*, scan, connection, inv,
  environment_monitor=None, event_ring=None,
  latest_scan=None)`. Defaults to `None` so existing callers
  (tests, the regression snapshot) keep working.
- `BonjourDetailScreen(*, device, latest_mdns=None,
  latest_ble=None, latest_connection=None)`. Same default-None
  pattern.

When a kwarg is `None`, the corresponding new section is
omitted entirely. The App always supplies real values, so the
omission only matters for old test fixtures.

## Risks / Trade-offs

- **[Risk]** Modal vertical height grows. Each new section adds
  3-8 lines. On a 50-row terminal opening a Wi-Fi detail with
  every section populated could exceed the modal height.
  → The existing scroll container handles this; we just have to
  not break overflow. Spec requires sections to omit when their
  data is absent, which limits the maximum case.

- **[Risk]** Cross-surface correlation false positives.
  → Mitigated by D7 ordering (deterministic rules first) and
  the "likely" hedge on rule 3. If false positives prove
  unmanageable, defer correlation entirely without blocking the
  rest of this change.

- **[Risk]** TXT decoders are a long tail.
  → Initial set is small (~7 keys). The registry pattern lets
  us add decoders incrementally without changing the spec.
  Decoders abstain on unknowns, so missing decoders never
  degrade behaviour.

- **[Risk]** Refactoring the `clearly-better` rule into a shared
  helper could regress the diagnostics panel's roam-score
  line.
  → Same-test-coverage: keep the existing roam-score tests
  green, add new tests against the extracted helper. Pure
  function, no state, easy to validate.

- **[Risk]** Decoder for Apple model strings (`MacBookPro18,1`)
  needs a non-trivial lookup table.
  → First decoder ships with a starter table covering common
  M-series models; unknowns fall through to displaying the
  raw identifier. Table grows over time, decoders never raise.

## Migration Plan

No data, no schema change for the helper bundle. The
`BonjourDevice.vendor_trace` field is additive (defaults None);
old serialised forms continue to load.

Rollout order (tasks order accordingly):
1. Wi-Fi: extract `clearly-better` helper, σ + RSSI history,
   sibling AP, roam history, recommendation
2. Bonjour: other services, vendor trace, TXT decoders
3. Cross-surface: rule 1 only first; rules 2 & 3 if budget

A merge can stop after step 1 or step 2 and still ship a
material improvement.

Rollback: `git revert` the PR. No data state, no spec breakage.
