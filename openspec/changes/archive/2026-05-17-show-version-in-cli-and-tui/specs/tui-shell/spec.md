## ADDED Requirements

### Requirement: The App title SHALL include the running version
`DitingApp.title` SHALL be set to `"diting v<version>"` where `<version>` is the value of `importlib.metadata.version("diting")`. The Textual header renders this on the left of the screen, so the user always sees the running version without pressing any key.

If `importlib.metadata.version("diting")` raises `PackageNotFoundError`, the title SHALL fall back to `"diting v0+unknown"` — the TUI MUST NOT fail to start.

#### Scenario: Title bar shows the running version
- **WHEN** the user launches the TUI
- **THEN** the App's `title` attribute equals `diting v<X.Y.Z>` where `<X.Y.Z>` matches the installed package version
- **AND** the version remains visible throughout the session — toggling views does not erase it

#### Scenario: Subtitle is unaffected
- **WHEN** the user toggles views or pauses polling
- **THEN** `sub_title` continues to render the existing session-state bits (`view: ... · scan Ns · PAUSED`)
- **AND** `title` remains `diting v<version>`
