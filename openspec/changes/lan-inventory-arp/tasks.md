## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — appended a new `### lan-inventory` section with entries for: lazy poller construction on first LAN-view entry, subnet derivation + /24 default cap + /22 WIDE cap, ICMP sweep concurrency / timeout, `arp -an` parsing, LANHost state-key + first-seen preservation, Bonjour cross-reference, OUI vendor + locally-administered MAC label. Added `tui-shell` entries for the four-way `n` cycle, `(sweeping subnet…)` first-tick placeholder, LANDetailScreen modal.
- [x] 1.2 `docs/zh/TESTING.md` — mirrored.

## 2. Core data model + poller (`lan-inventory`)

- [x] 2.1 `src/diting/lan.py` (new) — `LANHost` frozen dataclass with all fields per spec (mac / ip / vendor / hostname / bonjour_name / bonjour_services / first_seen / last_seen / is_gateway / is_self / is_randomised_mac). `LANInventoryUpdate` frozen dataclass with hosts / subnet / subnet_capped / cap_prefix / last_sweep_at / next_sweep_at.
- [x] 2.2 `src/diting/lan.py::_detect_subnet(iface_ip)` — derive netmask via `/sbin/ifconfig` parse; read effective cap from `DITING_LAN_INVENTORY_WIDE` env var (24 default, 22 when set to `"1"`); narrow the sweep down to a /cap around `iface_ip` when the netmask is wider; return `(hosts_to_probe: list[str], cidr: str, cap_prefix: int, was_capped: bool)`.
- [x] 2.3 `src/diting/lan.py::_ping_one(ip, timeout_ms) -> bool` — `asyncio.create_subprocess_exec("ping", "-c", "1", "-W", str(timeout_ms), ip)`, return whether non-zero exit.
- [x] 2.4 `src/diting/lan.py::_read_arp_cache() -> list[tuple[str, str, str]]` — subprocess `arp -an`, parse with the spec's regex, skip `<incomplete>` entries.
- [x] 2.5 `src/diting/lan.py::_is_randomised_mac(mac) -> bool` — first octet bit 0x02 check.
- [x] 2.6 `src/diting/lan.py::LANInventoryPoller` — async iterator `events()`, internal state dict keyed by `mac.lower()`. Each tick: `asyncio.gather` ping sweep (semaphore-bounded), then `_read_arp_cache()`, then enrich (OUI / reverse DNS / Bonjour cross-ref), then yield `LANInventoryUpdate`.
- [x] 2.7 `src/diting/lan.py::LANInventoryPoller.force_now()` — schedule an immediate sweep on the next tick.

## 3. TUI rendering (`tui-shell`)

- [ ] 3.1 `src/diting/tui.py::DitingApp` — instantiate `LANInventoryPoller` lazily the first time `_view_mode` transitions to `"lan"` (mirrors the existing BonjourPoller lazy-start pattern). Track `_lan_inventory_started: bool` flag.
- [ ] 3.2 `src/diting/tui.py` — new `LANPanel(VerticalScroll)` widget with `update_hosts(hosts, snapshot_meta, *, selected_mac=None)`. Row sort: `is_self` first, then `is_gateway`, then by IP ascending. Self/gateway rows prefixed with `★`. Random-MAC rows show `(random MAC)` instead of vendor. Before first snapshot lands, render one dim-italic line `(sweeping subnet…)`.
- [ ] 3.3 `src/diting/tui.py::DitingApp` — extend `action_toggle_view` so `n` cycles through `("wifi", "ble", "mdns", "lan")`. Existing wifi/ble/mdns subtitle and Diagnostics dispatch SHALL gain a fourth branch for `lan`.
- [ ] 3.4 `src/diting/tui.py::DitingApp.compose` — mount `LANPanel(id="lan")` alongside the existing three; `display=False` until `_view_mode == "lan"`.
- [ ] 3.5 `src/diting/tui.py::_environment_lines` (or wherever Diagnostics rendering switches on view) — new LAN-side summary block when `view == "lan"`: visible-LAN line + subnet line + last-sweep line (or `(sweeping subnet…)` before first snapshot).
- [ ] 3.6 `src/diting/tui.py::LANDetailScreen` — new modal mirroring `BLEDetailScreen` shape: Identity / Network / Bonjour services / Activity sections. Close keys `escape,i,q`. Cursor passthrough so `up` / `down` while the modal is open advances the LAN panel's selection (same as the BLE detail modal already does).
- [ ] 3.7 `src/diting/tui.py` — extend `action_inspect` (priority `i` binding) to dispatch to `LANDetailScreen` when `_view_mode == "lan"`.
- [ ] 3.8 `src/diting/tui.py::action_rescan` — when `_view_mode == "lan"` AND poller exists, call `poller.force_now()` in addition to (or instead of) the existing Wi-Fi rescan dispatch.

## 4. i18n

- [ ] 4.1 `src/diting/i18n.py` — EN+ZH entries for:
  - `"LAN"` → `"LAN"` (no translation — acronym, untranslated convention)
  - `"(sweeping subnet…)"` → `"(正在扫描子网…)"`
  - `"LAN inventory  "` → `"LAN 清单  "` (diagnostics row prefix)
  - `"{n} hosts"` → `"{n} 台主机"`
  - `"{n} named (Bonjour)"` → `"{n} 台有名字 (Bonjour)"`
  - `"{n} unknown vendor"` → `"{n} 台厂商未知"`
  - `"subnet {cidr}"` → `"子网 {cidr}"`
  - `"  · capped from /{bits}"` → `"  · 截自 /{bits}"`
  - `"last sweep {ago}"` → `"上次扫描 {ago}"`
  - `"Nearby LAN hosts"` → `"附近 LAN 主机"`
  - `"(random MAC)"` → `"(随机 MAC)"`
  - `"this Mac"` → `"本机"`
  - `"gateway"` → `"网关"`
  - Plus the LANDetailScreen section headers: `"Identity"` / `"Network"` (reuse existing keys when possible), `"Bonjour services"` → `"Bonjour 服务"`, `"Activity"` → reuse.

## 5. tui_snapshot.py regression scenario

- [ ] 5.1 `scripts/tui_snapshot.py` — add a synthetic `_LANInventoryBackend` returning a fixed `LANInventoryUpdate` with 5 hosts (1 self, 1 gateway, 1 Bonjour-named, 1 random-MAC, 1 unknown-vendor). Build a regression scenario `lan_view` that toggles to the LAN view + asserts panel shape.

## 6. Docs

- [ ] 6.1 `README.md` — add an LAN-inventory bullet to the headline feature list near the top + a note under the keybindings table that `DITING_LAN_INVENTORY_WIDE=1` unlocks a /22 sweep for wider home subnets. Roadmap entry for "Any-device LAN inventory" gets a `[shipped]` / "moved to shipped" marker.
- [ ] 6.2 `docs/zh/README.md` — mirror.

## 7. CI gates

- [ ] 7.1 `uv run pytest`
- [ ] 7.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [ ] 7.3 `openspec validate --specs --strict`
- [ ] 7.4 `openspec validate lan-inventory-arp --strict`
