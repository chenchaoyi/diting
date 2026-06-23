## Why

There's no in-tool way to upgrade. A user on an old release has to remember and
re-run the `curl … | bash` one-liner. diting should be able to update itself to
the latest binary.

## What Changes

- **Add a `diting update` verb.** It resolves the latest GitHub release, compares
  it with the running version, and:
  - `--json` → emit `{current, latest, update_available}` (no install), exit 0.
  - `--check` → report availability in prose, do not install.
  - default → if a newer release exists, re-run the canonical one-line installer
    pinned to that version (`DITING_VERSION`), so the frozen binary AND the Swift
    helper bundle refresh through the single source of truth (`install.sh`)
    rather than re-implementing download / verify / extract here.
- New `src/diting/update.py` (version compare + GitHub-latest fetch + installer
  re-run, all via `urllib` — no new deps). `update` is registered in `_COMMANDS`
  so `--help` and the `capabilities` manifest describe it; its scene banner is
  suppressed like `setup`.

## Impact

- Specs: `cli` (new `update` requirement).
- Code: `src/diting/update.py` (new), `src/diting/cli.py` (`_run_update`,
  `_COMMANDS` entry, dispatch, banner suppression), `src/diting/i18n.py`
  (ZH strings).
- Network: `update` reaches `api.github.com` + `raw.githubusercontent.com`;
  failures report cleanly (no traceback) and exit non-zero.
