# design — fix-ble-left-dedup

## The state machine

Conceptually each identifier passes through three states per session:

```
INIT ──(first advert in _devices)──> PRESENT
PRESENT ──(TTL eviction)──> DEPARTED
DEPARTED ──(advert re-arrives)──> DEPARTED  (silent)
DEPARTED ──(re-eviction)──> DEPARTED        (silent)
```

`seen` fires on INIT → PRESENT. `left` fires on PRESENT →
DEPARTED. DEPARTED is terminal for the session — the identifier
emits nothing further regardless of how many times it flaps
through `_devices`.

This matches the contract the user picked in scoping: "at most
one left per seen". Subsequent flapping is signal noise, not new
information.

## Why not "treat re-appearance as a new seen"

The rejected alternative was to clear `_seen_identifiers[ident]`
on `left` emission, so that a returning advert would fire a
fresh `seen` and an eventual fresh `left`. That preserves a
"record everything" feel — every transition observed gets a
record — but in practice it amplifies edge-of-range noise:

- The observed identifier `7c49b077` would have emitted ~229
  seen + 229 left pairs (≈ 460 events) instead of 1 + 1.
- Total session would have produced ~95k events instead of ~25k.
- A "high-RSSI new device just walked in" signal would be
  drowned in flap pairs from identifiers we already know
  about.

The DEPARTED-as-terminal choice keeps the spec's "no debounce"
promise honest for the first observation (which is the
information-carrying transition) while suppressing repeated
near-zero-information flap pairs.

## Implementation

```python
# new field in __init__, alongside _seen_identifiers
self._departed_identifiers: set[str] = set()
```

In `_detect_transitions`, the existing newcomer loop already
guards seen emission on `_seen_identifiers`. The expire loop
adds a single check:

```python
for ident, dev in before.items():
    if ident in self._devices:
        continue
    if ident in self._departed_identifiers:
        continue                  # ← new gate
    self._pending_transitions.append(BLEDeviceLeftEvent(...))
    self._departed_identifiers.add(ident)   # ← new bookkeeping
```

Two new set operations per tick (membership check + add). Cost
is O(1) per evicted ident.

## Edge case: a flapping device that the helper genuinely re-introduces

If a user's iPhone leaves the apartment for an hour and comes
back, its CoreBluetooth identifier is **already different** —
Apple rotates the identifier alongside the random MAC. So the
returning device looks like a brand-new identifier to the poller
and fires a fresh seen. We do not need to model "long absence →
treat as new identifier" — the OS already does it for us.

If a device legitimately stays in range for the whole session
but its adverts briefly stop reaching macOS (radio interference,
the user walked behind concrete), TTL evicts it once, we emit
one `left`, and then the device's adverts come back. With the
fix, no `left` re-fires; the device stays in `_devices` (its
`last_seen` is refreshed by new adverts) and the panel renders
it normally. The events log records exactly one seen-left pair
for the session, which under-reports continuous presence but
is consistent with our "ble_device_left = end of session, not
end of contact" semantics.

## What we do NOT change

- The `seen` gate (one seen per identifier per session). Already
  correct.
- `_seen_identifiers` semantics — still "ever been seen". Not
  cleared on left.
- TTL value (`_ttl_s`) — not the cause.
- The connected-peripheral path. `_connected` left-events are
  not emitted today (only seen). That's a separate gap, out of
  scope here.
- The events panel / EventsScreen filter cycle / JSONL schema —
  the fix only reduces the volume of `ble_device_left` records;
  the record shape is unchanged.
- The analyzer. It does not look at left-event counts directly
  (top contributors ranks by `seen` count for BLE), so this
  fix mostly affects file size and the per-network ranking
  (which currently double-counts flapping idents).
