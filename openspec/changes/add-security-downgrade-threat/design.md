# Design — security_downgrade

## Why desktop-local, no wire field

The detector needs the connection cipher available to the desktop `ThreatEngine`
(which observes wire payloads via the logger tap). Rather than add `security` to
the `link_state` *wire* vocabulary — which would force a paired mobile re-vendor
(strict `validate_event` rejects unknown keys) — `security` is stamped as a
**desktop-local** field, exactly like `familiarity` / `salience`:

- `emit_connection_update` adds `payload["security"] = conn.security` on the
  associated `link_state`.
- `security` joins `LOCAL_ONLY_FIELDS`, so the companion sink strips it before
  sealing and the fixture generator excludes it. It is NOT in the `link_state`
  `EVENT_SPEC`, so a strict consumer never sees it.
- The threat engine reads it off the observed payload (observers get the full
  pre-strip dict); the resulting `security_downgrade` is an `insight`, which
  already crosses the v2 wire. So the *threat* reaches the phone with zero new
  wire surface.

## Detector

Cipher strength rank (`_security_rank`): `open(0) < WEP(1) < WPA(2) < WPA2(3) <
WPA3(4)`, parsed from the CoreWLAN string (a transitional `WPA2/WPA3` ranks at
its strongest mode); unrankable → `None` (skip, never guess).

Per SSID, track the **strongest** cipher seen this session as the baseline. On
each associated `link_state`:
- first sighting → set baseline, no fire;
- current rank `<` baseline rank → queue a `critical` `security_downgrade`
  `{ssid, was: <baseline str>, now: <current str>}` (point-in-time, drained in
  `collect`, cooldown keyed `(security_downgrade, ssid)`);
- current rank `>=` baseline → update the baseline to the strongest (an upgrade
  is not a threat).

Baseline = strongest-seen (not first-seen) so once the legit WPA3 network is
observed, any later weaker association to that SSID fires regardless of order.

## Authoritative-signal note

Keys on the OUI-independent **cipher** reported by CoreWLAN, never trusting the
SSID as a trust anchor (the SSID is what the attacker forges — the point is that
the *same* SSID now offers weaker protection). Complements `evil_twin`
(vendor change on the same SSID); both can fire on one hostile reconnect.

## Scope

Fires on (re)association only (`link_state` associated carries the cipher). A
seamless intra-session roam (`roam` event) carries no cipher, so a downgrade via
seamless roam is not covered — documented, acceptable (a forced downgrade
disconnects + reassociates, which does carry it).
