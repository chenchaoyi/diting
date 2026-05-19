# Design

The user-facing design rationale lives in
[`docs/explainers/lan-inventory-arp.md`](../../../docs/explainers/lan-inventory-arp.md).
This file captures the **implementation-level decisions** that
weren't explicit in the explainer.

## D1. Default ON with /24 cap, env var unlocks /22

Earlier drafts of this design had the feature opt-in via
`DITING_LAN_INVENTORY=1`. We reversed that on the principle
that diting's existing precedent is "active probes default
on": Wi-Fi scan, mDNS query, BLE scan all start lazily but
without an env-var gate. A /24 ICMP sweep (254 hosts, ~3-10
s wall-clock at 30-way concurrency) is noise-level on a home
network and behaviourally less aggressive than the mDNS
query storms diting already emits.

The remaining concern is corporate networks where the
netmask is wider than /24 — a /16 sweep is 65k hosts and is
both noisy and slow. We address that with a hard /24 cap in
the default code path (so the user's first launch on a new
network is bounded), plus an opt-in `DITING_LAN_INVENTORY_WIDE=1`
env var that relaxes the cap to /22 (1022 hosts). Users
who know their network can opt into the wider sweep
explicitly; users who don't are protected by the default cap.

Env-var rather than aps.yaml field because the env var is the
existing pattern for runtime switches (`DITING_LANG`,
`DITING_HELPER`, `DITING_LAN_INVENTORY_WIDE` joins that family)
and because the wide-sweep choice is per-environment, not
per-AP.

## D2. Subnet derivation + the /24 cap (/22 with WIDE flag)

```python
# pseudo
addrs = socket.getaddrinfo(socket.gethostname(), None, family=AF_INET)
iface_ip = pick the one matching Connection.ip_address from MacOSWiFiBackend
netmask  = read via ioctl SIOCGIFNETMASK or parse `ifconfig en0` once
default_cap = 24
if os.environ.get("DITING_LAN_INVENTORY_WIDE") == "1":
    default_cap = 22
effective_prefix = max(netmask_prefix, default_cap)
hosts_to_probe = expand subnet around iface_ip with effective_prefix
```

If the netmask resolves to /24 or narrower (/25 = 128 hosts,
/26 = 64, etc.), sweep the full subnet. If it's wider than
the cap, narrow the sweep down to the cap **around
`iface_ip`** — explicitly noting in the diagnostics line that
we're not sweeping the full broadcast domain.

Hard ceilings:
- default: 256 IPs / tick (/24)
- WIDE flag: 1024 IPs / tick (/22)

A /22 sweep at 30-way concurrency is ~30 s wall-clock; we
emit a single diagnostic message on first-tick so the user
understands what's happening if they forget they set the
flag.

## D3. ICMP sweep — subprocess `ping` vs raw socket

macOS `ping` is unprivileged for ICMP echo. Spawning 30
concurrent `subprocess.Popen(["ping", "-c", "1", "-W", "200",
ip])` is the simplest path and what the design doc settled on.
Each `ping` exits within 200 ms whether the host responded or
not.

Raw `socket.socket(AF_INET, SOCK_DGRAM, IPPROTO_ICMP)` on
macOS is also unprivileged for the DGRAM variant since 2014,
but adds non-trivial parsing of the echo-reply packet
structure. Not worth the complexity for the MVP. If we ever
need finer-grained per-host RTT (already partially available
via the `LatencyPoller` for the gateway), revisit.

We use `asyncio.create_subprocess_exec` (not the blocking
`subprocess.run`) so the 30-concurrency semaphore actually
parallelises rather than serialising on the GIL.

## D4. Reading the ARP cache — `arp -an` parse

```
? (192.168.1.1) at aa:bb:cc:11:22:33 on en0 ifscope [ethernet]
? (192.168.1.42) at de:ad:be:ef:00:01 on en0 ifscope [ethernet]
```

Parse regex: `r'\(([\d.]+)\)\s+at\s+([0-9a-f:]+)\s+on\s+(\w+)'`.
Skip `incomplete` entries — those are sweeps where the host
didn't respond to ARP-who-has (genuinely offline or filtered).

Reading `/proc/net/arp` would be the Linux equivalent; we
ship macOS-only today, so `arp -an` it is. (When we eventually
do the Linux backend per the roadmap, `pyroute2` exposes the
neighbour table directly.)

## D5. Bonjour cross-reference — which side owns the lookup

The Bonjour state map is keyed by `(service_type, name)` and
each `BonjourDevice` carries `addresses: tuple[str, ...]`. To
join with the ARP table (keyed by MAC) we have to walk Bonjour
state and build a transient `{ipv4: BonjourDevice}` index per
snapshot tick. Cheap (typically 20-50 entries) and clean —
the LAN poller reads from `BonjourPoller._state` without
mutating it.

If a Bonjour service announces multiple `.local.` hosts
sharing one IP (rare but possible with virtual-host setups),
we keep the first match and ignore subsequent ones. The
detail modal can show the full list if the user opens it.

## D6. Vendor lookup — reuse `data/wifi_ouis.json`

The existing OUI map was built for BLE vendor resolution. The
IEEE OUI namespace is the same for Ethernet / Wi-Fi / BLE
MACs, so the data file is directly reusable via
`diting.ble.lookup_oui_vendor` (already exported). No new
data file.

When the first octet's bit 0x02 is set the MAC is
locally-administered (random / randomised). The vendor lookup
will miss (random MACs aren't in IEEE's registry), and the
renderer SHALL show `(random MAC)` instead of `(unknown)` so
the user understands why no vendor came back.

## D7. State key — MAC, not IP

DHCP rotates IPs on reconnect; MACs persist (per network for
random-MAC devices, globally for everything else). State map
is `dict[mac_lower, LANHost]`. When the same MAC reappears at
a new IP, we update the IP field in place — the row keeps its
`first_seen` and accumulated identity (Bonjour name etc.).

When a MAC is seen for the first time in a session we set
`first_seen = now`; `last_seen` updates on every observation.

## D8. First-tick rendering — "sweeping subnet…"

When the user first cycles into the LAN view, the poller is
constructed and the first sweep kicks off. Until the first
`LANInventoryUpdate` lands (~3-10 s default, ~30 s under
WIDE), the panel renders one dim-italic placeholder line:

```
(sweeping subnet…)
```

ZH:

```
(正在扫描子网…)
```

This is the same idiom as the existing Bonjour panel's
"discovering services…" first-tick state. The poller is
lazy: nothing happens until the user actually cycles in.

## D9. Where the poller lives

```
DitingApp (existing)
  ├─ WiFiPoller        (existing)
  ├─ BLEPoller         (existing, lazy on n → BLE)
  ├─ BonjourPoller     (existing, lazy on first BLE → mDNS)
  └─ LANInventoryPoller (NEW, lazy on first Bonjour → LAN)
```

The lazy start mirrors the Bonjour pattern: nothing happens
until the user actually cycles into the LAN view (third `n`
press after Wi-Fi → BLE → Bonjour → LAN). A user who never
enters the view pays zero cost for the feature.

## D10. Cadence — 60 s default, `r` for immediate

A /24 sweep at 30-way concurrency completes in ~2-3 s on a
healthy network, ~10 s when many hosts are silent. Running
once per minute gives ~1.7 % duty cycle on the ping subprocess
pool — comfortable.

`r` (force_rescan) does an immediate sweep in addition to its
existing role of forcing a Wi-Fi scan. From the LAN view, `r`
re-sweeps the subnet.

## D11. UI mock

```
┏━ Connection ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ?af:5e:9d  5G  · country CN                                  ┃
┃   ...                                                        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━ Diagnostics ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ LAN inventory  17 hosts · 4 named · 2 unknown vendor ·       ┃
┃ subnet 192.168.1.0/24 · last sweep 8s ago                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━Wi-Fi  ·  BLE  ·  Bonjour  ·  LAN━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ★ vendor            name                  IP            MAC                last seen ┃
┃ ★ Apple, Inc.       this Mac              192.168.1.20  84:2f:57:9b:15:59  now       ┃
┃ ★ TP-Link Tech.     gateway               192.168.1.1   aa:bb:cc:11:22:33  now       ┃
┃   Apple, Inc.       ccy-MBP24-M4-Office   192.168.1.42  de:ad:be:ef:00:01  now       ┃
┃   Roku, Inc.        Living-Room-TV        192.168.1.55  f4:5c:89:11:22:33  now       ┃
┃   (random MAC)      —                     192.168.1.81  98:76:54:32:10:00  13s ago   ┃
┗━━━━━━━━━━━━━━━━━━ Nearby LAN hosts (17)  · sort: ip  ━━━━━━━┛
```

## D12. Test surface

`tests/test_lan.py` (new file):

- `test_subnet_from_ifconfig_parses_typical_home_24`
- `test_subnet_caps_at_24_when_netmask_wider`
- `test_subnet_caps_at_22_when_wide_flag_set`
- `test_subnet_still_caps_at_22_when_wide_flag_set_and_netmask_is_16`
- `test_arp_parse_skips_incomplete_entries`
- `test_arp_parse_extracts_mac_and_ip`
- `test_lan_host_keyed_by_mac_keeps_first_seen_across_ip_change`
- `test_is_randomised_mac_detects_locally_administered_bit`
- `test_bonjour_cross_ref_pulls_name_from_state`

`tests/test_tui_helpers.py` additions:

- `test_lan_panel_renders_self_and_gateway_pinned_to_top`
- `test_lan_panel_renders_sweeping_placeholder_before_first_snapshot`
- `test_lan_panel_marks_random_mac_with_label`
- `test_lan_detail_modal_renders_all_sections`

`scripts/tui_snapshot.py` additions:

- `lan_view` regression scenario with a synthetic
  `_LANInventoryBackend` so the layout is locked under CI.

## D13. Surface impact

- `src/diting/lan.py` — new file, ~250 LoC for poller + state
- `src/diting/tui.py` — new `LANPanel`, `LANDetailScreen`,
  `n` cycle extension, diagnostics line dispatch (~200 LoC
  additions across existing functions)
- `src/diting/i18n.py` — new EN+ZH catalog entries
- `tests/test_lan.py` — new, ~200 LoC
- `tests/test_tui_helpers.py` — additions
- `scripts/tui_snapshot.py` — new scenario
- `README.md` + `docs/zh/README.md` — keybinding row already
  references `n`; add an LAN bullet to the feature list near
  the top + a note about `DITING_LAN_INVENTORY`

No new third-party dependency.
