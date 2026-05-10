# Tasks — document cli

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/cli.py` (`main`, the `_run_*` subcommand handlers, `_extract_lang_arg` / `_extract_log_arg` / `_resolve_log_path` / `default_out_dir`).
- [x] 1.2 Cross-checked exit-hint behaviour against the post-merge work that added it (`tip: summarise this session with wifiscope analyze {path}`).

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "Quick start" / `wifiscope --help` output gain a one-liner pointing to `openspec/specs/cli/spec.md`.
- [x] 2.2 The exit-hint string itself is i18n'd via `t()` already; document parity.
