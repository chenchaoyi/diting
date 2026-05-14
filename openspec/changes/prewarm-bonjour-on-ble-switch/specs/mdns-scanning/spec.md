## MODIFIED Requirements

### Requirement: `zeroconf` dependency SHALL be lazy-imported and pre-warmed on the first non-Wi-Fi view
`from zeroconf import ...` SHALL appear ONLY inside `src/diting/mdns.py` and SHALL be top-level inside that module (not function-local). `src/diting/tui.py` SHALL NOT `import diting.mdns` at module load. The TUI SHALL trigger the first import of `diting.mdns` (and the construction of a `BonjourPoller`) the first time the user leaves the Wi-Fi view — i.e. the wifi → BLE step in the wifi → BLE → mDNS cycle — so that the cost is absorbed while the user is reading the BLE panel and the second `n` press (BLE → mDNS) does not pause. The pre-warm SHALL run on a worker thread (`asyncio.to_thread`) so the asyncio event loop and the visible BLE view stay responsive throughout. Users who never leave the Wi-Fi view SHALL NOT pay the `zeroconf` import cost or its background-thread cost.

#### Scenario: User never leaves Wi-Fi view
- **WHEN** the user runs `diting` and never presses `n`
- **THEN** `zeroconf` is never imported
- **AND** no Bonjour browsing thread is started

#### Scenario: User cycles wifi → BLE → mDNS for the first time
- **WHEN** the user presses `n` once (wifi → BLE)
- **THEN** the TUI starts a background worker that imports `diting.mdns`, instantiates a `BonjourPoller`, and begins the consumer task — all off the asyncio event loop
- **AND** the BLE view renders immediately, with no perceptible pause attributable to Bonjour startup
- **WHEN** the user presses `n` a second time (BLE → mDNS)
- **THEN** the mDNS panel is shown immediately (the poller is either ready or completes within a few hundred ms; no event-loop block on either keystroke)
- **AND** subsequent `n` cycles back to mDNS reuse the same poller (no re-instantiate)

### Requirement: BonjourPoller socket setup SHALL run off the asyncio event loop
The synchronous `Zeroconf(...)` constructor inside `BonjourPoller._start_browser` opens a UDP multicast socket and joins 224.0.0.251:5353; this can take 100 – 500 ms on macOS. `BonjourPoller.events()` SHALL invoke `_start_browser` via `asyncio.to_thread` (not inline) so the asyncio event loop continues serving the TUI while the multicast handshake completes.

#### Scenario: Poller initialisation does not block the event loop
- **WHEN** the consumer task awaits the first iteration of `BonjourPoller.events()`
- **THEN** the underlying `Zeroconf(InterfaceChoice.Default)` call runs on a worker thread
- **AND** the asyncio event loop continues to process scheduled tasks (BLE poller, footer refresh, keystrokes) while the multicast socket setup is in flight

### Requirement: A crashed consumer task SHALL be re-startable by a subsequent `n` press
If the Bonjour consumer task exits via an unexpected exception (anything other than `asyncio.CancelledError` / `GeneratorExit`), it SHALL call `BonjourPoller.stop()` and reset `App._mdns_poller` to `None` so that the lazy-init gate in `_ensure_mdns_poller` no longer believes a poller is alive. A subsequent transition from Wi-Fi to BLE or BLE to mDNS SHALL rebuild the poller and restart the consumer.

#### Scenario: Consumer task hits an unexpected exception
- **WHEN** `BonjourPoller.events()` raises an unexpected exception inside the consumer task
- **THEN** the consumer task stops the poller, clears `App._mdns_poller`, and exits
- **AND** the TUI does not crash
- **WHEN** the user later cycles back through wifi → BLE
- **THEN** `_ensure_mdns_poller` rebuilds a fresh `BonjourPoller` and starts a new consumer task
