# Surface "relay unreachable" in the companion chip

## Why

A real session on a corporate network showed `companion: 49 待发` climbing
steadily. The cause was invisible: every 3-second flush was failing (the
network blocks the relay endpoint), so envelopes only ever entered the queue.
The chip renders the symptom (queued count) but never the diagnosis — the
user watches a number grow without knowing whether the phone is slow, the
relay is down, or their own network is blocking egress.

The `companion-bridge` spec already requires the surface to report "whether
the relay is currently reachable or events are queued" — the chip implements
the queued half only.

## What Changes

- `RelayClient` tracks consecutive fully-failed flushes: a `flush()` that
  attempts delivery and sends nothing increments the counter; any successful
  send resets it. Exposed as `consecutive_failures`.
- `subtitle_chip` appends a `· relay unreachable` annotation to the queued
  variants once the counter reaches a small threshold (3 — about 9 s of
  failures at the 3 s flush interval), so a transient blip does not flash
  the warning but a sustained outage names itself.
- ZH catalog entries for the new chip strings.

Threshold rationale: the chip is recomputed after every flush, so recovery
clears the annotation on the first successful send.

## Impact

- Affected specs: `companion-bridge` (the discoverable-surface requirement
  gains the chip-level unreachable scenario).
- Affected code: `src/diting/companion/relay_client.py` (failure counter),
  `src/diting/companion/runtime.py` (`subtitle_chip`), `src/diting/i18n.py`.
- No wire/protocol change, no new config. The queue/flush semantics are
  untouched — this is presentation of already-tracked state.
