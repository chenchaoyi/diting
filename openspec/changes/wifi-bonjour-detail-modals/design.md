## Context

The BLE panel was the first interactive list in the diting TUI. Its
detail modal landed in v0.7.x and the keyboard/mouse contract was
hardened in subsequent audits:

- Selection state lives on the App (`_ble_selected_id: str | None`),
  keyed by stable peripheral identifier, not row index.
- Bindings `up`/`down`/`i`/`enter` are registered priority=True so
  they fire before `VerticalScroll`'s scroll handler — but each
  action no-ops when the active view isn't BLE, so the same physical
  key can mean "navigate the list" in BLE view and "do nothing"
  (i.e. let other handlers see it) elsewhere.
- Mouse click on a row both selects and opens the modal in one
  gesture. The `_y_to_id: list[str | None]` map on the panel is
  rebuilt every render so coordinate-to-identifier translation stays
  accurate after sort / churn.

The Wi-Fi and Bonjour panels render to the same third panel slot but
have never been interactive. They render rows from `ScanResult` and
`BonjourDevice` respectively; both dataclasses already carry ~3×
more fields than the list view exposes.

This change does not invent anything new — it generalises the BLE
pattern across both panels.

## Goals / Non-Goals

**Goals:**

- Same gesture across all three panels: `up`/`down` move selection;
  `i` or `Enter` opens a panel-specific detail modal; mouse click on
  a data row selects-and-inspects in one gesture; `Esc`/`i`/`q`
  closes.
- Modal renders every field the source dataclass carries, omitting
  sections whose data is absent so empty headers don't clutter.
- Selection is stable across re-sort + churn (keyed by identifier);
  selected target leaving the snapshot clears selection rather than
  silently jumping to a different row.
- Zero new dependencies, zero new helper schema fields. Punt
  per-BSSID RSSI history to a follow-up.

**Non-Goals:**

- New data collection. The modals render existing fields; they do
  not introduce active probing, deeper Wi-Fi telemetry, or
  long-running per-BSSID RSSI history.
- A unified "DetailScreen" base class. The three modals share a
  visual pattern but have different sections, different field
  semantics, and different test surfaces. A shared base would couple
  three independent capabilities; we'd lose the ability to evolve
  one without touching the others. We accept some structural
  duplication in exchange for capability isolation.
- Inline editing (e.g. renaming an AP, tagging a Bonjour device).
  All three modals stay read-only this change.

## Decisions

### Two new capabilities, not one

`wifi-detail-modal` and `bonjour-detail-modal` are independent specs,
parallel to the existing `ble-detail-modal`. **Rejected alternative:**
a single `detail-modals` spec covering all three views. Reasons:

- BLE's spec is already shipped and has a well-tested set of
  scenarios that wouldn't translate cleanly to Wi-Fi (no `tx_power`,
  no decoder framework) or Bonjour (no RSSI, no connected/advertising
  split).
- Per-capability specs let future BLE-only or Wi-Fi-only changes
  modify just that capability's spec without ripple. The cost is a
  small amount of structural parallelism in the spec layouts, which
  is the kind of repetition that's good for readability.

`tui-shell` gets one new cross-cutting Requirement: "all three
panels share the same row-select gesture contract". The specifics
(which sections, which fields) stay in the per-panel capability.

### Selection key choice

| Panel | Key | Why |
|---|---|---|
| BLE | `device.identifier` | Already shipped; stable across re-sort. |
| Wi-Fi | `bssid` (lowercase, no separators), fallback `f"{ssid}#{channel}"` | BSSID is the unique key when CoreWLAN exposes it; when it's redacted (TCC denied), a `(ssid, channel)` synthetic key preserves stable selection within a single session. Hidden SSIDs (broadcast empty) → `f"#{channel}"`. |
| Bonjour | `f"{name}.{service_type}"` | A given service type can have multiple instances; the FQDN-style key is unique on the local link. |

**Rejected alternative for Wi-Fi:** make BSSID the only key and
disable selection when BSSID is None. Rejected because most home /
café Macs running diting *without* Location Services granted (a
common state for new users) would never see a selectable list — and
that's exactly the audience who'd benefit most from a "what does
this row actually mean?" modal.

### Mouse + keyboard sharing the same action

Both inputs route through `_wifi_set_selected(key, *, inspect=False)`
on the App (mirror of `_ble_set_selected`). The keyboard path calls
it with `inspect=False` on arrow keys and `inspect=True` on
`i`/`Enter`; the mouse path always passes `inspect=True`. Single
action, two surface bindings — keeps "what happens when I select
something" in one place.

### Modal width: 100 cells, matching BLE

`WifiDetailScreen` and `BonjourDetailScreen` use the same `width: 100;
height: 90%;` modal box as `BLEDetailScreen`. **Rejected
alternative:** wider Wi-Fi modal to fit a roam-history sparkline.
Rejected because per-BSSID history is explicitly out of scope this
change — a wider modal would announce a feature we're not shipping.

### Body rendering: prose-style `Text`, not a `DataTable`

Both modals use the same `Text`-based section/field layout as BLE
(label-aligned columns via `pad_cells`). **Rejected alternative:**
Textual `DataTable` for TXT records. Rejected because a `DataTable`
inside a `ModalScreen` introduces focus / scroll handling we'd have
to special-case (Esc should still close even if the DataTable's
focused); a 2-column `Text` block scrolls correctly inside the
existing `VerticalScroll` wrapper.

### TXT records: render all of them, hex-fold ugly values

Bonjour TXT records are sometimes prose (`md=Apple TV`, `am=AppleTV5,3`),
sometimes opaque base64-looking blobs (`pk=...90 chars...`). The
modal renders every key, but values longer than 60 chars get a
"`<256-byte payload>`" placeholder + a one-line hex preview. This
keeps the layout sane on AirPlay receivers (TXT can run 30+ keys)
without dropping data.

### `up`/`down` priority + view-scoped no-op

Same trick as BLE: register the binding priority=True on the App
(so `VerticalScroll` doesn't eat it), but each `action_*_select_next`
checks `self._current_view` and returns early if it isn't the
matching panel. This means the user pressing ↓ in Wi-Fi view scrolls
the (mostly fixed-height) ConnectionPanel + EnvironmentPanel
*content* by triggering Textual's default arrow-key behaviour — no
regression.

### Live navigation inside the modal — sync hook on the App, not Bindings on the modal

The modal must walk the underlying list when the user presses
`up` / `down` while the modal is open. The obvious implementation —
adding `up` / `down` bindings to each modal class — does **not**
work because the App already binds `up` / `down` priority=True for
the list view. With both registered, Textual fires the App's
binding (which advances the selection) and the modal's binding
never runs (so the modal body doesn't re-render).

The chosen design: keep arrow bindings only at the App level, and
have each detail modal expose a public `sync_to_app_selection()`
method. After the App's `action_select_prev` / `action_select_next`
runs, it walks `screen_stack` looking for any screen with that
method and calls it. Each modal's implementation re-fetches the
current selection (via `_wifi_lookup` / `_bonjour_lookup` /
`_ble_lookup`), updates its own state (and the RSSI history in the
BLE case), and re-renders the body.

**Rejected alternative:** modal-level `up`/`down` bindings with
priority=True. Doesn't work — App's priority binding wins.

**Rejected alternative:** event bus / reactive observer. Overkill
for one-modal-at-a-time UX; a direct method call on whatever's on
the screen stack is one short helper.

### No CHANGELOG bullets

Per the v0.9.0 policy switch, the per-PR CHANGELOG entry is
replaced by the proposal's `## What Changes`. The release that
bundles this change will produce the user-facing release note.

## Risks / Trade-offs

- **Wi-Fi selection with redacted BSSID is fragile.** When
  CoreWLAN cannot read BSSIDs (Location Services denied), the
  synthetic `(ssid, channel)` key collides for an SSID broadcast
  on multiple channels (e.g. a roaming-friendly mesh on 2.4 +
  5 GHz with the same SSID). → Mitigation: collision keeps the
  highlight on whichever row happens to be first in sort order;
  the modal still opens correctly because we re-resolve the key
  against the current snapshot at modal-open time and pick the
  best-matching `ScanResult`. Document the limitation in the
  spec's Scenario block so reviewers can verify it.
- **Bonjour TXT keys can carry user-identifying data.** TXT records
  for AirPlay receivers include `deviceid` (MAC), iCloud account
  hashes, HomeKit pairing identifiers. → Mitigation: same privacy
  posture as the rest of diting — TUI shows what the user can see
  themselves on a packet sniff, runs entirely local, no telemetry.
  No new exposure surface here; just document in the spec that the
  modal is read-only and renders verbatim.
- **Spec parallelism vs spec duplication.** Three near-identical
  specs invite cargo-culting when a fourth panel gets added (say,
  Thread / Matter). → Mitigation: the `tui-shell` cross-cutting
  Requirement is the load-bearing contract. The three per-capability
  specs are the *layout* details; they're allowed to diverge.

## Migration Plan

No data migration. The change is purely additive in the TUI layer:
existing key bindings (`n`, `m`, `h`, `b`, `r`, `p`, `q`) keep their
current behaviour; `up`/`down`/`i`/`enter` were already bound for the
BLE view and now also act in Wi-Fi and Bonjour views; the modal
classes are new files attached to existing panels.

Rollback: revert the feature commit. No state lives outside the TUI
process.
