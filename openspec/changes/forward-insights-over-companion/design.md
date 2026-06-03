# Design — insights/threats over the companion wire

## Wire shape: a nested `detail` object + an `obj` tag

`insight` joins `EVENT_SPEC`:

```python
"insight": {
    "required": {"code": "str", "severity": "str"},
    "optional": {"detail": "obj"},
    "enums": {"severity": ["info", "note", "warn", "critical"]},
},
```

`obj` is a new field tag = a JSON object (`isinstance(v, dict)`) whose inner keys
are NOT strictly validated — insight `detail` is `{count}` / `{peak_loss_pct}` /
`{ssid, new_vendor}` / `{identifier, locations}` depending on `code`, so a
per-key schema would couple the protocol to every detector. `_tag_ok` gets an
`obj` branch; `_TAG_SCHEMA`/`_field_schema` map it to
`{"type": "object"}` (no `additionalProperties: false` inside `detail`, while
the envelope's top level stays strict).

The flattening in `emit_insight` is removed: `detail` is emitted as a nested
sub-object so the JSONL line matches the wire (the protocol's
"`_schema_spec` mirrors `emit_*`" invariant). `InsightEvent.detail` is already a
dict; the dataclass, `format_insight_summary`, and the TUI render are unchanged
— only the serialiser and the JSONL-shape tests move from flat keys to
`row["detail"][...]`.

## Versioning: per-envelope minimum version

`PROTOCOL_VERSION = 2`, `SUPPORTED_VERSIONS = {1, 2}`.

A new map gives the minimum protocol version that can decode each type:

```python
EVENT_MIN_VERSION = {"insight": 2}   # default 1
```

The seal path stamps the envelope `v` = `EVENT_MIN_VERSION.get(type, 1)`. So:
- every existing event → `v1` envelope → a v1 mobile still accepts it;
- an `insight` → `v2` envelope → a v1 mobile's `is_supported_version(2)` is
  False, so it abstains on that envelope and drops the insight, but keeps every
  other event flowing. A v2 mobile accepts both.

This is the crux: it decouples the two repos' release timing. Stamping all
traffic `v2` (the rejected alternative) would make a v1 phone abstain on
*everything*.

The envelope schema's `v` enum widens from `[1]` to `[1, 2]`.

## Push gating

`insight` is added to `DEFAULT_PUSH_TYPES`. The existing salience gate already
drops `< low`; insights are `low`/`notable`/`high` by severity
(`info`→low, `note`→notable, `warn`/`critical`→high), so with the default
`min_salience = low`, `info` insights are suppressed and everything else
forwards. No insight-specific push code — it rides the salience gate. The
silence window keys on `code` (the `_target` helper gains an `insight` branch
returning `code`).

The sink's local-only field strip (`familiarity`, `salience`) is unchanged and
still applies to insight payloads; only the *type* stops being implicitly
local (it was never explicitly stripped — it simply was not in the push set).

## Sequencing (cross-repo)

1. **diting (this repo)** — regenerate fixtures (`python -m
   diting.companion.protocol._generate`); the source of truth for the wire
   contract lives here. Merge desktop half.
2. **diting-mobile** — vendor the regenerated `protocol/` artifacts, decode +
   render `insight` (info/note/warn → `[INSIGHT]`, critical → `[THREAT]`),
   surface a notification, and verify it abstains on `v2` envelopes it can't yet
   decode. The cross-repo conformance test pins the vendored artifacts to this
   repo's `manifest.json` hashes.
3. **Ship desktop to users only after mobile v2 is out**, so a paired phone
   renders the new envelopes instead of dropping them. (Desktop-updated-first is
   safe either way thanks to per-envelope versioning — the phone just doesn't
   see insights until it updates.)

## Alternatives considered

- **Flag-day v2 bump (all envelopes v2).** Rejected — blinds a v1 phone to all
  events until it updates.
- **Keep v1, relax `validate_event` to abstain on unknown types.** Rejected —
  silently weakens the strict-schema guarantee for every type, and a v1 mobile
  vendoring the old validator still rejects `insight` regardless.
- **Flattened detail on the wire with `additionalProperties: true` for
  insight.** Rejected — un-strict top-level envelope; the nested `detail` keeps
  strictness where it matters (envelope keys) and contains the variability.
