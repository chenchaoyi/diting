# Document the `cli` capability

## Why

`wifiscope`'s command-line surface is the contract users build
shell pipelines on top of (`wifiscope monitor | jq`, cron jobs
running `wifiscope analyze`, `--log` -then-`analyze` workflows). The
flag-resolution order, the SIGPIPE-cleanly-on-monitor, the exit-
hint after a logged session, and the `--lang` precedence are all
small but load-bearing. Backfill captures them so we don't quietly
break a user's automation.

## What Changes

- Introduce capability `cli`.
- No code changes — backfill from `src/wifiscope/cli.py`.

## Capabilities

### New Capabilities
- `cli`: subcommand vocabulary, default-TUI behaviour, `--lang`
  precedence, `--log` semantics with optional default path, exit-
  hint contract, monitor-stdout-cleanliness invariant, `--config`
  fallback.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/cli/spec.md`
- Cross-cuts with: every capability behind a subcommand —
  `wifi-scanning` / `bluetooth-scanning` (TUI default),
  `event-log` (`--log` plumbing, monitor JSONL),
  `analyze` (analyze subcommand), `environment-monitor`
  (calibrate subcommand), `i18n` (`--lang` resolution path)
- Future impact: adding a subcommand or changing flag precedence
  MUST file an ADDED / MODIFIED Requirement
