## ADDED Requirements

### Requirement: `--version` SHALL print the running version and exit 0
`diting --version` SHALL print exactly one line `diting <version>` to stdout (where `<version>` is the value of `importlib.metadata.version("diting")`) and exit with status 0. The flag SHALL be recognised at the top level only; passing it after a subcommand (`diting once --version`) SHALL be ignored or rejected by the subcommand's own argument parser.

If `importlib.metadata.version("diting")` raises `PackageNotFoundError` (e.g. an unusual install layout without a dist-info record), `--version` SHALL print `diting 0+unknown` and exit 0 — it MUST NOT crash.

#### Scenario: User asks for the version
- **WHEN** the user runs `diting --version`
- **THEN** stdout has exactly one line `diting <X.Y.Z>` matching `pyproject.toml`'s `version` field
- **AND** the process exits with status 0
- **AND** no TUI is launched, no helper is spawned, no log file is written

#### Scenario: Frozen binary reports the same version as the source build
- **WHEN** the user installs via `curl ... | bash` and runs `diting --version`
- **THEN** the output matches what `uv run diting --version` prints from a checkout at the same tag
