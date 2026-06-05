# Expand the event ring to 1000 events

## Why

The events browser (`m`) can only ever show the last 100 events — the
`EventRing` default capacity. On a real office floor a single hour of BLE /
LAN churn plus the at-launch census already blows past 100, so by the time
something interesting happens the context around it has rolled off. The
user asked for 1000.

## What Changes

`EventRing`'s default capacity goes from 100 to 1000. Nothing else moves:
the constructor arg stays, overflow semantics stay (oldest rolls off
silently), the events modal already scrolls the whole snapshot and the
bottom strip already renders only the leading entries.

Cost check: ~1000 dataclass events is trivial memory; the modal rebuilds
its body on open / filter change, which is a linear pass over the
snapshot — 1000 rows render fine inside the existing `VerticalScroll`.

## Impact

- Affected specs: `events` (the size-bound requirement: 100 → 1000).
- Affected code: `src/diting/events.py` (one default + docstring).
- Docs: README EN + ZH — three "last 100" mentions each become 1000.
- Tests: the overflow scenario was never actually covered — add it at the
  new default (1001st event drops the oldest) plus a custom-capacity case.
