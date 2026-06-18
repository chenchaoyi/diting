## 1. Test plan first (test-first discipline)

- [x] 1.1 Update `tests/TESTING.md` (EN) with the new CLI contract cases: verb routing (`status`/`scan`/`stream`/`capabilities`), alias deprecation notices, `--json` stdout purity, `capabilities` manifest shape + dispatch parity, `--duration`/`--since` grammar, exit codes
- [x] 1.2 Mirror the same additions into `docs/zh/TESTING.md` (ZH parity)

## 2. Shared CLI plumbing

- [x] 2.1 Add the declarative command-descriptor table in `cli.py` (name, summary, flags `{name,type,default,repeatable}`, output mode, exit codes, deprecated-of) as the single source for parsing, `--help`, and `capabilities`
- [x] 2.2 Add a shared `--duration` parser reusing `analyze`'s `parse_since` grammar; wire `--since` to the same grammar
- [x] 2.3 Add a shared JSON-output path (one writer per command: JSON to stdout, prose + `{"error","code"}` to stderr, exit-code convention)

## 3. Verb redesign + aliases

- [x] 3.1 Rename the `once` handler to `status`; register `once` as a forwarding alias that prints the stderr deprecation notice
- [x] 3.2 Repoint the headless-stream handler to `stream` (canonical event-log JSONL, `--duration` bound); register `monitor` and `watch` as forwarding aliases
- [x] 3.3 Implement `scan` (`--wifi`/`--ble`, default both; `--duration` bounds BLE) reusing `_helper.scan` and the `ble_decoder_survey` decode path; per-sensor structured errors
- [x] 3.4 Implement `capabilities` (pretty + `--json`) emitting `schema_version`, `commands`, `deprecated_aliases`, exit-code convention from the descriptor table
- [x] 3.5 Route `--notify` on the default TUI subcommand and `stream`; ensure `monitor --notify` forwards correctly
- [x] 3.6 Regenerate per-subcommand `--help` from the descriptor table; top-level `--help` states exit-code convention and points at `capabilities`

## 4. Tests

- [x] 4.1 Verb-routing + alias-forwarding tests (canonical output identical to alias output; deprecation notice on stderr only)
- [x] 4.2 `--json` stdout-purity tests across `status`/`scan`/`analyze`/`capabilities` (jq-parseable; notices/chrome on stderr; JSON error object on failure)
- [x] 4.3 `capabilities` manifest tests: schema_version present, every canonical verb covered, manifest/dispatch parity, `deprecated_aliases` correct
- [x] 4.4 `--duration`/`--since` grammar tests (suffix forms + bad-value exit 2) and exit-code convention tests (0/1/2)
- [x] 4.5 Run the full suite: `uv run pytest`

## 5. Docs + parity

- [x] 5.1 Write `docs/agents.md` — agent guide: tool surface, JSON contracts, invocation patterns, `capabilities` discovery
- [x] 5.2 Write `docs/zh/agents.md` — ZH parity of the agent guide
- [x] 5.3 Update `README.md` command table for the new verbs (+ alias note)
- [x] 5.4 Update `docs/zh/README.md` command table (ZH parity)
- [x] 5.5 Add any new user-facing strings via `t()` with EN + ZH catalog entries

## 6. Gates

- [x] 6.1 `uv run pytest`
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 6.3 `openspec validate --specs --strict` and `openspec validate agent-cli-foundation --strict`
