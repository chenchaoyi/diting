## MODIFIED Requirements

### Requirement: ICMP sweep SHALL use unprivileged `ping` with bounded concurrency and per-host timeout
The poller SHALL invoke `ping -c 1 -W <ms>` per IP via `asyncio.create_subprocess_exec`, with concurrency bounded by a single `asyncio.Semaphore(30)` shared across all sweep tasks. The per-host wait is the existing `<ms>` argument to `ping`; default 200 ms. Total wall-clock for a /24 sweep at 30-way concurrency SHALL be under 12 seconds under healthy conditions; a /22 sweep SHALL be under 40 seconds.

`_ping_one(ip, timeout_ms)` SHALL return `tuple[bool, float | None, int | None]` — `(reachable, rtt_ms, ttl)` — by parsing the `time=X.XXX ms` and `ttl=N` segments from macOS `ping`'s stdout. When `ping` exits 0 and stdout contains both, the tuple is `(True, <rtt>, <ttl>)`. Missing segments SHALL be tolerated as None on their respective slot; the boolean reflects exit code only.

`_sweep(hosts)` SHALL return `dict[str, tuple[bool, float | None, int | None]]` mapping each IP to its `(reachable, rtt_ms, ttl)` result.

The poller SHALL NEVER:
- open a raw socket
- send malformed packets
- perform TCP port scanning or banner grabbing

The poller MAY, when permitted by the active scene's `lan_active_probe` knob (or by the public-scene one-shot override flow), emit UDP probes for the explicitly-enumerated active-discovery protocols defined under the active-discovery requirements (NBNS UDP 137 unicast, SSDP UDP 1900 multicast, mDNS UDP 5353 multicast).

#### Scenario: Concurrent ping sweep
- **WHEN** the sweep starts on a /24
- **THEN** at most 30 `ping` subprocesses are alive simultaneously; the remaining tasks block on the semaphore until a slot frees

#### Scenario: Per-host budget cap
- **WHEN** a host is silent and does not respond within 200 ms
- **THEN** the `ping` exits non-zero and the host is recorded as `(False, None, None)` in the sweep result dict

#### Scenario: Healthy ping yields RTT and TTL
- **WHEN** a host responds within 200 ms and ping's stdout contains `time=2.439 ms` and `ttl=64`
- **THEN** the sweep result for that IP is `(True, 2.439, 64)`

#### Scenario: Ping succeeds but TTL doesn't parse
- **WHEN** `ping` exits 0, stdout has `time=2.4 ms` but no `ttl=N` segment
- **THEN** the sweep result is `(True, 2.4, None)`

### Requirement: Each tracked host SHALL be a `LANHost` keyed by lowercase MAC, with vendor / hostname / Bonjour cross-reference fields
`LANHost` SHALL be a `@dataclass(frozen=True, slots=True)` with at minimum:

- `mac: str` (lowercase, colon-separated)
- `ip: str` (IPv4 dotted)
- `vendor: str | None` (normalised display name, the output of `_normalize_vendor()` over the raw IEEE registry entry; resolved via the multi-tier OUI map — MA-S 36-bit, MA-M 28-bit, MA-L 24-bit, longest-prefix wins)
- `vendor_raw: str | None` (the raw IEEE registry string before normalisation; surfaced in the detail modal so the user can reconcile odd normalisations)
- `hostname: str | None` (from `socket.gethostbyaddr`, wrapped in `asyncio.to_thread` with a 500 ms timeout)
- `bonjour_name: str | None` (from the current `BonjourPoller` state map's `host` field for the matching IP)
- `bonjour_services: tuple[str, ...]` (category names of every Bonjour service announced from the matching IP)
- `nbns_name: str | None` (NetBIOS Status Response WORKSTATION name — only populated when active probing was enabled and the host replied to a Status Query)
- `upnp_server: str | None` (the SSDP `SERVER:` header verbatim — only populated when M-SEARCH was sent and the host replied)
- `upnp_friendly_name: str | None` (from the LOCATION XML `<friendlyName>` element — only populated when `DITING_LAN_UPNP_FETCH=1` and the fetch succeeded)
- `upnp_model: str | None` (from the LOCATION XML `<modelName>` element)
- `first_seen: datetime` (set on first observation of the MAC in this session; preserved across IP changes)
- `last_seen: datetime` (updates on every observation)
- `last_rtt_ms: float | None` (RTT of the most recent successful ICMP echo for this host's current IP)
- `last_reachable_at: datetime | None` (UTC timestamp of the most recent successful ICMP echo)
- `ttl: int | None` (raw IP TTL from the most recent successful ICMP echo; `None` until the host has responded once)
- `ttl_class: str | None` (one of `"unix"` for TTL ≈ 64, `"windows"` for ≈ 128, `"router"` for ≈ 255, or `None`)
- `device_class: str | None` (output of the device-class inference rules — one of `phone | laptop | desktop | tv | camera | smart-home | printer | nas | gaming | speaker | router`, or `None` when no rule fires)
- `is_gateway: bool`
- `is_self: bool`
- `is_randomised_mac: bool`

The state map SHALL be keyed by `mac.lower()`. DHCP rotation, RTT preservation, and other invariants from prior phases SHALL be preserved unchanged.

The new fields SHALL all default to `None` / empty when their source signal is unavailable; they are additive enrichments and SHALL NOT block a `LANHost` from being instantiated.

#### Scenario: First observation of a host that responded to ICMP
- **WHEN** a MAC ↔ IP pair lands in state for the first time this session AND the sweep got an ICMP reply with RTT 2.4 ms and TTL 64
- **THEN** `first_seen` and `last_seen` are set to `now`, `last_rtt_ms=2.4`, `last_reachable_at=now`, `ttl=64`, `ttl_class="unix"`

#### Scenario: NBNS / UPnP / mDNS not run for this host
- **WHEN** active probing was disabled for the current scene
- **THEN** the host's `nbns_name`, `upnp_server`, `upnp_friendly_name`, `upnp_model` are all `None`; the host still appears in the state map with vendor + Bonjour fields populated

#### Scenario: Locally-administered MAC
- **WHEN** a MAC begins with a first octet whose bit 0x02 is set (e.g. `02:11:22:…`)
- **THEN** `is_randomised_mac=True`; `vendor`/`vendor_raw` are both `None`

## ADDED Requirements

### Requirement: OUI vendor lookup SHALL use a multi-tier MA-L / MA-M / MA-S registry with longest-prefix wins
diting SHALL bundle three OUI registry files under `src/diting/data/`:

- `wifi_ouis.json` — IEEE MA-L (24-bit prefix), the existing file.
- `wifi_ouis_ma_m.json` — IEEE MA-M (28-bit prefix) sub-allocations.
- `wifi_ouis_ma_s.json` — IEEE MA-S (36-bit prefix) sub-allocations.

`load_ouis_layered()` SHALL return a tuple `(ma_l, ma_m, ma_s)` of three dicts. `lookup_oui_vendor(mac, *, ma_l, ma_m, ma_s)` SHALL try, in order, the 36-bit MA-S key, then the 28-bit MA-M key, then the 24-bit MA-L key. First match wins. Missing files or unreadable JSON SHALL be tolerated (yield an empty dict for that tier).

#### Scenario: MA-S sub-allocation matches before MA-L
- **WHEN** a MAC's 36-bit prefix is registered in MA-S to a specific IoT vendor AND its 24-bit prefix is registered in MA-L to a white-label OEM
- **THEN** `lookup_oui_vendor()` returns the MA-S vendor name, not the MA-L OEM

#### Scenario: Only MA-L matches
- **WHEN** a MAC's 36-bit and 28-bit prefixes are not registered, but its 24-bit prefix is
- **THEN** `lookup_oui_vendor()` returns the MA-L vendor name

#### Scenario: No tier matches
- **WHEN** none of the three tiers has the prefix registered
- **THEN** `lookup_oui_vendor()` returns `None`

#### Scenario: Tier file missing or unreadable
- **WHEN** `wifi_ouis_ma_s.json` is absent from the bundled `data/` directory
- **THEN** `load_ouis_layered()` returns `(ma_l_dict, ma_m_dict, {})`; lookup degrades gracefully through the remaining tiers

### Requirement: Vendor names SHALL be normalised for display
After the multi-tier lookup returns a raw IEEE registry string, the LAN poller SHALL apply `_normalize_vendor(name)`:

- Strip trailing tokens `CO.`, `CO.,LTD`, `CO., LTD`, `CORPORATION`, `CORP`, `LTD`, `LTD.`, `INC`, `INC.`, `GMBH`, `LLC`, `B.V.`, `S.A.`, `LIMITED`, `COMPANY`, `TECHNOLOGIES`, `TECHNOLOGY`, `ELECTRONICS`, `ELECTRONIC`.
- Strip leading geographic prefixes `SHENZHEN `, `HANGZHOU `, `BEIJING `, `SHANGHAI `, `GUANGZHOU `.
- Titlecase the remainder while preserving acronyms enumerated in `_ACRONYM_OVERRIDES` (at minimum: `HP`, `IBM`, `ASUS`, `H3C`, `TP-Link`, `D-Link`, `LG`).
- Truncate to 16 grapheme cells (matching `_COL_LAN_VENDOR`).

The raw IEEE string SHALL be preserved on `LANHost.vendor_raw` so the detail modal can surface both forms.

#### Scenario: Long Chinese vendor name
- **WHEN** the IEEE registry returns `"SHENZHEN BILIAN ELECTRONIC CO.,LTD"`
- **THEN** `_normalize_vendor()` returns `"Bilian"` (or similar — first non-stripped, non-prefix token, titlecased)

#### Scenario: Acronym preserved
- **WHEN** the IEEE registry returns `"NEW H3C TECHNOLOGIES CO., LTD"`
- **THEN** `_normalize_vendor()` returns `"New H3C"`; the `H3C` token is not titlecased to `H3c`

#### Scenario: Detail modal shows both forms
- **WHEN** the detail modal renders the Vendor row
- **THEN** the displayed normalized form is the primary value; the raw IEEE string is rendered in a `dim` style on a continuation line for reference

### Requirement: The poller SHALL perform scene-gated active discovery when `scene_defaults(scene)["lan_active_probe"]` is true
When the active scene's `lan_active_probe` knob is true (or the env override `DITING_LAN_PROBE=1` is set, regardless of scene), the LAN poller SHALL emit, on each sweep tick after the ICMP/ARP merge completes, three additional probe phases:

1. **NBNS Name Query** — for each host with no `bonjour_name` and no `hostname`, send a NetBIOS Status Query (UDP 137 unicast) and listen up to 100 ms for the Status Response; parse the name table; store the WORKSTATION (`0x00`) name as `LANHost.nbns_name`. Concurrency capped at 30 via shared semaphore. Total phase budget ≤ 1 s for a /24.
2. **SSDP M-SEARCH** — send one `M-SEARCH * HTTP/1.1` request to `239.255.255.250:1900` with `ST: ssdp:all`, `MX: 2`. Listen 3 s for responses. Parse each response's `SERVER:` header into `LANHost.upnp_server`. When `DITING_LAN_UPNP_FETCH` is `1` (default), HTTP-GET the response's `LOCATION:` URL with a 500 ms timeout and a 4 KB response cap, parse `<friendlyName>` and `<modelName>` from the XML using stdlib `xml.etree.ElementTree` with external-entity resolution disabled, and store as `LANHost.upnp_friendly_name` / `LANHost.upnp_model`.
3. **Active mDNS browse query** — `BonjourPoller.send_meta_query()` SHALL send one mDNS query for the meta-service record `_services._dns-sd._meta._tcp.local`. Responses are captured through the existing passive listener.

When `lan_active_probe` is false AND `DITING_LAN_PROBE` is unset (or `0`), NONE of the three phases SHALL run; the sweep tick completes after the ARP merge as before, and the active-discovery fields on `LANHost` remain `None`.

The three phases SHALL be implemented in a new module `src/diting/lan_probes.py` and called from the existing `_do_sweep_and_emit()` method in `lan.py`. The probes SHALL fail-soft: any exception during a single host's NBNS query or the SSDP M-SEARCH listener SHALL be swallowed (logged at debug level if a debug logger is present), and the next sweep tick SHALL proceed normally.

#### Scenario: Home scene runs all three active phases
- **WHEN** active scene is `home` AND `DITING_LAN_PROBE` is unset
- **THEN** each sweep tick emits NBNS unicast queries to silent hosts, one M-SEARCH multicast, and one mDNS meta-query; collected enrichments land on the next `LANInventoryUpdate`

#### Scenario: Public scene skips all three active phases
- **WHEN** active scene is `public` AND `DITING_LAN_PROBE` is unset AND no one-shot override armed
- **THEN** no NBNS / SSDP / mDNS-meta packets are emitted; the sweep cycle uses only ICMP echo and ARP read

#### Scenario: Env override forces active probing in public
- **WHEN** active scene is `public` AND `DITING_LAN_PROBE=1`
- **THEN** active probes run every sweep, same as home

#### Scenario: Env override forces off in office
- **WHEN** active scene is `office` AND `DITING_LAN_PROBE=0`
- **THEN** no active probes run; behaviour matches public default

#### Scenario: NBNS-only enrichment
- **WHEN** a Windows host with no Bonjour publication replies to NBNS with name `LAB-PRINTER-01`
- **THEN** the corresponding `LANHost.nbns_name = "LAB-PRINTER-01"`; the row's Name column shows `LAB-PRINTER-01`

#### Scenario: UPnP fetch disabled
- **WHEN** `DITING_LAN_UPNP_FETCH=0` and active probing is otherwise on
- **THEN** M-SEARCH still runs and `upnp_server` is populated, but `upnp_friendly_name` / `upnp_model` remain `None` (no HTTP fetch of the LOCATION URL)

#### Scenario: UPnP LOCATION fetch hits a malicious server
- **WHEN** a response's `LOCATION:` URL points to an attacker-controlled host serving a 10 MB XML
- **THEN** the fetch is aborted after 4 KB; the `xml.etree.ElementTree` parse runs with external-entity resolution disabled; failure leaves `upnp_friendly_name`/`upnp_model` as `None`

#### Scenario: Probe phase fails-soft
- **WHEN** the SSDP socket bind fails with `EADDRINUSE`
- **THEN** the SSDP phase is skipped for this tick; NBNS and mDNS phases still run; an inventory snapshot is still emitted

### Requirement: Public scene SHALL provide a one-shot user-consent override that triggers active discovery for one sweep tick
When the active scene is `public` AND `DITING_LAN_PROBE` is unset, the LAN view SHALL bind the uppercase `P` key to a confirmation flow:

1. Pressing `P` pushes a `LANProbeConsentScreen` modal that displays:
   - Current scene + connected SSID.
   - Enumeration of the exact packets that will be sent: `NBNS UDP 137 unicast`, `SSDP M-SEARCH UDP 1900 multicast`, `mDNS UDP 5353 multicast`.
   - The consequences statement (other guests' devices receive the probes; IDS may flag; captive portal may rate-limit).
   - A statement that the probe is one-shot.
2. The confirm key (`y`) SHALL be inactive for the first 2 seconds the modal is open. After the cooldown elapses, the footer text changes from "(wait 2s)" to "(y to probe)".
3. On confirm, the poller's `_one_shot_probe_armed` flag SHALL be set to True. The next sweep tick (which can be forced immediately via the same code path as `force_now()`) runs the three active-discovery phases once and then clears the flag. Subsequent sweeps revert to passive behaviour.
4. A `LANActiveProbeConsentedEvent` SHALL be written to the JSONL event log at the moment of confirmation, capturing the at-time scene, SSID, and packet counts that will be sent.
5. There SHALL be no "remember my choice" or sticky toggle. Re-pressing `P` re-opens the modal and re-confirms.

#### Scenario: Public-scene user confirms one-shot probe
- **WHEN** active scene is `public` AND the user presses `P` AND waits 2 s AND presses `y`
- **THEN** a `LANActiveProbeConsentedEvent` is appended to the JSONL log; the next sweep tick runs NBNS + SSDP + mDNS-meta once; subsequent sweep ticks return to passive

#### Scenario: Cooldown prevents press-through
- **WHEN** the user presses `P` and immediately presses `y` within 500 ms
- **THEN** the `y` keypress is ignored; no event is logged; no probe runs; the modal footer still reads "(wait 2s)"

#### Scenario: Cancel during cooldown
- **WHEN** the user presses `P` and then `esc` before the cooldown elapses
- **THEN** the modal closes; no event is logged; no probe runs

#### Scenario: Re-confirm required each press
- **WHEN** the user has confirmed one probe; sweep completes; user presses `P` again
- **THEN** the modal opens again from scratch with the full 2 s cooldown; the user must confirm a second time to run a second one-shot probe

#### Scenario: P binding inactive when probing is already on
- **WHEN** active scene is `home` (or `DITING_LAN_PROBE=1` is set in any scene)
- **THEN** the `P` key SHALL be a no-op on the LAN view — the override only makes sense when probing is otherwise off

### Requirement: Each `LANHost` SHALL carry a TTL fingerprint class derived from its most recent ICMP TTL
After `_ping_one()` records the IP TTL, the merge step SHALL set `LANHost.ttl` to the integer value and SHALL set `LANHost.ttl_class` according to the following table:

| Observed TTL range | `ttl_class` |
|---|---|
| 50 ≤ TTL ≤ 64 | `"unix"` |
| 100 ≤ TTL ≤ 128 | `"windows"` |
| 200 ≤ TTL ≤ 255 | `"router"` |
| anything else, or None | `None` |

The TTL class is **presentational** — incorrect classification does NOT affect events, the analyzer, or JSONL exports beyond the `ttl_class` field itself.

#### Scenario: macOS host TTL is 64
- **WHEN** a host responds with TTL 64
- **THEN** `ttl_class = "unix"`

#### Scenario: Windows host TTL is 128
- **WHEN** a host responds with TTL 128
- **THEN** `ttl_class = "windows"`

#### Scenario: TTL decremented by router hop
- **WHEN** a host two hops away responds with TTL 62 (decremented from 64)
- **THEN** `ttl_class = "unix"` (the 50–64 range absorbs single-digit hop decrements)

#### Scenario: TTL out of range
- **WHEN** a host responds with an unusual TTL value like 90
- **THEN** `ttl_class = None`

### Requirement: Each `LANHost` SHALL carry an inferred device class
A new module `src/diting/lan_classify.py` SHALL expose `classify(host: LANHost) -> str | None`. The function SHALL apply a documented rules table over the host's fields (`vendor_raw`, `bonjour_services`, `nbns_name`, `upnp_server`, `upnp_friendly_name`, `ttl_class`, `is_gateway`, `is_self`) and return the first matching class or `None`.

Classes SHALL be exactly one of: `phone | laptop | desktop | tv | camera | smart-home | printer | nas | gaming | speaker | router`.

The classifier SHALL be a pure function over `LANHost` (no I/O, no global state) and SHALL NOT raise on any combination of input fields.

The merge step SHALL call `classify()` for every `LANHost` it constructs and assign the result to `LANHost.device_class`.

The classifier output is **presentational** — incorrect classification does NOT affect events, the analyzer, or JSONL exports beyond the `device_class` field itself.

#### Scenario: AirPrint Bonjour signals printer
- **WHEN** a host has `bonjour_services` containing `"AirPrint"`
- **THEN** `classify()` returns `"printer"`

#### Scenario: UPnP server header signals TV
- **WHEN** a host has `upnp_server` matching `/smarttv|hisense|samsung-tv|lge-tv/i`
- **THEN** `classify()` returns `"tv"`

#### Scenario: Hikvision / Dahua / Axis vendor signals camera
- **WHEN** a host has `vendor_raw` matching one of `hikvision`, `dahua`, `axis communications`, `tapo`, `imou` (case-insensitive)
- **THEN** `classify()` returns `"camera"`

#### Scenario: Tuya / Xiaomi smart-home gateway signals smart-home
- **WHEN** a host has `vendor_raw` matching `tuya`, `xiaomi`, `aqara`, or `mijia` (case-insensitive) AND no signal pointing to phone / camera / printer
- **THEN** `classify()` returns `"smart-home"`

#### Scenario: Gateway flag wins router class
- **WHEN** a host has `is_gateway=True`
- **THEN** `classify()` returns `"router"` regardless of other fields

#### Scenario: No rule fires
- **WHEN** a host has only a randomised MAC and no Bonjour / NBNS / UPnP signal
- **THEN** `classify()` returns `None`

### Requirement: The poller SHALL emit `LANActiveProbeConsentedEvent` only when the public-scene one-shot override confirms
`LANActiveProbeConsentedEvent` SHALL be appended to the JSONL log via the existing `EventLogger.append()` path. Fields:

- `timestamp: datetime` — moment of user confirmation
- `scene: str` — the at-time scene name (always `"public"` in this phase since the binding is public-only)
- `ssid: str | None` — the SSID of the currently-connected Wi-Fi
- `nbns_packets: int` — number of NBNS Status Queries that will be sent on the next sweep
- `ssdp_packets: int` — `1` (single M-SEARCH multicast)
- `mdns_packets: int` — `1` (single meta-query multicast)

The event SHALL NOT fire when active probing runs because of scene defaults or `DITING_LAN_PROBE=1` — it is specifically the "user accepted the public-scene risk" marker.

#### Scenario: Public-scene confirm fires event
- **WHEN** the user confirms the `P` modal in public scene
- **THEN** one `LANActiveProbeConsentedEvent` is appended with the at-time scene/SSID and the planned packet counts

#### Scenario: Home-scene probing does NOT fire event
- **WHEN** active scene is `home` and active probing runs as scheduled
- **THEN** no `LANActiveProbeConsentedEvent` is appended (those probes run silently; only the public-scene override is audited)
