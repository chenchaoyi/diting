# Forward insights + threats over the companion wire

## Why

Phases 2–3 built the insight + threat layer, but it is desktop-local: the
`insight` event type is not in the companion push set, so the most valuable
signals diting produces — "an unfamiliar group appeared", "possible evil twin",
"Wi-Fi keeps dropping" — never reach the paired phone. The companion bridge
exists precisely to get high-value events to the user when they are away from
the desktop; insights and threats are the events that most deserve that.

This is the cross-repo follow-up deferred across 2b/2c/3: make `insight` a
first-class `companion-protocol` wire type so the desktop can forward it and the
phone can render + notify it. Because it changes the wire contract, it is a
**paired** change — diting (this proposal) and diting-mobile at the same
protocol version, fixtures regenerated here first, then re-vendored there.

## What Changes

- **`insight` becomes a wire event type** in `companion-protocol`'s `EVENT_SPEC`:
  `{type, ts, code: str, severity: enum(info|note|warn|critical), detail: obj}`.
  This needs a new `obj` field tag (a JSON object whose inner keys are not
  strictly validated — insight `detail` varies per `code`). The
  `event.schema.json` + golden fixtures regenerate; a fixture gains one
  `insight` line.

- **Insight `detail` becomes nested, not flattened.** `emit_insight` today
  flattens `detail` onto the payload (`{…, code, severity, count: 4}`). To fit a
  strict schema, the wire (and therefore the JSONL, per the protocol's
  "JSONL mirrors the wire" invariant) carries `detail` as a sub-object
  (`{…, code, severity, detail: {count: 4}}`). Insights shipped only in v1.13.0
  and are desktop-local with no downstream consumers yet, so reshaping now is
  cheap and is the correct long-term shape.

- **Protocol version 2 with per-envelope minimum-version stamping.**
  `PROTOCOL_VERSION = 2`, `SUPPORTED_VERSIONS = {1, 2}`. The envelope `v` is
  stamped as the *minimum* version that can decode the contained event — every
  existing type stays `v1`, only `insight` is `v2`. A not-yet-updated **v1
  mobile** abstains on `v2` envelopes (it already gates on
  `is_supported_version`) and keeps processing every existing event unchanged —
  graceful degradation, no hard break on desktop-updated-first. A v2 mobile
  decodes both. This avoids stamping all traffic v2 (which would blind a v1
  phone to everything).

- **Push wiring.** `insight` joins the push set, but gated by salience like
  everything else: only `notable`+ (i.e. `note`/`warn`/`critical`) insights
  forward; `info` stays local. The sink stops treating the whole type as
  local-only; the existing `familiarity`/`salience` field-strip still applies.

## Impact

- Affected specs: `companion-protocol` (the `insight` wire type + the `obj` tag
  + version 2 + per-envelope stamping), `companion-bridge` (insight is
  push-worthy; salience-gated), `events` (insight `detail` is a nested object).
- Affected code (desktop, this repo): `protocol/_schema_spec.py` (the `insight`
  spec + `obj` tag), `protocol/events_schema.py` (`_tag_ok`/`_field_schema` for
  `obj`), `protocol/version.py` (bump + supported set), `protocol/_generate.py`
  (per-envelope min-version + regenerated fixtures), `companion/crypto.py` or
  `sink.py` (stamp the envelope at the event's min version), `push_policy.py`
  (insight in the push set, salience-gated), `event_log.py` (`emit_insight`
  nested `detail`). Fixtures + `manifest.json` regenerate via
  `python -m diting.companion.protocol._generate`.
- **Paired mobile change (separate repo `chenchaoyi/diting-mobile`):** vendor the
  regenerated protocol artifacts, add the `insight` type to its decoder, render
  `[INSIGHT]`/`[THREAT]` timeline entries + notifications, and confirm it
  abstains (not crashes) on `v2` envelopes before the desktop side ships. The
  cross-repo fixture-conformance test covers the vendored artifacts.
- **Scope limit (honest):** this forwards the existing insight/threat events
  only. It does NOT add `security_downgrade` (still needs the connection cipher
  as its own wire field) and does NOT change any detector. Desktop can merge its
  half first (fixtures + version live in this repo, the source of truth), but
  must not be released to users until mobile ships v2 support, so the phone
  renders rather than silently drops the new envelopes.

## Open decision (needs a call before implementation)

The **per-envelope minimum-version** scheme above is the recommendation (it lets
desktop and mobile update independently without a flag day). The simpler
alternative — stamp every envelope `v2` and require mobile updated first — is
rejected here because it blinds a v1 phone to *all* events, not just insights.
Confirm the per-envelope approach (or pick the flag-day bump) before the wire
work lands.
