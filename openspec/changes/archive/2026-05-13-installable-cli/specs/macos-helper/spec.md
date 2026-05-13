## MODIFIED Requirements

### Requirement: The helper SHALL be auto-detectable from the Python side without configuration
The Python `_helper.find_helper()` SHALL locate the helper bundle
without the user having to set `PATH` or env vars. The function
SHALL search the following locations in order, returning the first
hit:

1. `DITING_HELPER` env var (full path to the bundle OR the binary
   inside it) — escape hatch for contributors testing a non-default
   build location
2. `<repo>/helper/diting-tianer.app` relative to the source root —
   in-place developer build picked up automatically when `diting`
   is run via `uv run` from a repo checkout
3. `/Applications/diting-tianer.app` — back-compat for users who
   moved the bundle into `/Applications` before the in-place flow
   was the recommended developer path
4. `~/Applications/diting-tianer.app` — same back-compat for
   users who installed to their personal Applications folder
5. `~/Library/Application Support/diting/diting-tianer.app` —
   the install location used by the curl-bash one-line installer

Search order MUST keep the in-repo dev build first so contributors
running `uv run diting` from a checkout always pick up their
freshly-`make helper`ed bundle even if they also have the
one-line installer's copy in place.

#### Scenario: Developer with both a repo checkout and a one-line install
- **WHEN** a contributor has both `<repo>/helper/diting-tianer.app` (from `make helper`) and `~/Library/Application Support/diting/diting-tianer.app` (from the curl-bash installer)
- **THEN** `find_helper()` returns the in-repo path; the Application Support copy is shadowed

#### Scenario: End user with only the one-line install
- **WHEN** a user has no repo checkout, no /Applications copy, only `~/Library/Application Support/diting/diting-tianer.app`
- **THEN** `find_helper()` returns the Application Support path

#### Scenario: Pip install without source AND without a one-line install
- **WHEN** diting is installed via `pip install diting` (no source tree) and the helper bundle is not present at any of the five search locations
- **THEN** `find_helper()` returns `None`, and the BLE / Wi-Fi paths fall back to direct CoreWLAN (which produces redacted scan results until the user installs the helper bundle)

#### Scenario: `DITING_HELPER` env override
- **WHEN** `DITING_HELPER=/Volumes/Builds/diting-tianer.app` is set
- **THEN** `find_helper()` returns that path, ignoring every other location
