<sub>**English** · [中文](../zh/explainers/lan-inventory-arp.md)</sub>

# "Who is on my Wi-Fi?" — technical design

A LAN-inventory feature answers **"which devices are connected to my
home network right now"** from a normal phone or laptop on the same
subnet — no router admin login required. This document is the detailed
design for that capability inside diting: a fourth panel listing every
host on the local subnet with vendor, hostname, and Bonjour
cross-reference, refreshed live.

We're not committing to ship this — it's the design we'd
implement when we decide to build it. The doc focuses on **what
we can actually observe from a Mac client** and where the limits are.

## What "see who's on the Wi-Fi" actually means

There are three different questions hiding in that phrase:

1. **Currently active on the LAN.** Has IP X, MAC Y, talked to
   something in the last minute. **Answerable from a normal
   client.** This is what we're scoping here.
2. **Currently associated to the AP.** The AP has it in its
   association table — may or may not be exchanging traffic.
   **Only the AP / router knows.** Out of scope.
3. **Has ever been associated.** Historical roster of every
   device that joined this network. **Only the router knows,
   and only since reboot / log retention.** Out of scope.

diting can answer (1) reasonably well on a home network. On a
corporate AP with client isolation enabled, none of the discovery
techniques below work — the AP drops all client-to-client
traffic at L2. That's a network policy, not a bug to fix.

## The discovery toolkit

Every observation technique we'd use is a passive or
unprivileged-active probe that any LAN client can perform.
Nothing here needs root, raw sockets, or router credentials.

### Layer 2: ARP cache + ICMP / ARP sweep

ARP is the bedrock. Every device on a /24 that wants to talk to
another device first broadcasts an "who has X.X.X.X?" ARP
request, and the answer (MAC↔IP) lands in the local cache:

```bash
$ arp -an
? (192.168.1.1) at aa:bb:cc:11:22:33 on en0 ifscope [ethernet]
? (192.168.1.42) at de:ad:be:ef:00:01 on en0 ifscope [ethernet]
? (192.168.1.55) at f4:5c:89:11:22:33 on en0 ifscope [ethernet]
```

This is **what we've talked to**, not what's alive on the network.
A device the Mac has never opened a connection to won't appear.

To enumerate everyone, do an **ICMP ping sweep** of the subnet
first, then read the ARP cache:

1. Derive the subnet from `ifconfig en0` (interface IP +
   netmask). Most home networks are /24 = 254 hosts to probe.
2. For each host, run `ping -c 1 -W 200 X.X.X.X` in parallel
   (asyncio task pool, ~30 concurrent). Each ping either gets
   an ICMP reply (host is alive) or times out (200 ms cap).
3. After the sweep, re-read `arp -an`. Every host that
   responded — even with "host unreachable" — leaves an ARP
   entry, because the *ARP request that preceded the ping*
   landed in the cache.

**Why ICMP ping and not pure ARP scan:** macOS's standard `ping`
binary is unprivileged. A pure ARP scan via raw sockets needs
root. ICMP-then-ARP gets the same result without asking for
privileges.

**Why not `nmap -sn`:** Same effect, third-party dependency we
don't need.

A full /24 sweep at 30-way concurrency finishes in ~2-3 seconds
under healthy conditions, ~10 s if many hosts are silent.

### Layer 2 fallback: passive ARP listening

ARP is an L2 broadcast — every "who has?" query reaches every
device on the segment. We can **passively listen** for these
broadcasts on the interface (`tcpdump arp` reads them, BPF
filter `ether proto 0x0806`). This catches devices that nobody
is currently talking to, **as long as they speak first**. Slow,
but free of network traffic on our end.

The fastest combo: ICMP sweep on a 60 s interval for ground
truth, plus passive ARP listening between sweeps for catch-up.

### Layer 3: OUI → vendor

Every MAC address starts with a 24-bit Organisationally Unique
Identifier (OUI) registered to a manufacturer. IEEE publishes
the registry; diting already ships a curated OUI map at
`src/diting/data/wifi_ouis.json` (today used for BLE vendor
resolution). The Ethernet / Wi-Fi OUI space is the same
namespace, so the existing data file is directly reusable.

This gets us `aa:bb:cc:11:22:33` → `Apple, Inc.` for free on the
common cases. Long-tail vendors fall back to `(unknown)`.

### Layer 4: reverse DNS

For each discovered IP, `socket.gethostbyaddr(ip)` issues a PTR
lookup. Behaviour:

- **Home routers with local DNS** (e.g. asus, ubiquiti, fritz):
  return the device's DHCP-supplied hostname → `airport-express.local`.
- **Most home routers**: no local DNS → query falls through to
  upstream public DNS → returns no result.
- **macOS itself**: `gethostbyaddr` consults mDNS first, so a
  Bonjour-publishing device's IP→hostname works even without
  router DNS.

Each lookup is asynchronous-friendly via `asyncio.to_thread` so
a hanging DNS server doesn't stall the panel.

### Layer 5: cross-reference with our existing Bonjour state

This is the diting-specific win. We already passively listen to
mDNS announces in `BonjourPoller`. Every `BonjourDevice` carries
`host` (the `.local.` name) and `addresses` (IPv4 + IPv6). When
we discover an ARP entry at IP X, we look up X in the Bonjour
state map:

```
ARP says:        192.168.1.42 = de:ad:be:ef:00:01 (Apple, Inc.)
Bonjour says:    192.168.1.42 = ccy-MBP2024-M4-Office.local
                                services: AirPlay, AirPlay audio, Apple Companion
→ render:        Apple, Inc.  ccy-MBP2024-M4-Office  AirPlay+3  192.168.1.42
```

For non-Apple devices that announce mDNS (printers, NAS,
Chromecasts, smart speakers, ESPHome IoT), this gives us a
friendly name without any extra probing. For devices that don't
announce mDNS (most generic IoT, Android phones, Windows
laptops), the row just shows OUI vendor + IP + MAC.

### Optional layer 5+: passive identity hints

If we want more after the MVP:

- **SSDP / UPnP** (UDP 239.255.255.250:1900): a multicast
  "M-SEARCH" produces device-description URLs from smart TVs,
  game consoles, media renderers. Adds ~20 lines of code,
  uses the same listen-only pattern as our Bonjour poller.
- **NetBIOS / LLMNR**: still alive on Windows boxes. UDP 137
  name query gets a NetBIOS name. Less common on a modern LAN.
- **TCP banner grab**: connect to port 22 / 80 / 443 / 8080 /
  5353, read the first banner line. Identifies SSH versions,
  web admin pages, etc. **Crosses the line into "active port
  scanning"** — should be opt-in only and never run on
  unfamiliar networks.

We'd stop at SSDP for an MVP and leave banner grabbing as a
later opt-in.

### What we deliberately do NOT do

- **No router admin scraping.** Some tools scrape the router's
  web UI for the DHCP lease table. Brittle (every router model
  has a different HTML structure), requires credentials, and is
  arguably hostile to the router vendor. Out of scope.
- **No deep packet inspection.** We don't sniff payload, only
  L2 / L3 metadata.
- **No traffic capture.** We never write a pcap.
- **No port scanning.** SYN-scanning every host's 65k ports is
  the easiest way to get diting flagged as malware by corporate
  EDR. Hard no.

## What the user sees

A new fourth panel cycle (the `n` toggle becomes Wi-Fi → BLE →
Bonjour → **LAN**), or a new keystroke to a dedicated view —
the panel choice is a UX call. Each row:

```
 vendor          name                      services / mDNS         IP              MAC                  last seen
 Apple, Inc.     ccy-MBP2024-M4-Office     AirPlay (+3)            192.168.1.42    de:ad:be:ef:00:01    now
 TP-Link Tech.   gateway                   —                       192.168.1.1     aa:bb:cc:11:22:33    now
 Roku, Inc.      Living-Room-TV            SSDP                    192.168.1.55    f4:5c:89:11:22:33    now
 (unknown)       —                         —                       192.168.1.81    98:76:54:32:10:00    13s ago
```

Diagnostics line at the top:

```
LAN inventory  17 hosts  ·  4 named (Bonjour)  ·  2 unknown vendor  ·  subnet 192.168.1.0/24  ·  last sweep 8s ago
```

A detail modal on `i` would show: IP / MAC / vendor / hostname /
all Bonjour services / first seen / last seen / RTT to host
(reusing the latency probe).

## Architecture sketch

```
LANInventoryPoller (new, src/diting/lan.py)
  ├─ subnet detector: parse `ifconfig en0` once at start
  ├─ sweep task: every 60s, asyncio.gather(254 pings) → harvest arp -an
  ├─ passive listener (optional): tcpdump -ni en0 'arp' subprocess,
  │   parse stdout for who-has / is-at, feed into state map
  ├─ enrichment:
  │     OUI lookup (reuse data/wifi_ouis.json)
  │     reverse DNS (asyncio.to_thread per IP, 500ms timeout)
  │     Bonjour cross-ref (read BonjourPoller state)
  ├─ state: dict[mac, LANHost] keyed by MAC (IPs rotate, MACs don't)
  └─ emit LANInventoryUpdate snapshots to consumer
```

`LANHost`:

```python
@dataclass(frozen=True, slots=True)
class LANHost:
    mac: str
    ip: str
    vendor: str | None         # from OUI map
    hostname: str | None       # from reverse DNS
    bonjour_name: str | None   # from BonjourPoller cross-ref
    bonjour_services: tuple[str, ...]
    first_seen: datetime
    last_seen: datetime
    is_gateway: bool           # IP matches Connection.router_ip
    is_self: bool              # MAC matches Connection.interface_mac
```

New OpenSpec capability `lan-inventory` with the schema +
sweep-cadence + cross-reference requirements. New view tab plus
detail modal in `tui-shell`.

## Performance budget

- **Network impact of a sweep**: 254 ICMP echo requests = ~21 KB
  out, similar in. Once per minute is 0.35 kbps average — utterly
  negligible.
- **Wall-clock**: ~2-10 s end-to-end on a typical home /24.
- **CPU**: bounded by asyncio scheduling; 254 ping tasks each
  doing ~200 ms of work = manageable.
- **Memory**: linear in host count; <100 hosts even on busy
  small-office LANs.

The poller would run on a longer cadence than scan/BLE (60-120 s
seems right) since ARP state changes slowly. A user pressing `r`
forces an immediate sweep.

## Where it falls down

Honest list of limits we'd document in the UI's basics modal:

1. **Client isolation**: enterprise / guest Wi-Fi often drops
   client-to-client traffic at the AP. We see only the gateway
   and ourselves. The Diagnostics line should say something
   like "网关之外暂未发现其他主机 — 网络可能启用了客户端隔离".
2. **VLAN segmentation**: same effect from a different mechanism
   — devices on a different VLAN are unreachable.
3. **Sleeping devices**: a phone whose screen is off and whose
   Wi-Fi is in power-save will sometimes not respond to ICMP
   immediately. We catch them on a later sweep when they wake.
4. **IPv6-only / dual-stack edge cases**: pure-IPv6 LANs are rare
   on consumer gear; we focus on IPv4 first and add IPv6 NDP
   discovery as a v2.
5. **MAC randomisation**: iOS / Android randomise their MAC per
   network. We'd correctly see the per-network MAC, but the
   vendor lookup gets the locally-administered bit (random)
   and shows "(unknown)". The Bonjour cross-ref usually still
   identifies them by hostname.
6. **DHCP lease churn**: a device's IP changes on reconnect. We
   key state by MAC so the row stays stable; the IP column just
   updates.

## Threat model and privacy

This is a **passive observation tool**. On your own home
network it's fine. On somebody else's network it ranges from
"impolite" (continuous ICMP sweep, even at 60 s, is logged by
intrusion-detection appliances) to "outright suspicious"
(running on corporate Wi-Fi will get attention).

We'd default the feature **off** until the user explicitly
enables it (a flag in `aps.yaml` or a CLI / env var), and we'd
keep a one-line README warning. The capability spec should
include a "DISABLED by default" requirement.

## Why this is interesting at all

Three real use cases:

1. **"Did someone new join my home network?"** Visible without
   guesswork or a router login. Combined with our existing
   roam-log timeline this becomes "the network's biography".
2. **"What is `192.168.1.81` and why is it eating my bandwidth?"**
   diting can't answer the bandwidth part, but answering the
   identity part is half the question.
3. **Debugging "the TV won't AirPlay"**: cross-referencing what
   the LAN inventory sees with what Bonjour publishes is exactly
   the diagnostic you'd want.

## Effort estimate

- **MVP (sweep + ARP-read + OUI + reverse DNS + Bonjour
  cross-ref, no SSDP, no port banner)**: ~1-2 days, including
  OpenSpec, tests, and TUI panel.
- **Polish (SSDP add, detail modal, RTT integration with
  LatencyPoller)**: another day or two.

Reasonable to drop into a future v1.2 release if we decide to
commit. No new dependency footprint — everything works with the
stdlib + `subprocess` + the existing zeroconf / pyobjc stack.

## Out of scope, again

- 24/7 monitoring. That's the
  [edge-hardware sidecar](#) idea, not this. The MVP only
  inventories while the TUI is open.
- "Block a device from the network". That's a router-side
  action, never something a LAN client can do without ARP
  spoofing — which we will not do.
- New-device alerts ("a stranger just joined!"). Possible later
  by diffing snapshots, but only meaningful if combined with
  persistent storage across diting restarts. MVP would just
  show the live state.
