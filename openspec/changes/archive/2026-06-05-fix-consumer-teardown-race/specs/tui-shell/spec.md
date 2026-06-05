# tui-shell — delta

## ADDED Requirements

### Requirement: Event-consumer workers SHALL tolerate screen teardown
The App's event-consumer workers SHALL absorb a `NoMatches` query failure
by ending the worker quietly instead of crashing the app — this covers all
five consumers (Wi-Fi poller, BLE, latency, Bonjour, LAN inventory).
Rationale: the fixed panels never unmount in a running app (view cycling
only toggles `display`), so `NoMatches` inside a consumer can only occur
when shutdown has already unmounted the screen's children while the worker
drains its last queued events — a race observed in CI's test context. Any
other exception SHALL still propagate so genuine bugs keep failing loudly.

#### Scenario: Late event after teardown ends the worker quietly
- **WHEN** a consumer worker processes a queued event after the screen's panels have been unmounted and a panel query raises `NoMatches`
- **THEN** the worker ends without raising and the app shutdown completes cleanly

#### Scenario: Other exceptions still propagate
- **WHEN** a consumer coroutine raises any exception other than `NoMatches`
- **THEN** the exception propagates unchanged (the worker fails loudly)
