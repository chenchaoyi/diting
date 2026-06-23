## ADDED Requirements

### Requirement: The top-level `--help` SHALL list every canonical subcommand

`diting --help` (the top-level usage) SHALL list every canonical subcommand the
CLI dispatches — the same set advertised in the `capabilities` manifest — so a
user can discover the whole surface from the help text alone. When a canonical
subcommand is added or removed, the top-level usage SHALL be updated in the same
change; the usage text SHALL NOT advertise a subset.

#### Scenario: Help lists all canonical verbs
- **WHEN** the user runs `diting --help`
- **THEN** the output lists every canonical subcommand (including `capture`, `setup`, and `update`), matching the verb set in `diting capabilities --json`
