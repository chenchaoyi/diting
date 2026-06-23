## MODIFIED Requirements

### Requirement: `capture start` SHALL launch a detached named session and return immediately

`diting capture start --name N` SHALL spawn a detached `diting stream` for the
named session, write a session record, and return without blocking. `--sensors`,
`--out`, and `--duration` SHALL be forwarded to the spawned stream. The child
SHALL run in its own process group so the parent's exit does not terminate it,
write its JSONL to the capture path, and outlive the `capture start` invocation.
`--name` SHALL be required and match `[A-Za-z0-9._-]+`; an invalid or missing
name SHALL be a usage error (exit 2). Starting a name whose session is still
running SHALL be a usage error (exit 2); starting a name whose prior session has
exited or been stopped SHALL overwrite the record.

The spawned-stream invocation SHALL be correct for the runtime: in a frozen
(PyInstaller) install — where `sys.executable` is the `diting` binary itself, not
a Python interpreter — `capture start` SHALL invoke the binary's own `stream`
verb directly (`[sys.executable, "stream", …]`), NOT `[sys.executable, "-m",
"diting", "stream", …]` (the frozen binary rejects `-m` as an unknown subcommand
and the detached stream would exit immediately, leaving an empty capture). The
source / `uv run` runtime (where `sys.executable` is a Python interpreter) SHALL
use `-m diting`.

#### Scenario: Start returns immediately with the session + path
- **WHEN** the user runs `diting capture start --name nightwatch --sensors all`
- **THEN** the process exits 0 promptly, a record for `nightwatch` exists, and stdout names the session and its capture path

#### Scenario: Duplicate running name is rejected
- **WHEN** the user runs `diting capture start --name nightwatch` while a running `nightwatch` exists
- **THEN** stderr reports the name is already running and the process exits 2

#### Scenario: Invalid name
- **WHEN** the user runs `diting capture start --name "bad name"`
- **THEN** stderr reports the invalid name and the process exits 2

#### Scenario: Frozen install spawns the stream verb directly
- **WHEN** `capture start` runs from a frozen binary (`sys.frozen` is true)
- **THEN** the spawned argv invokes `<binary> stream …` directly, with no `-m diting`, so the detached stream actually runs and writes its capture
