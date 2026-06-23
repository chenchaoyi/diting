## Why

`diting --help` and the README's agent section drifted out of sync with the
actual verb surface. The hand-written top-level usage lists only `status`, `scan`,
`stream`, `calibrate`, `analyze`, `companion`, `capabilities` — it never gained
`capture` (capture-sessions), `setup` (permission-setup), or `update`
(add-update-command), even though all three are dispatchable canonical verbs in
the `capabilities` manifest. The README likewise enumerates a stale `--json` verb
list. A new user running `diting --help` cannot discover three shipped commands.

## What Changes

- **`diting --help` (`_usage`) lists every canonical verb** — add `capture`,
  `setup`, `update`, and correct the "accepts `--json`" line. A guard test asserts
  every `_CANONICAL_VERBS` entry appears in the usage text, so it cannot drift
  again.
- **README (EN + ZH) agent section** lists the current `--json`-capable verbs and
  describes the non-TUI subcommand set accurately.

## Impact

- Specs: `cli` (a guarantee that top-level `--help` lists every canonical verb).
- Code: `src/diting/cli.py` (`_usage`). Docs: `README.md` + `docs/zh/README.md`.
- No behaviour change beyond the help/doc text; all listed verbs already exist.
