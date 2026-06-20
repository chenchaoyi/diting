# capture-sessions Specification

## Purpose
TBD - created by archiving change capture-sessions. Update Purpose after archive.
## Requirements
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

#### Scenario: Start returns immediately with the session + path
- **WHEN** the user runs `diting capture start --name nightwatch --sensors all`
- **THEN** the process exits 0 promptly, a record for `nightwatch` exists, and stdout names the session and its capture path

#### Scenario: Duplicate running name is rejected
- **WHEN** the user runs `diting capture start --name nightwatch` while a running `nightwatch` exists
- **THEN** stderr reports the name is already running and the process exits 2

#### Scenario: Invalid name
- **WHEN** the user runs `diting capture start --name "bad name"`
- **THEN** stderr reports the invalid name and the process exits 2

### Requirement: The session registry SHALL live under a stable state dir

Session records SHALL be stored under a fixed state directory so `capture list`
works from any working directory: the directory named by `DITING_STATE_DIR`, or
`~/.diting` by default. Each session SHALL be one JSON record carrying at least
its name, pid, sensors, capture path, started-at timestamp, requested duration
(or null), and last-written status. The capture JSONL SHALL default to a path
under the state dir (overridable with `--out`). The state directory SHALL be
created on first use.

#### Scenario: Records are found from another directory
- **WHEN** a session is started in one directory and `diting capture list` is run from another
- **THEN** the session appears in the list

#### Scenario: State dir override
- **WHEN** `DITING_STATE_DIR=/tmp/x diting capture start --name s` runs
- **THEN** the record and capture live under `/tmp/x`, not under `~/.diting`

### Requirement: `capture list` and `capture status` SHALL report live status

`capture list` SHALL print every known session with a status derived live from
process liveness, and `capture status [--name N]` SHALL print one session's
record plus its live status. A record marked running whose pid is no longer
alive SHALL be reported as exited / crashed — never as running. Both SHALL accept
`--json` for one machine-readable document (an array for `list`, an object for
`status`), with the uniform JSON contract (pure stdout, prose to stderr).

#### Scenario: Running session
- **WHEN** `diting capture list --json` runs while a session's pid is alive
- **THEN** that session's entry has status `running` and its pid

#### Scenario: Dead pid is not reported running
- **WHEN** a session record says running but its pid has exited
- **THEN** `capture list` reports that session as `exited` (or `crashed`), not `running`

#### Scenario: Unknown session name
- **WHEN** `diting capture status --name nope` runs and no such session exists
- **THEN** stderr reports the unknown session and the process exits 1

### Requirement: `capture stop` SHALL terminate a session cleanly

`diting capture stop --name N` SHALL send SIGTERM to the session's process and
mark the record stopped; `--all` SHALL stop every running session. Because
`diting stream` handles SIGTERM as a graceful shutdown, a stopped capture SHALL
be a complete, flushed JSONL file rather than a truncated one. Stopping a session
that is not running SHALL be reported without error (idempotent).

#### Scenario: Stop terminates and flushes
- **WHEN** the user runs `diting capture stop --name nightwatch` on a running session
- **THEN** the process is signalled, the record is marked stopped, and the capture file ends with a complete final line

#### Scenario: Stop all
- **WHEN** the user runs `diting capture stop --all` with two running sessions
- **THEN** both are signalled and marked stopped

#### Scenario: Stop an already-stopped session
- **WHEN** the user runs `diting capture stop --name done` on a session that already exited
- **THEN** the command succeeds (exit 0) and reports nothing to stop

### Requirement: `diting stream` SHALL shut down cleanly on SIGTERM

`diting stream` SHALL install a SIGTERM handler that cancels the capture and runs
the engine's teardown — flushing the familiarity store and closing the
`EventLogger` — then exits 0. A SIGTERM mid-capture SHALL therefore produce a
complete capture (the final JSONL line is whole), not a truncated one. SIGINT
(Ctrl+C) behaviour SHALL be unchanged.

#### Scenario: SIGTERM flushes and closes
- **WHEN** a running `diting stream --out FILE` receives SIGTERM
- **THEN** the logger is closed, FILE ends with a complete JSON line, and the process exits 0

### Requirement: `capture tail` SHALL print the session's capture

`diting capture tail --name N` SHALL print the last K lines of the session's
capture JSONL (`-n K`, sensible default), and `-f` SHALL follow the file,
printing newly-appended lines until interrupted. The output SHALL be the raw
canonical JSONL (the same schema `analyze` consumes), so it pipes into `jq`
unchanged. Tailing an unknown session SHALL exit 1 with a stderr message.

#### Scenario: Tail last lines
- **WHEN** the user runs `diting capture tail --name nightwatch -n 20`
- **THEN** stdout is the last 20 JSONL lines of that session's capture

#### Scenario: Tail is jq-pipeable
- **WHEN** the user runs `diting capture tail --name nightwatch -n 50 | jq 'select(.type=="roam")'`
- **THEN** jq parses every line; nothing breaks the pipeline

