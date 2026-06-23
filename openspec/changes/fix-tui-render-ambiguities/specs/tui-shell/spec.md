## ADDED Requirements

### Requirement: Help modal rows SHALL separate the key/label from its description

Help modal rows SHALL render at least one space between a row's key/label and
its description, regardless of the label's length — panel labels like `Events`
and key bindings like `enter / i` included. A label whose width meets or exceeds
the label column SHALL NOT abut its description (no merged words such as
`Eventsstrip` or `enter / iinspect`).

#### Scenario: A label that fills the column still has a gap
- **WHEN** the help modal renders a label that is exactly the label-column width (`Events`) or wider (`enter / i`)
- **THEN** the label and its description are separated by whitespace — the rendered text contains `Events strip…` and `enter / i inspect…`, never `Eventsstrip` or `enter / iinspect`
