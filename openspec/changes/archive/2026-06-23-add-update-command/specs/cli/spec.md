## ADDED Requirements

### Requirement: `update` SHALL check for and install the latest diting release

`diting update` SHALL resolve the latest published release of diting, compare it
with the running version, and report or perform an upgrade. It SHALL be a
canonical verb listed in `--help` and the `capabilities` manifest, and SHALL NOT
emit the scene-detection banner.

`update` SHALL resolve the latest version from the GitHub releases API and treat
a leading `v` as insignificant when comparing versions. With `--json` it SHALL
print exactly one object `{current, latest, update_available}` to stdout and exit
0 (it SHALL NOT install). With `--check` it SHALL report whether an update is
available in human-readable prose and SHALL NOT install. With neither flag, when
the latest release is newer than the running version, `update` SHALL upgrade by
re-running the canonical one-line installer pinned to the resolved version (via
`DITING_VERSION`), so the binary and the Swift helper bundle refresh through the
same path a fresh install uses; when already current it SHALL say so and exit 0.

If the latest version cannot be resolved (network or parse failure), `update`
SHALL report the failure without a traceback and exit non-zero — as a
`{"error","code"}` object on stderr under `--json`, or a one-line message on
stderr otherwise.

#### Scenario: Reports an available update as JSON
- **WHEN** the user runs `diting update --json` and a newer release exists
- **THEN** stdout is one object `{current, latest, update_available: true}` and the exit code is 0, with no install performed

#### Scenario: Already on the latest release
- **WHEN** the user runs `diting update` and the running version is the latest
- **THEN** it reports that diting is already current and exits 0 without installing

#### Scenario: Check-only does not install
- **WHEN** the user runs `diting update --check` and a newer release exists
- **THEN** it reports the available upgrade and exits without re-running the installer

#### Scenario: Installs the latest when newer
- **WHEN** the user runs `diting update`, a newer release exists, and they proceed
- **THEN** `update` re-runs the canonical installer pinned to the resolved version so the binary and helper bundle are upgraded

#### Scenario: Network failure is reported cleanly
- **WHEN** the latest version cannot be resolved
- **THEN** `update` prints a one-line error to stderr (or a `{"error","code"}` object under `--json`) and exits non-zero, with no traceback
