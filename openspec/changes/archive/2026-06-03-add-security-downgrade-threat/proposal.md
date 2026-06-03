# security_downgrade threat detection

## Why

Phase 3 shipped three threat detectors but deferred `security_downgrade` —
the payoff of an evil-twin / forced-disconnect: you reconnect to a
familiar-looking SSID, but on a *weaker* cipher (WPA2 → open), so traffic the
attacker now sees is unencrypted. It was deferred under the (mistaken) belief
it needed the connection cipher as a new wire field + a paired mobile change.
It does not: using the same desktop-local-field pattern as `familiarity` /
`salience`, the detector is **desktop-only** and its threat reaches the phone
for free over the v2 `insight` wire already built.

## What Changes

- **`link_state` (associated) carries the connection cipher** as a desktop-local
  `security` field — stamped by `emit_connection_update` from `conn.security`,
  added to `LOCAL_ONLY_FIELDS` so the companion sink strips it before sealing
  (it is not part of the `link_state` wire vocabulary) and the fixture generator
  excludes it. It stays in the JSONL log; the threat engine reads it off the
  observed payload.
- **A `security_downgrade` threat detector** in `ThreatEngine`: per SSID it
  tracks the *strongest* cipher seen this session (rank open < WEP < WPA < WPA2
  < WPA3); a later association to that SSID at a weaker cipher emits a
  `critical` `security_downgrade` insight `{ssid, was, now}`. First sighting
  sets the baseline (no fire); an unrankable cipher is skipped. Keys on the
  authoritative cipher, never trusting the SSID as identity.
- **Surfacing** rides the existing path: `[THREAT]` row + macOS notification,
  and — since it is an `insight` — it forwards over the v2 companion wire to the
  phone with no new wire field and no mobile round-trip.

## Impact

- Affected specs: `threats` (the `security_downgrade` detector), `events`
  (`link_state` carries desktop-local `security`), `companion-bridge`
  (`security` joins the local-only strip set).
- Affected code: `event_log.py` (stamp `security` on associated `link_state`),
  `protocol/events_schema.py` (`LOCAL_ONLY_FIELDS` += `security`), `threats.py`
  (`_security_rank` + the detector), `insights.py` `format_insight_summary` +
  `i18n.py` (EN↔ZH one-liner). No protocol-version change; fixtures unaffected
  (the generator's `link_state` fixture uses `emit_link_state`, which carries no
  `security`).
- **Scope limit:** detection fires on (re)association (`link_state` associated),
  which is where a forced downgrade shows; a seamless same-session roam carries
  no cipher and is not covered (honest limitation). Desktop-only; no new wire
  field.
