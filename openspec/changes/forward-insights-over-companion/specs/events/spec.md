# events — delta

## MODIFIED Requirements

### Requirement: An insight event type SHALL carry a code, severity, and detail
The event vocabulary SHALL include an `insight` event — a synthesized
valuable-change observation — carrying a stable English `code`, a `severity`
(`info` / `note` / `warn` / `critical`, where `critical` is the threat tier),
and an optional structured `detail`. The `code` is locale-stable (the analysis
key); the human one-liner is derived from `code` + `detail` at render / notify
time via `t()`, so the JSONL carries no localised text. `detail` SHALL be
serialised as a single nested object (e.g. `"detail":{"count":4}`), NOT
flattened onto the event — so the JSONL line mirrors the `companion-protocol`
wire shape exactly. `InsightEvent` is a frozen dataclass with a `timestamp`,
like every other event, and rides the same EventRing + JSONL writer.

#### Scenario: Insight serialises with a stable code
- **WHEN** an `insight` event is emitted to a file sink
- **THEN** the JSONL line carries `"type":"insight"`, the English `code`, and the `severity`

#### Scenario: Detail is a nested object when supplied
- **WHEN** an insight is emitted with a non-empty `detail`
- **THEN** the JSONL line carries `detail` as a nested object; when `detail` is absent the line omits the key
