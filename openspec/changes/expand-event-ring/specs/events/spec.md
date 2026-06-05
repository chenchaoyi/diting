# events — delta

## MODIFIED Requirements

### Requirement: The `EventRing` SHALL be size-bounded and thread-safe-by-construction
The ring SHALL retain at most 1000 events by default (configurable via
constructor arg). Older events SHALL roll off the front when the
buffer is full. The ring SHALL be appendable from any coroutine in
the asyncio loop without explicit locking — Python's GIL plus the
single-thread asyncio model is the consistency guarantee.

#### Scenario: Ring overflow
- **WHEN** the 1001st event is appended to a default-sized ring
- **THEN** the oldest event is dropped silently, the new event lands at the tail, and `snapshot()` returns 1000 events (newest last)

#### Scenario: Custom capacity still honored
- **WHEN** a ring is constructed with `capacity=5` and 6 events are appended
- **THEN** `snapshot()` returns the 5 newest events
