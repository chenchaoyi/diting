# familiarity-store delta — fix-familiarity-tz-mismatch

## MODIFIED Requirements

### Requirement: The store SHALL persist, stay bounded, and read fail-soft
The store SHALL persist across sessions to a git-ignored local file (default
path with an env override), updated in memory and flushed periodically and on
clean shutdown. Reading SHALL be fail-soft — a corrupt file or record is skipped,
never raising. The store SHALL be bounded: capped at a maximum entity count and
aging out entities unseen beyond a retention threshold, so it cannot grow
without limit. It SHALL be constructible with an injected path for hermetic
testing without a real environment.

The store SHALL tolerate any mix of offset-naive and offset-aware timestamps
across observe, classify, prune, and flush without raising, normalizing naive
values as local time at its boundary (on observe and on read-back), so that
already-persisted naive records heal on load without a migration. Both the
periodic and the shutdown flush SHALL be fail-soft — a store error degrades
the baseline, never the monitor.

#### Scenario: Corrupt record is skipped
- **WHEN** the store file contains a malformed record among valid ones
- **THEN** the load returns the valid records and skips the corrupt one without throwing

#### Scenario: Aged-out and capped
- **WHEN** entities have not been seen beyond the retention threshold, or the count exceeds the cap
- **THEN** the persisted store drops the stalest entities to stay within bounds

#### Scenario: Mixed naive and aware sightings survive a flush
- **WHEN** one entity is observed with an offset-naive timestamp and another with an offset-aware timestamp, and the store is then flushed
- **THEN** the flush completes without raising and both records persist with offset-aware local timestamps

#### Scenario: Persisted naive record heals on load
- **WHEN** the store file contains a record whose `last_seen` is an offset-naive ISO string
- **THEN** loading, classifying against, and pruning that record treat the timestamp as local time without raising
