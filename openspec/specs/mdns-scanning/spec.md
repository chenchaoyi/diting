# mdns-scanning Specification

## Purpose
TBD - created by archiving change mdns-bonjour-discovery. Update Purpose after archive.
## Requirements
### Requirement: The `BonjourPoller` SHALL passively browse the well-known service-type list on the link-local mDNS multicast group
`BonjourPoller` SHALL subscribe via the Python `zeroconf` library's `ServiceBrowser` to a curated list of well-known service types (`_airplay._tcp`, `_raop._tcp`, `_googlecast._tcp`, `_sonos._tcp`, `_ipp._tcp`, `_ipps._tcp`, `_printer._tcp`, `_smb._tcp`, `_afpovertcp._tcp`, `_workstation._tcp`, `_hap._tcp`, `_homekit._tcp`, `_companion-link._tcp`, `_rfb._tcp`, `_ssh._tcp`, `_http._tcp`, `_https._tcp`, `_meshcop._udp`, `_matter._tcp`) maintained in `src/diting/data/bonjour_services.json`. The poller SHALL NOT browse the meta-type `_services._dns-sd._udp.local.` and SHALL NOT initiate any service-type discovery outside the curated list. The poller SHALL bind to all "up" network interfaces (the `zeroconf` library default) so the active Wi-Fi link and any other live interface produce announcements.

#### Scenario: AirPlay service announce captured
- **WHEN** an AppleTV on the same link emits an `_airplay._tcp` PTR / SRV / TXT announce
- **THEN** the poller's state map gains an entry keyed by `(service_type, instance_name)` with the announce's host, port, and TXT fields
- **AND** the next snapshot emitted by `BonjourPoller.events()` contains a corresponding `BonjourDevice`

#### Scenario: Unknown service type ignored
- **WHEN** a device on the link emits a `_my-vendor-custom._tcp` announce that is not in `bonjour_services.json`
- **THEN** the poller does NOT receive the event (because no browser is subscribed to that type)
- **AND** the snapshot list is unchanged

#### Scenario: No active probing across VLANs
- **WHEN** the poller starts up
- **THEN** it does NOT emit any unicast DNS queries to specific hosts
- **AND** it does NOT join the meta-discovery browse that would flood the link

### Requirement: `BonjourDevice` SHALL carry the announce-derived fields the panel renders
`BonjourDevice` SHALL be a frozen dataclass exposing these fields:

- `service_type: str` — the underscore-form type (e.g., `_airplay._tcp`).
- `name: str` — the service-instance name (e.g., `Living-Room-AppleTV`).
- `host: str | None` — the announced server (e.g., `Living-Room-AppleTV.local.`); None when the announce hasn't included one yet.
- `port: int | None` — the announced port.
- `addresses: tuple[str, ...]` — the announced IPv4 / IPv6 addresses (empty tuple if not yet resolved).
- `txt: dict[str, str]` — the parsed TXT record fields; UTF-8-decoded keys + values; binary-valued keys excluded.
- `vendor: str | None` — resolved via the chain in the next Requirement.
- `vendor_trace: str | None` — names which step of the resolution chain produced `vendor`. One of `txt-vendor`, `oui`, `hostname-pattern`, `service-type-hint`, or `None` when `vendor` is also `None`. Recorded by the resolver at the same time it produces `vendor`. Used by `bonjour-detail-modal` to annotate the Identity section so the user can see which signal won; used by maintainers to diagnose long-tail vendor-resolution gaps.
- `category: str | None` — the friendly service category from `bonjour_services.json` (e.g., `AirPlay` for `_airplay._tcp`); None for unknown types (cannot occur in v1 because unknown types are filtered out, but the field is included for forward-compatibility).
- `first_seen: datetime` — first announce observed (UTC).
- `last_seen: datetime` — most recent announce observed (UTC).

Field updates SHALL be applied per `(service_type, name)` key: a second announce for the same key updates `last_seen` and any newly-resolved field (addresses, port, TXT entries), but never replaces the device record.

#### Scenario: TXT record decoded UTF-8
- **WHEN** the announce includes a TXT entry `model=AppleTV3,2`
- **THEN** `BonjourDevice.txt["model"]` is the string `"AppleTV3,2"`

#### Scenario: Binary TXT field excluded
- **WHEN** the announce includes a TXT entry whose value bytes do not decode as UTF-8
- **THEN** that key is dropped from `BonjourDevice.txt`
- **AND** no exception propagates out of the parser

#### Scenario: vendor_trace records the winning chain step
- **WHEN** a device's vendor is resolved by the OUI step (step 2 of the chain)
- **THEN** `BonjourDevice.vendor_trace == "oui"`
- **AND** `BonjourDevice.vendor` is the non-None vendor name

#### Scenario: vendor_trace is None when the chain abstains
- **WHEN** all five steps abstain
- **THEN** both `BonjourDevice.vendor` and `BonjourDevice.vendor_trace` are `None`

### Requirement: `BonjourDevice.vendor` SHALL be resolved via a 5-step deterministic chain
The chain SHALL run in this order and SHALL return on the first step that produces a non-None vendor:

1. **TXT-record explicit field**: if `txt["vendor"]` or `txt["manufacturer"]` is present, that value is the vendor.
2. **OUI lookup**: if a TXT entry contains a MAC-formatted address (`xx:xx:xx:...`) OR a known MAC-bearing key (`deviceid`, `mac`), feed it through `ble.lookup_oui_vendor` and use the result.
3. **Hostname pattern**: feed `host` through the existing `_NAME_PATTERN_VENDORS` table in `ble.py` (`Apple-` / `HP-` / `Synology-` / `Sonos-` / `Roku-` patterns).
4. **Service-type vendor hint**: a small `_SERVICE_VENDOR_HINTS` table maps service types that uniquely identify a vendor (e.g., `_googlecast._tcp` → `Google`, `_sonos._tcp` → `Sonos`).
5. **Abstain**: return `None`.

#### Scenario: TXT vendor field wins
- **WHEN** a service announces `txt["vendor"] = "HomePod"`
- **AND** the hostname also matches the `Apple-` name pattern
- **THEN** `BonjourDevice.vendor == "HomePod"` (step 1 wins, step 3 never runs)

#### Scenario: Hostname pattern catches unbranded Apple device
- **WHEN** a service announces hostname `Macbook-Pro-2.local.` with no TXT vendor field and no MAC address
- **THEN** the chain falls through to step 3 and resolves vendor to `Apple, Inc.` via the `Macbook-` name pattern

#### Scenario: All steps abstain
- **WHEN** the announce has no TXT vendor, no MAC, an unrecognised hostname pattern, and an ambiguous service type (e.g., `_http._tcp` which any device may serve)
- **THEN** `BonjourDevice.vendor` is `None`
- **AND** the panel renders it as `(unknown)` / `(未知)`

### Requirement: The state map SHALL expire entries on `remove_service` callbacks AND fall back to a TTL when no remove is observed
The `ServiceListener` `remove_service` callback is the primary source of truth: when the library fires it, the entry SHALL be removed from the snapshot. As a backstop for devices that go offline without a graceful goodbye, the poller SHALL also expire entries whose `last_seen` is older than `_BROWSE_TTL_S` (default 60 seconds, exposed for tests).

#### Scenario: Graceful disappearance
- **WHEN** `zeroconf` fires `remove_service` for a previously-announced service instance
- **THEN** the next snapshot does NOT include that `BonjourDevice`

#### Scenario: Silent disappearance falls back to TTL
- **WHEN** a service stopped advertising 90 seconds ago and no `remove_service` was fired
- **AND** the `_BROWSE_TTL_S` default of 60 has elapsed
- **THEN** the entry is removed from the snapshot at the next interval

### Requirement: The `BonjourPanel` SHALL render the same vendor / name / services / age / id columns as the BLE panel
`BonjourPanel.compose()` SHALL build a `VerticalScroll` containing a `Static` body. The body SHALL render one row per `BonjourDevice` in `addresses`-then-name order, with columns (left to right): vendor (cyan when resolved, dim when `(unknown)`), name (white when present, dim italic when missing), service-category (cyan), age relative to "now" (dim), short id (first 8 chars of the service-instance name, dim). CJK column alignment SHALL use `pad_cells` / `fit_cells`.

There is NO RSSI column, NO signal-bar column, NO connected-vs-advertising split, NO history sparkline — the panel is simpler than `BLEPanel` because mDNS data doesn't carry signal-strength or per-device numeric series.

#### Scenario: AppleTV row rendered
- **WHEN** the panel receives a `BonjourDevice` with vendor=`Apple, Inc.`, name=`Living-Room-AppleTV`, category=`AirPlay`, last_seen 3 seconds ago
- **THEN** the row text contains `Apple, Inc.`, `Living-Room-AppleTV`, `AirPlay`, `3s`
- **AND** the columns are cell-aligned even when the user is running in ZH and a CJK character is present

#### Scenario: Unknown vendor row
- **WHEN** the panel receives a `BonjourDevice` whose vendor resolution chain abstained
- **THEN** the vendor cell renders as `(unknown)` / `(未知)` in dim style

### Requirement: The diagnostics panel SHALL surface an mDNS-side summary when the active view is `mdns`
When the user has the Bonjour view active, the Diagnostics panel SHALL replace its Wi-Fi-side lines with an mDNS summary:

1. **Visible Bonjour** — total service count + distinct service-type count.
2. **Top services** — three most-common service types with counts (e.g. `5 Apple Companion · 4 AirPlay · 4 AirPlay audio`).
3. **Top vendors** — three most-common vendor names with counts. The unknown-vendor bucket SHALL be rendered as `(unknown) N`, never as `? N`, to match the column placeholder used in the table and the same bucket's label in the BLE panel.
4. **Closest** — RSSI is not available on mDNS, so this line is omitted (BLE-only).

#### Scenario: User in mDNS view sees Bonjour diagnostics
- **WHEN** the user toggles to the `bonjour` view with 21 announces across 8 hosts
- **THEN** the diagnostics panel shows `Visible Bonjour 21 total · 7 service types`, `Top services …`, and `Top vendors …` rows

#### Scenario: Empty snapshot placeholder
- **WHEN** the user toggles to the `bonjour` view before any announce has arrived
- **THEN** the diagnostics panel shows a single dim-italic line `(listening for announces …)`

#### Scenario: Unknown-vendor bucket rendered with explicit label
- **WHEN** the snapshot has 16 announces from `Apple, Inc.` and 5 from devices whose vendor could not be resolved
- **THEN** the `Top vendors` line reads `Top vendors  16 Apple, Inc.  ·  (unknown) 5` — the literal `?` glyph SHALL NOT appear for this bucket

### Requirement: The poller SHALL clean up the underlying `zeroconf` resources on stop
`BonjourPoller.stop()` SHALL call `Zeroconf.close()` synchronously, joining any background threads the library started. The TUI's existing `on_unmount` SHALL invoke `BonjourPoller.stop()` alongside the existing `BLEPoller.stop()` call so processes exit cleanly without hanging.

#### Scenario: Clean shutdown
- **WHEN** the user quits the TUI with `q`
- **THEN** `BonjourPoller.stop()` is called
- **AND** the process exits within 1 second (no background threads keep it alive)

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

### Requirement: The `BonjourPanel` SHALL support a `by-host` sort mode in addition to the default service-row mode
The Bonjour panel SHALL accept two sort modes:

- `service` (default) — one row per `(host, service_type)` pair. Each row's services column carries a single service-type name. This is the historical behaviour.
- `by-host` — one row per `host`. The vendor / name / age / host columns reflect the host's most-recent service announce. The services column folds the host's services into a comma-joined string of the short service-type names (e.g. `AirPlay, AirPlay audio, Apple Companion, HomeKit`), in alphabetical order of the short name. Long folded lists SHALL be truncated to the column width with an ellipsis via `fit_cells` (no raw slicing — keep CJK-safe).

The user SHALL cycle between modes via the existing `s` keystroke. The cycle order is `service` → `by-host` → `service`. The border subtitle's `sort: <mode>` SHALL reflect the current mode.

The `service` mode is the default on TUI start. Switching modes does not refetch — both modes operate on the same `BonjourDevice` snapshot.

#### Scenario: User on Bonjour view presses `s`
- **WHEN** the view is `bonjour`, current sort is `service`, and the user presses `s`
- **THEN** the panel re-renders in `by-host` mode and the border subtitle reads `sort: by-host`

#### Scenario: User presses `s` again
- **WHEN** the view is `bonjour` and current sort is `by-host`
- **THEN** the panel re-renders in `service` mode and the border subtitle reads `sort: service`

#### Scenario: HomePod with four services
- **WHEN** in `by-host` mode and a host `Blue-Pod` has services `_airplay._tcp`, `_raop._tcp`, `_companion-link._tcp`, `_homekit._tcp`
- **THEN** the row's services column reads `AirPlay, AirPlay audio, Apple Companion, HomeKit` (alphabetically sorted short names, comma-joined)

#### Scenario: by-host mode collapses count
- **WHEN** in `service` mode the panel reports `21 services` from `8` hosts, then the user presses `s`
- **THEN** `by-host` mode shows `8` rows; the border subtitle's `Nearby Bonjour devices` count reflects the row count in the active mode

#### Scenario: Long services list truncates with ellipsis
- **WHEN** a host has 7 services and the joined string would overflow the column
- **THEN** the rendered string is truncated to the column width with a trailing `…` via `fit_cells`, never via raw `str` slicing

