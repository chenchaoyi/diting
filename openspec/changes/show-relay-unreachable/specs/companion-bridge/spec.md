# companion-bridge — delta

## MODIFIED Requirements

### Requirement: The companion surface is explicit and discoverable
diting SHALL expose companion control via a `--companion` CLI surface and/or a
TUI toggle, reusing `--notify` semantics where sensible, and SHALL surface
current pairing and connectivity state (paired / not paired, relay reachable /
queued).

The TUI subtitle chip SHALL distinguish a transiently-queued backlog from a
sustained delivery failure: when several consecutive flush attempts deliver
nothing (threshold: 3 — about 9 s at the periodic flush interval), the queued
chip SHALL carry a `relay unreachable` annotation. The first successful send
SHALL clear the annotation. A flush against an empty queue SHALL NOT count
toward the threshold either way.

#### Scenario: Status is observable
- **WHEN** the user inspects the companion surface
- **THEN** it reports whether a device is paired and whether the relay is currently reachable or events are queued

#### Scenario: Pairing from inside the TUI
- **WHEN** the user presses the companion key in the running TUI
- **THEN** a modal renders the pairing QR (generating a pairing if none exists yet), and forwarding begins on the running app without a restart

#### Scenario: Sustained flush failure names itself
- **WHEN** events are queued and 3 consecutive flush attempts deliver nothing
- **THEN** the subtitle chip renders the queued count with a `relay unreachable` annotation

#### Scenario: A transient blip does not flash the warning
- **WHEN** a single flush attempt fails and the next one delivers
- **THEN** the chip shows the plain queued count throughout, and never the unreachable annotation

#### Scenario: Recovery clears the annotation
- **WHEN** the unreachable annotation is showing and a flush then delivers at least one envelope
- **THEN** the annotation is dropped on the next chip render
