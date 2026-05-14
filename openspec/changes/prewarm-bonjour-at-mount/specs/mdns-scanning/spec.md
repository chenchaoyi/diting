## MODIFIED Requirements

### Requirement: `zeroconf` dependency SHALL be lazy-imported at the module boundary and pre-warmed at TUI mount
`from zeroconf import ...` SHALL appear ONLY inside `src/diting/mdns.py` and SHALL be top-level inside that module (not function-local). `src/diting/tui.py` SHALL NOT `import diting.mdns` at module load.

The TUI SHALL trigger the first import of `diting.mdns` (and the construction of a `BonjourPoller`) at TUI mount — `App.on_mount` SHALL call `_ensure_mdns_poller()` after scheduling the other pollers. The pre-warm SHALL run on a worker (`run_worker` + `asyncio.to_thread` for the slow stages) so the visible Wi-Fi view renders immediately and the user's first ~5 s of reading the wifi panel amortises the zeroconf import + multicast socket setup. The `action_toggle_view` call into `_ensure_mdns_poller()` SHALL remain as an idempotent safety net but is a no-op once the mount-time prewarm has fired.

**Why mount-time instead of "first wifi → BLE"**: the PyInstaller-frozen binary's `PyiFrozenImporter` decompresses each imported module from a PYZ archive while holding the GIL throughout, so `asyncio.to_thread` cannot overlap the import with the event loop. The previous "first leaving Wi-Fi" trigger gave the frozen build only the ~2 s of BLE-view reading time to absorb a 1.5+ s import; with mount-time prewarm, the entire wifi-view dwell time is available. The source `uv run` build benefits too — the import overlaps with TUI initial paint instead of with a view switch.

#### Scenario: TUI mount kicks off the Bonjour prewarm
- **WHEN** the user launches the TUI
- **THEN** `App.on_mount` schedules a worker that imports `diting.mdns`, constructs a `BonjourPoller`, and begins the consumer task — all off the asyncio event loop
- **AND** the Wi-Fi panel renders immediately, with no perceptible pause attributable to Bonjour startup

#### Scenario: User cycles wifi → BLE → mDNS for the first time
- **WHEN** the user presses `n` once (wifi → BLE)
- **THEN** the BLE view appears immediately; the mount-time prewarm is either complete or in flight
- **WHEN** the user presses `n` a second time (BLE → mDNS)
- **THEN** the mDNS panel is shown immediately (the poller is ready since it has had the entire wifi-view dwell time to initialise)
- **AND** subsequent `n` cycles back to mDNS reuse the same poller (no re-instantiate)

#### Scenario: User never leaves Wi-Fi view
- **WHEN** the user runs `diting` and never presses `n`
- **THEN** zeroconf is still imported at mount (background worker), but no user-visible cost is incurred — the work happens concurrently with the user reading the wifi view
- **AND** no mDNS-related UI is shown
