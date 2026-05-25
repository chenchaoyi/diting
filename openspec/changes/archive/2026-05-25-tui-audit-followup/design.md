## Context

This change bundles three display-only follow-ups from the
2026-05-25 `/tui-audit` run. Findings live at
`/private/tmp/wfs-tui-audit-20260525-181001/findings.md` (iterations
1.1, 2.1, 3.1). None of the three fixes change a data model, a JSONL
contract, or a backend permission surface — they all sit in the
TUI render layer or at the boundary where helper output enters the
Python state machine. The change is intentionally small so it can ship
on top of v1.7.1 without coordinating with downstream consumers.

The relevant code today:

- `src/diting/lan.py:_read_arp_cache` returns
  `list[tuple[ip, mac, iface]]`. The MAC is captured by the regex
  `([0-9a-f:]+)` and lower-cased with `.lower()` — no octet
  normalisation. macOS `arp -an` strips leading zeros, so the field
  carries un-padded forms like `14:51:7e:71:5a:1`.
- `src/diting/tui.py` renders the BLE list rows via a formatter
  that consumes `BLEDevice.name` directly into the name column.
- `src/diting/tui.py`'s `EventsScreen` consumes `EventRing` events
  via `EventsPanel.append_event` and renders one row per event;
  there is no run-length compaction at the modal layer.

## Goals / Non-Goals

**Goals:**
- Stop the LAN detail modal from showing un-padded MACs that look like
  parser bugs.
- Stop the BLE list from reading rotating-identifier base64 strings as
  if they were human-readable device names, while keeping the raw
  value reachable for users who need to debug a specific device.
- Stop the events modal from being unreadable in dense BLE
  environments, without changing what gets written to JSONL or how
  external analyzers see the event stream.

**Non-Goals:**
- Re-architecting the BLE merger / dedup pipeline. The source-side
  per-identifier dedup in `ble.py:1458` is correct; we are only
  changing the modal's rendering.
- Adding new BLE manufacturer-data decoders (Huami / Polar / Telink).
  That is a separate proposal flagged in the audit findings file but
  out of scope here.
- Changing the LAN list column width or the events modal layout.
- Touching the JSONL log format. The `event-log` capability is
  explicitly unmodified.
- Internationalising the LAN MAC field (it is already locale-neutral).

## Decisions

### Fix 1: MAC normalisation at ingest, not at render

`_read_arp_cache` is the single boundary where `arp -an`'s leaking
zero-stripped MACs cross into the Python data model. Normalising
there means every downstream consumer — the LAN list column, the
detail modal, the JSONL transition event payloads, the merger keyed
by `mac.lower()` — receives the canonical form for free. The
alternative (normalising at each render site) was rejected because
it leaves the field in a non-canonical state inside the state machine
and risks future code paths writing the wrong form into JSONL.

Implementation: between the regex capture and the `_is_multicast_dest_mac`
check, run each octet through `f"{int(p, 16):02x}"` and rejoin with
`":"`. The transform is idempotent on already-padded inputs. No
hot path concern — `_read_arp_cache` runs once per sweep tick
(default 60 s).

### Fix 2: BLE name guard via heuristic, with raw value preserved in the detail modal

A name is treated as a rotating identifier when it satisfies a
high-precision predicate (no whitespace, 16+ chars, base64 / hex /
underscore / hyphen alphabet, not a known Apple-product prefix). The
predicate is deliberately conservative — it avoids false-positive
matches on legitimate names like `HW Watch GT` (whitespace) or `abc`
(too short) or `iPhone` (Apple prefix).

The raw value is preserved in two places:

1. **`BLEDevice.name` itself is unchanged.** The render-time
   transform produces the display string from a copy; the data class
   stays immutable and the merger / history / JSONL log all see the
   original value.
2. **The BLE detail modal gains a `Raw name:` row** in the Identity
   section. Users who need to investigate a specific device (does
   the helper see what I expect?) can still get at the helper-emitted
   string. The row is omitted when `name` is None or empty so we
   don't add a `Raw name: —` placeholder for every anonymous row.

The Apple-prefix allowlist is intentionally a fixed set of strings
rather than a regex — it documents the known-good shapes and is easy
to extend when Apple ships a new product line. Other vendor prefixes
(`HW`, `Mi`, `Amazfit`, …) are NOT in the allowlist because their
local-name shapes are mixed; the guard's `(rotating ID)` substitution
for Huami serials like `Z-GM0YXG6A` is intentional.

Alternative considered: per-vendor decoders that resolve
`Z-GM0YXG6A` to a friendly Amazfit model string. Rejected for this
proposal — it's the right long-term answer but would expand scope
substantially and is already noted in the audit findings as a future
decoder gap.

### Fix 3: Events modal grouping is render-only and consecutive-only

Grouping happens at the EventsScreen render path, not in `EventRing`
or `EventLogger`. The ring keeps the original event order; the JSONL
log keeps the original per-event lines. This preserves two
invariants:

- `diting analyze` and external `--log` consumers see the unchanged
  byte stream.
- The `event-log` capability's "JSONL keys SHALL be locale-stable
  English" requirement is not touched.

Grouping is *consecutive-only* (`group_by` semantics, not aggregate
counting). This was chosen over a global "count of (vendor, name)
pairs in the ring" because:

- It preserves the relative ordering of heterogeneous events. A
  user looking for a roam event sees roam in the right slot even
  when surrounded by BLE chatter.
- It does not require maintaining a secondary index keyed by
  `(vendor, name)` over the ring.
- It composes cleanly with the existing filter cycle: filter to a
  bucket first, then run consecutive grouping over the filtered list.

The grouped row format:

```
HH:MM:SS  [BLE]  device seen: <vendor>  ·  <name_label>  ×N  → HH:MM:SS
```

Where the leading timestamp is the earliest event in the group, `×N`
is the count, and the trailing arrow + timestamp is the most-recent
event in the group when `N ≥ 2`. The exact glyph (`×`) was chosen to
mirror the existing `(merged N)` badge used in the BLE list — the
user is already used to reading that idiom for "fold of identical
rows".

### Why all three in one bundled change

All three are display-only, all three were surfaced in the same
audit, none of them depend on each other. Splitting into three
changes would mean three proposal-design-spec-tasks-archive cycles
for what amounts to ~150 lines of code and one i18n key set per fix.
The bundled change is consistent with the user's stated preference
(memory: bundled PRs for refactors / cohesive cleanup) and keeps the
spec deltas readable as a single audit follow-up.

## Risks / Trade-offs

[Risk] **MAC normalisation could surprise external tools that consume
diting's JSONL log and expect macOS's un-padded form.** → Mitigation:
the un-padded form is not a stable interface — `arp -an`'s exact
output varies across macOS versions and is documented as
human-readable, not machine-parseable. Zero-padded colon-separated
MAC is the canonical IEEE 802 representation and what every other
tool emits. No known external consumer depends on the un-padded form.

[Risk] **Rotating-ID predicate false positives on a legitimate device
name.** → Mitigation: the predicate requires ≥16 chars, no
whitespace, no punctuation other than `+/=_-`, and no Apple-product
prefix. The combination is narrow enough that real device names
(`ccy's iPhone`, `Office Printer`, `Living Room TV`) all fail it.
The detail modal still surfaces the raw value so any false positive
is recoverable without code change. If a false positive does surface,
the fix is one-line: add a prefix to the allowlist.

[Risk] **Events modal grouping hides the timestamp distribution
within a group.** → Mitigation: the trailing `→ HH:MM:SS` shows the
range explicitly. Users who need per-event timestamps can press the
right-arrow filter key to widen to `all` (which still groups) or open
the underlying JSONL log. The audit found that the dense ungrouped
view was actively *less* useful than a grouped view because the user
couldn't see the non-BLE events at all.

[Risk] **Grouping interacts surprisingly with the filter cycle.** →
Mitigation: the spec is explicit that filtering applies *before*
grouping. The test plan exercises filter-then-group and group-after-
filter-change to lock the order in.

## Migration Plan

No migration required. All three changes are additive to the render
path or to a normalised-form contract that downstream consumers
either already tolerate (MAC) or do not depend on (BLE name shape,
events modal layout). The bundled change ships as a patch release
on top of v1.7.1.

Rollback: revert the change set. No state to migrate; no JSONL to
re-format.

## Open Questions

None at proposal time.
