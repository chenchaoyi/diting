## Why

diting today shows what's *near* you in three radio dimensions
(Wi-Fi APs, BLE peers, mDNS announcers). It does not show
**what's on your local IP subnet** — the actual list of hosts
the user means when they say "who's on my Wi-Fi". A laptop
on the LAN can answer this from the kernel ARP cache plus an
unprivileged ICMP / ARP sweep; no router admin login is needed.

Adding this capability closes the most common "who is that?"
question and slots cleanly between the existing Wi-Fi (radio
neighbours) and Bonjour (service announcers) views: the LAN
panel is L3 reachability + L2 identity, with the existing
Bonjour state cross-referenced as the friendly-name source
when available.

Detailed design is already in
[`docs/explainers/lan-inventory-arp.md`](../../../docs/explainers/lan-inventory-arp.md).
This proposal scopes the **MVP** out of that design.

## What Changes

### `lan-inventory` (new capability)

A new `LANInventoryPoller` (`src/diting/lan.py`) periodically
discovers every host on the local /24 subnet and emits
`LANInventoryUpdate` snapshots on its async-iterator interface.
Each tracked host is a `LANHost` keyed by lowercase MAC.

- **ADDED:** the poller SHALL derive the subnet from the
  active interface's IPv4 + netmask (via `socket`-level
  inspection, no shell-out) at start, default-prefixing to
  /24 around `iface_ip` when the netmask is wider (we never
  sweep more than 256 hosts in one pass under the default
  configuration). When the env var `DITING_LAN_INVENTORY_WIDE=1`
  is set, the cap relaxes to /22 (up to 1022 hosts); the cap
  is still enforced at /22 — wider netmasks are still
  truncated.
- **ADDED:** every snapshot tick (default cadence `60 s`,
  configurable, with a `force_now()` for the `r` key) the
  poller SHALL run a parallel ICMP ping sweep against every
  IP in the subnet (concurrency ≤ 30 via `asyncio.Semaphore`,
  per-host timeout 200 ms via `ping -c 1 -W <ms>`) and then
  read the kernel ARP cache via `arp -an`.
- **ADDED:** for each MAC ↔ IP pair, the poller SHALL resolve
  the vendor from the existing OUI map
  (`src/diting/data/wifi_ouis.json`), attempt reverse DNS via
  `socket.gethostbyaddr` (wrapped in `asyncio.to_thread`, 500
  ms timeout), and cross-reference the IP against the current
  `BonjourPoller` state map to pull a `bonjour_name` and
  `bonjour_services` tuple.
- **ADDED:** `LANHost` SHALL be a `@dataclass(frozen=True,
  slots=True)` with at minimum `mac`, `ip`, `vendor`,
  `hostname`, `bonjour_name`, `bonjour_services: tuple[str, ...]`,
  `first_seen`, `last_seen`, `is_gateway`, `is_self`. Locally-
  administered (random) MACs SHALL be flagged with
  `is_randomised_mac: bool` (bit 0x02 of the first octet) so
  the renderer can label them.
- **ADDED:** the capability SHALL be enabled by default and
  follow the existing lazy-construction pattern: the
  `LANInventoryPoller` is constructed the first time the
  user cycles into the LAN view (third `n` press), mirroring
  how `BLEPoller` and `BonjourPoller` start lazily. Users who
  never enter the view pay zero cost; users who do, see the
  panel populate within ~10 s of healthy /24 sweep wall-clock.
- **ADDED:** the poller SHALL NOT perform port scanning,
  SSDP / UPnP probing, NetBIOS queries, TCP banner grabs, or
  any active probe beyond the ICMP echo described above.
  These remain documented out-of-scope; adding any of them
  MUST file a new ADDED Requirement.

### `tui-shell` — fourth view in the `n` cycle

- **MODIFIED:** the `n` keystroke SHALL cycle through four
  views: Wi-Fi → BLE → Bonjour → LAN → Wi-Fi. The fourth
  view's panel header is `LAN`. The footer's view-toggle
  label SHALL show the *next* view target as today.
- **MODIFIED:** when the active view is `lan`, the third-slot
  panel SHALL render a vendor / name / services-mdns / IP /
  MAC / last-seen column table sorted by IP ascending. Hosts
  flagged `is_self` SHALL pin to the top with a `★`
  indicator; `is_gateway` SHALL pin second. Before the first
  snapshot lands (within ~10 s of view entry), the panel
  shows a single dim-italic line `(sweeping subnet…)` (EN) /
  `(正在扫描子网…)` (ZH).
- **MODIFIED:** the Diagnostics panel SHALL gain an mDNS-
  style summary line when the active view is `lan`:
  `LAN inventory  17 hosts  ·  4 named (Bonjour)  ·  2 unknown vendor  ·  subnet 192.168.1.0/24  ·  last sweep 8s ago`.
  When the optional wide-sweep env var
  `DITING_LAN_INVENTORY_WIDE=1` is set AND the netmask is
  wider than /24, the line also surfaces `· capped from /N`
  to make the truncation explicit.
- **ADDED:** pressing `i` on a row in the LAN view opens a
  `LANDetailScreen` modal showing IP / MAC / vendor /
  hostname / first seen / last seen / Bonjour service list
  with categories / cross-references to the Wi-Fi BSSID and
  Bonjour host where applicable. Close keys are the same as
  the other modals: `Esc`, `i`, `q`.

## Out of Scope

The following items are documented in the design explainer
but explicitly NOT in this MVP. Each gets its own future
change proposal if pursued:

- SSDP / UPnP M-SEARCH (would discover game consoles, smart
  TVs, media renderers that don't speak mDNS).
- NetBIOS / LLMNR queries (still on legacy Windows boxes).
- TCP banner grabbing (crosses into active port-scanning
  territory; opt-in-within-opt-in if ever done).
- Passive ARP listening via tcpdump subprocess.
- IPv6 NDP discovery (we focus on IPv4 first).
- "New device joined" alerts (requires persistent storage
  across diting restarts; not a foreground-TUI concern).
- 24/7 monitoring from a Pi-class sidecar — that's the
  separate edge-hardware roadmap entry.

## Migration / Defaults

This is purely additive. The `n` cycle gains a fourth stop,
but pressing `n` from any current view still works the same
way it did. The LAN poller starts lazily on first entry to
the LAN view, mirroring the existing Bonjour pattern — users
who never enter the view pay zero cost.

Power users on wider home networks can opt into a /22
sweep via `DITING_LAN_INVENTORY_WIDE=1`. The default /24
sweep is harmless on home networks (~3-10 s wall-clock,
30-way concurrency) and is consistent with diting's
existing "active probes default on" precedent (Wi-Fi scan,
mDNS query).
