## Context

diting's CLI (`src/diting/cli.py`) is hand-rolled argv slicing: global flags are
extracted by a chain of `_extract_*` helpers in `_dispatch()`, then `args[0]`
selects one of `once`/`watch`/`monitor`/`calibrate`/`analyze`/`companion` (or the
default TUI). `--json` exists on `once`/`watch`/`analyze` only, each with its own
output shape; `monitor` parses its own `--notify`; help is built by ad-hoc string
builders. The engine layer (pollers, `_helper.scan`, `BLEPoller`, `EventLogger`,
`analyze`) is already cleanly separable and exercised headlessly today.

This change is the first of three (foundation → headless-capture-engine →
capture-sessions). It touches only the CLI surface and its tests/docs — no
engine, poller, decoder, or helper-schema changes.

## Goals / Non-Goals

**Goals:**
- A predictable, JSON-first, self-describing agent CLI: `status`, `scan`,
  `stream`, `analyze`, `capabilities`, `companion`, `calibrate`.
- One uniform `--json` contract across all read commands (pure-JSON stdout,
  chrome/errors on stderr, locale-stable English keys, documented exit codes).
- Backward-compatible forwarding from the old verbs for at least one release.
- A machine-discoverable command manifest (`capabilities --json`) and a human/
  agent guide (`docs/agents.md` + ZH).

**Non-Goals:**
- No full-sensor headless capture (LAN/mDNS/RF) — that is
  `headless-capture-engine`. `scan`/`stream` here cover Wi-Fi + BLE only.
- No managed background sessions — that is `capture-sessions`.
- No move to argparse/click/typer; keep the hand-rolled parser (lower risk,
  preserves the existing global-flag extraction and exit-hint behaviour).
- No engine refactor, no helper schema bump, no TUI changes.

## Decisions

### D1 — Verb mapping and aliases
- `once` → `status`; `watch` → `stream`; `monitor` → `stream`. `analyze`,
  `calibrate`, `companion`, default-TUI keep their names. New: `scan`,
  `capabilities`.
- Old verbs remain registered as **aliases**: dispatch resolves the alias to its
  canonical handler, prints exactly one line `diting: 'once' is deprecated; use
  'status'` to **stderr** (never stdout — keeps `--json` pure), then runs
  normally. Aliases are kept for ≥1 release and listed in `capabilities` under a
  `deprecated_aliases` map so an agent learns the canonical name.
- `stream` emits canonical event-log JSONL (the `monitor` shape — the same schema
  `analyze` consumes), not `watch`'s lighter change-event shape. `watch`→`stream`
  is therefore a documented output change; acceptable under the redesign mandate.
  Rationale: one stream format that round-trips through `analyze` beats two.

  Alternative considered: keep `watch`'s change-event JSON as a third format.
  Rejected — two stream shapes is exactly the inconsistency this change removes.

### D2 — Uniform `--json` contract (single chokepoint)
Factor a small `JsonContext` helper that every read command uses: it routes the
single JSON document (or NDJSON lines) to stdout, all human prose to stderr, and
on failure emits `{"error": <msg>, "code": <int>}` to stderr with the matching
exit code. `status`/`scan` print one object; `stream` prints NDJSON. This
replaces the three independent `--json` implementations with one, guaranteeing
identical purity/error semantics. Keys stay locale-stable English regardless of
`--lang`.

### D3 — `capabilities` manifest is data, not prose
`capabilities` builds its manifest from a declarative table (a list of command
descriptors: name, summary, flags `[{name,type,default,repeatable}]`, output
mode `json-object|json-lines|text|tui`, exit codes, deprecated-of). The same
table drives `--help` text and the manifest, so they can't drift. `--json` emits
the table; plain `capabilities` pretty-prints it. The manifest carries a
top-level `schema_version` (start at `1`) so agents can pin.

  Alternative considered: hand-write the manifest separately. Rejected — it would
  drift from actual parsing/help, defeating the discovery guarantee.

### D4 — `scan` reuses existing headless paths
`scan --wifi` calls `_helper.find_helper()` → `_helper.scan()`; `scan --ble`
follows the `scripts/ble_decoder_survey.py` pattern (spawn `ble-scan`, dedup,
`decoders.decode_all`). Default (no sensor flag) runs both and keys the JSON by
sensor. A `--duration` bounds the BLE collection window (default short, e.g. 4s).
No new engine code — just wiring existing functions behind the verb.

### D5 — Flag grammar
- `--duration D` accepts `Ns`/`Nm`/`Nh` or bare seconds; shared parser, reused by
  `scan`/`stream` (and later `capture`). Reuse `analyze`'s existing `parse_since`
  grammar for `--since` so the two stay identical.
- `--sensors a,b` reserved/parsed now (accepting `wifi`,`ble`) so the flag grammar
  is stable before `headless-capture-engine` widens the accepted set.

## Risks / Trade-offs

- [Breaking the user's own scripts/habits] → Deprecation aliases forward for ≥1
  release with a stderr notice; `capabilities.deprecated_aliases` documents the
  mapping; README + agent guide updated in the same PR.
- [`watch`→`stream` output shape changes] → Documented in the alias notice and
  the agent guide; `watch` was lightly used and the canonical JSONL is strictly
  more useful (round-trips through `analyze`).
- [Help text vs manifest drift] → Both generated from the one descriptor table
  (D3), so they can't diverge; a test asserts every dispatchable verb appears in
  the manifest and vice-versa.
- [Hand-rolled parser accreting more special-casing] → Contained by the shared
  `--duration`/`JsonContext` helpers; a full parser migration is explicitly a
  non-goal to keep this change low-risk.

## Migration Plan

1. Land new verbs + aliases + `capabilities` + uniform `--json` behind the
   existing parser; old verbs keep working (alias notice only).
2. Update README/agent guide to teach the new verbs.
3. Future release may drop the aliases via a follow-up REMOVED requirement once
   downstream usage has migrated.

## Open Questions

- None blocking. Whether to eventually drop the aliases is deferred to a future
  change, not decided here.
