# link-health Specification

## Purpose

Defines the contract for active link probing — how wifiscope measures
gateway / WAN reachability, latency, jitter, and loss bursts on the
user's current Wi-Fi connection. The events ring, the analyzer, and
the JSONL log all consume the same aggregates this capability
produces.

## Requirements

### ADDED Requirement: Probes SHALL hit the gateway via ICMP and the WAN via TCP/53
The poller SHALL run two parallel probe streams:

- **Gateway**: ICMP echo against the local gateway IP discovered from
  the Connection (e.g. `192.168.1.1`). Default cadence 1 s.
- **WAN**: TCP SYN against port 53 of the first non-gateway DNS server
  the system has configured. Default cadence 1 s.

ICMP requires no privileges on macOS; TCP/53 sidesteps the home-network
case where the gateway IS the only DNS server (in which case WAN
probing is silently skipped, see below).

#### Scenario: Standard home network
- **WHEN** the user is on a router at 192.168.1.1 with DNS 8.8.8.8
- **THEN** the poller pings 192.168.1.1 (ICMP) and probes 8.8.8.8:53 (TCP) once per second each

#### Scenario: Captive portal / no DNS
- **WHEN** SCDynamicStore returns no DNS addresses
- **THEN** WAN probing is skipped, the diagnostics row shows `WAN n/a`, and gateway probing continues

#### Scenario: DNS == gateway
- **WHEN** the only configured DNS address equals the gateway IP
- **THEN** WAN probing is skipped with reason "dns_eq_gateway", and the row shows `WAN n/a (DNS == gateway)`

### ADDED Requirement: Aggregates SHALL be computed over a rolling 60 s window
For each probe target the poller SHALL maintain a rolling window of
samples and produce a `LatencyAggregate` containing: median RTT
(`rtt_ms`), MAD jitter (`jitter_ms`), loss percentage (`loss_pct`,
0..100), sample count, target_ip, target label. The window SHALL
be 60 s by default. Stale samples SHALL be evicted by monotonic clock,
not wall clock — the poller SHALL not break across NTP adjustments
or sleep/wake cycles.

#### Scenario: Steady-state probing
- **WHEN** the user has been associated for 5 min with normal latency
- **THEN** the diagnostics row shows `Router 5 ms · 0% loss · WAN 16 ms · 0% loss · jitter 2 ms`

#### Scenario: Sleep/wake
- **WHEN** the Mac sleeps for 30 min and wakes
- **THEN** stale samples are correctly evicted by monotonic clock; the diagnostics row does not briefly show ancient pre-sleep latencies

### ADDED Requirement: Network change SHALL force a complete probe reset
The poller SHALL detect a network change via `NetworkChangeEvent`
(emitted whenever the gateway IP differs from the previous tick),
reset both probe targets, evict the in-flight sample buffer, and
re-resolve gateway / DNS from the new connection. The poller SHALL
NOT continue pinging the old gateway from the new network.

#### Scenario: Roam from home Wi-Fi to office Wi-Fi
- **WHEN** the user changes networks and `Connection.bssid` updates
- **THEN** the poller emits a `NetworkChangeEvent`, immediately resets gateway+WAN probes against the new `IP / Router` row, and the diagnostics latency briefly shows "…" before the first new sample arrives

### ADDED Requirement: Loss bursts and latency spikes SHALL fire as discrete events
The poller SHALL emit:

- `latency_spike`: when a single RTT sample exceeds 200 ms (gateway)
  or 500 ms (WAN)
- `loss_burst`: when ≥ 50 % of the rolling window's samples are lost
- `gateway_unreachable`: when 100 % of samples in the window failed
  for at least 10 consecutive seconds

These events feed the unified events ring, get logged to JSONL when a
log path is configured, and surface in the events strip footer.

#### Scenario: Brief gateway hiccup
- **WHEN** RTT spikes from 5 ms to 350 ms for one sample then recovers
- **THEN** one `latency_spike` event fires, gets timestamped, and shows in the events strip

#### Scenario: Cable yanked from router
- **WHEN** the gateway is unreachable for 15 seconds
- **THEN** a `gateway_unreachable` event fires and the link diagnostic row shows `WAN unreachable` in red

### ADDED Requirement: WAN-only outages SHALL be distinguishable from full link loss
Loss / spike events SHALL carry a `target` field (`gateway` or `wan`)
so consumers can tell "internet is broken but the AP is fine" apart
from "the AP itself is down". The diagnostics row SHALL render WAN
red separately from gateway red.

#### Scenario: ISP outage
- **WHEN** gateway probes succeed but WAN probes fail for 20 s
- **THEN** the row reads `Router 5 ms · 0% loss · WAN unreachable · jitter 2 ms`, with only WAN in red
