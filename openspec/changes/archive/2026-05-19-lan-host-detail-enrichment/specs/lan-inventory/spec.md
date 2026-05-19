## MODIFIED Requirements

### Requirement: ICMP sweep SHALL use unprivileged `ping` with bounded concurrency and per-host timeout
The poller SHALL invoke `ping -c 1 -W <ms>` per IP via `asyncio.create_subprocess_exec`, with concurrency bounded by a single `asyncio.Semaphore(30)` shared across all sweep tasks. The per-host wait is the existing `<ms>` argument to `ping`; default 200 ms. Total wall-clock for a /24 sweep at 30-way concurrency SHALL be under 12 seconds under healthy conditions; a /22 sweep SHALL be under 40 seconds.

`_ping_one(ip, timeout_ms)` SHALL return `tuple[bool, float | None]` — `(reachable, rtt_ms)` — by parsing the `time=X.XXX ms` line from macOS `ping`'s stdout. When `ping` exits 0 and stdout contains a parseable RTT, the tuple is `(True, <rtt>)`. When `ping` exits 0 but stdout doesn't parse, the tuple is `(True, None)` — host is reachable but RTT was unparseable. When `ping` exits non-zero, the tuple is `(False, None)`.

`_sweep(hosts)` SHALL return `dict[str, tuple[bool, float | None]]` mapping each IP to its `(reachable, rtt_ms)` result, so the merge step can populate per-host RTT and reachability fields without re-running per-host probes.

The poller SHALL NEVER:
- open a raw socket
- perform TCP / UDP probes beyond ICMP echo
- send malformed packets
- perform port scanning, SSDP / UPnP probing, NetBIOS queries, or banner grabbing

#### Scenario: Concurrent ping sweep
- **WHEN** the sweep starts on a /24
- **THEN** at most 30 `ping` subprocesses are alive simultaneously; the remaining tasks block on the semaphore until a slot frees

#### Scenario: Per-host budget cap
- **WHEN** a host is silent and does not respond within 200 ms
- **THEN** the `ping` exits non-zero and the host is recorded as `(False, None)` in the sweep result dict (and still leaves an ARP-incomplete entry in the kernel cache, which is skipped by the parser)

#### Scenario: Healthy ping yields RTT
- **WHEN** a host responds within 200 ms and ping's stdout contains `time=2.439 ms`
- **THEN** the sweep result for that IP is `(True, 2.439)`

#### Scenario: Ping succeeds but stdout doesn't parse
- **WHEN** `ping` exits 0 but stdout does not contain a parseable `time=X ms` segment (locale quirk, unusual build)
- **THEN** the sweep result is `(True, None)` — the boolean preserves the reachable signal while RTT is recorded as unknown

### Requirement: Each tracked host SHALL be a `LANHost` keyed by lowercase MAC, with vendor / hostname / Bonjour cross-reference fields
`LANHost` SHALL be a `@dataclass(frozen=True, slots=True)` with at minimum:

- `mac: str` (lowercase, colon-separated)
- `ip: str` (IPv4 dotted)
- `vendor: str | None` (resolved via the existing OUI map at `src/diting/data/wifi_ouis.json`)
- `hostname: str | None` (from `socket.gethostbyaddr`, wrapped in `asyncio.to_thread` with a 500 ms timeout)
- `bonjour_name: str | None` (from the current `BonjourPoller` state map's `host` field for the matching IP)
- `bonjour_services: tuple[str, ...]` (category names of every Bonjour service announced from the matching IP)
- `first_seen: datetime` (set on first observation of the MAC in this session; preserved across IP changes)
- `last_seen: datetime` (updates on every observation)
- `last_rtt_ms: float | None` (RTT of the most recent successful ICMP echo for this host's current IP, in milliseconds; `None` until the host has responded to ICMP at least once)
- `last_reachable_at: datetime | None` (UTC timestamp of the most recent successful ICMP echo; `None` until the host has responded at least once. Distinct from `last_seen`, which tracks ARP cache entries, including stale ones.)
- `is_gateway: bool` (true when `ip == Connection.router_ip`)
- `is_self: bool` (true when `mac == Connection.interface_mac`)
- `is_randomised_mac: bool` (true when bit 0x02 of the first octet is set — the IEEE "locally administered" bit)

The state map SHALL be keyed by `mac.lower()`. When the same MAC reappears at a new IP (DHCP rotation), the entry SHALL update the IP field in place while preserving `first_seen`. `last_rtt_ms` and `last_reachable_at` SHALL be preserved across sweeps that don't get an ICMP reply for the host — a temporarily silent host's last-known RTT stays visible in the modal until the next successful ping replaces it.

#### Scenario: First observation of a host that responded to ICMP
- **WHEN** a MAC ↔ IP pair lands in state for the first time this session AND the sweep got an ICMP reply with RTT 2.4 ms
- **THEN** `first_seen` and `last_seen` are set to `now`, `last_rtt_ms=2.4`, `last_reachable_at=now`

#### Scenario: First observation of a host that did NOT respond to ICMP
- **WHEN** a MAC ↔ IP pair lands in state for the first time (kernel ARP cache had it from earlier; the sweep got no reply)
- **THEN** `last_rtt_ms=None`, `last_reachable_at=None` — the user can see in the modal that diting has not seen a ping reply for this host yet this session

#### Scenario: Known host goes silent for one sweep
- **WHEN** a host responded with RTT 2.4 ms on tick N (so `last_rtt_ms=2.4`, `last_reachable_at=<then>`) but did not respond on tick N+1
- **THEN** on tick N+1 the entry's `last_rtt_ms` and `last_reachable_at` SHALL be preserved unchanged — `last_seen` advances if the ARP cache still has the entry, but reachable-only fields stay frozen at the last successful ping

#### Scenario: DHCP IP rotation for a known MAC
- **WHEN** an existing tracked MAC is observed at a new IP
- **THEN** the `LANHost` entry's `ip` field updates, `last_seen=now`, `first_seen` is unchanged; `last_rtt_ms` / `last_reachable_at` carry over (the RTT was measured against the previous IP, but the host identity — its MAC — is the same and the field is informative)

#### Scenario: Locally-administered MAC
- **WHEN** a MAC begins with a first octet whose bit 0x02 is set (e.g. `02:11:22:…`, `aa:11:22:…`)
- **THEN** `is_randomised_mac=True`; vendor lookup SHALL return `None` (these MACs aren't in the IEEE registry)
