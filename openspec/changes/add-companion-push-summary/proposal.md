# Add a cleartext event summary to the companion push

## Why

The companion push is currently a content-free doorbell: the phone shows
"New ble activity" and the user must open the app, pull, and decrypt to learn
what happened. In practice the notification is the surface that makes the
feature useful — a generic "activity" ping is ignorable. The event detail
diting forwards (a device name, an SSID it roamed to, a latency target) is the
same low-sensitivity data the app already shows on screen, so naming it in the
notification is a deliberate, accepted privacy trade-off for utility.

## What Changes

- **Relax the "content-free doorbell" rule.** The APNs payload MAY now carry a
  short, human-readable, single-line event summary in cleartext (e.g. "BLE
  nearby: Magic Keyboard", "Roamed to AX51-E", "192.168.1.42 joined"). The
  relay and APNs see this summary; the user opts into it by pairing.
- **Producer composes the summary** (`companion/push_summary.py`), localised via
  `t()` so it follows the desktop language, and sends it to the relay as a
  cleartext `push` sibling of the sealed envelope.
- **Relay forwards the summary** as the APNs alert body, stripping the `push`
  sibling before storing — only the encrypted envelope is persisted or returned
  to the consumer. Absent a summary it falls back to the coarse category text,
  so older producers keep working.
- **The full event is unchanged**: it still rides the E2E-encrypted envelope
  (`seal_event`) for the on-device timeline and report. No crypto is added or
  removed; the summary is a separate, intentionally-cleartext push field.

## Impact

- Affected specs: `companion-protocol` (APNs trigger requirement modified).
- Affected code: `src/diting/companion/push_summary.py` (new),
  `companion/sink.py`, `companion/relay_client.py`, `relay/src/index.js`,
  `relay/src/apns.js`, `src/diting/i18n.py` (EN+ZH summary templates).
- Backward-compatible: the `push` sibling is optional; the relay tolerates its
  absence and old producers POST plain envelopes as before.
