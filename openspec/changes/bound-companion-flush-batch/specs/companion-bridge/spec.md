## MODIFIED Requirements

### Requirement: The relay client queues offline and flushes on reconnect
The sink SHALL post envelopes to the relay and, when the relay is unreachable
(Mac offline), SHALL enqueue them locally and flush in sequence order once
connectivity returns, preserving ordering and not losing events within the
queue's bounded capacity. A single flush SHALL send at most a bounded batch of
envelopes so the per-call blocking time is bounded by the batch size rather than
the backlog depth; the periodic flush driver SHALL keep draining successive
batches while events remain queued, so a large backlog drains incrementally
across cycles rather than in one all-or-nothing burst. Bounding the batch SHALL
NOT change ordering, the bounded-queue drop-oldest behavior, or the
sustained-failure (`relay unreachable`) accounting.

#### Scenario: Offline events flush in order
- **WHEN** the Mac loses connectivity, several push-worthy events occur, and connectivity later returns
- **THEN** the queued envelopes are delivered to the relay in ascending sequence order

#### Scenario: Bounded queue reports drops honestly
- **WHEN** the offline queue reaches capacity before reconnecting
- **THEN** the overflow is dropped with a recorded, user-visible indication rather than silently lost

#### Scenario: A single flush is bounded by the batch size
- **WHEN** more envelopes are queued than the configured flush batch and one flush runs with that batch limit
- **THEN** it sends at most the batch's worth of envelopes, in ascending sequence order, and leaves the remainder queued for the next flush

#### Scenario: A large backlog drains across successive periodic flushes
- **WHEN** a backlog larger than one batch is queued and the relay is reachable
- **THEN** repeated periodic flushes drain the backlog to empty across multiple cycles, each cycle sending at most one batch, with no events lost or reordered
