## MODIFIED Requirements

### Requirement: Decoders SHALL be registered functions taking a `BLEDevice` and returning a dict
Each decoder SHALL be a callable with the signature
`decode(d: BLEDevice) -> dict[str, Any] | None` and SHALL register
itself via the `@register` decorator at import time. The registry
is a flat module-global list; order of registration determines order
of execution but the framework SHALL NOT depend on order for
correctness — multiple decoders on the same device produce a
key-merged dict.

#### Scenario: Adding a new decoder
- **WHEN** a contributor creates `src/diting/decoders/foo.py` with `@register def decode(d): ...`
- **THEN** importing the package picks up `foo.py` and `decode_all` includes its output
