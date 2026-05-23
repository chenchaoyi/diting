## 1. Phase 1 — passive enrichment (OUI multi-tier + vendor normalization)

- [x] 1.1 Extend `scripts/refresh_ouis.py` to partition the IEEE CSV into three files by registry column (MA-L / MA-M / MA-S); emit `wifi_ouis_ma_m.json` and `wifi_ouis_ma_s.json` alongside the existing `wifi_ouis.json`.
- [x] 1.2 Refresh the bundled data files: run the updated script and commit the three JSON files under `src/diting/data/`.
- [x] 1.3 In `src/diting/ble.py`, add `load_ouis_layered() -> tuple[dict, dict, dict]` that loads all three files, tolerating missing / unreadable ones.
- [x] 1.4 Extend `lookup_oui_vendor(mac, *, ma_l, ma_m, ma_s)` for longest-prefix-wins matching (36→28→24); preserve the existing single-tier `lookup_oui_vendor(mac, ouis)` signature as a back-compat shim that treats `ouis` as MA-L only.
- [x] 1.5 In `src/diting/lan.py`, replace the single-tier OUI load + lookup calls with the layered variant.
- [x] 1.6 Add `_normalize_vendor(name: str) -> str` and `_ACRONYM_OVERRIDES` table to `src/diting/lan.py`.
- [x] 1.7 Extend `LANHost` dataclass with `vendor_raw: str | None`; update `_merge_arp_into_state` to populate both `vendor` (normalized) and `vendor_raw` (raw IEEE).
- [x] 1.8 Update `LANDetailScreen._render_body` to surface the raw IEEE string on a dim continuation line when it differs from the normalized form.
- [x] 1.9 Update `tests/TESTING.md` + `docs/zh/TESTING.md` with new sections for multi-tier OUI, vendor normalization. EN/ZH parity required.
- [x] 1.10 Write `tests/test_oui_multitier.py` covering all three tiers + missing-file degradation.
- [x] 1.11 Write `tests/test_vendor_normalize.py` covering Chinese-prefix stripping, acronym preservation, titlecase, truncation.
- [x] 1.12 Extend `tests/test_lan.py` to verify `vendor_raw` is preserved and `vendor` is normalized.
- [x] 1.13 Extend `tests/test_tui.py` for the LAN-detail modal's dim-continuation-line behaviour.
- [x] 1.14 Run `uv run pytest` and `openspec validate expand-lan-identification --strict`; both must pass.

## 2. Phase 2 — active discovery layer (NBNS + UPnP + active mDNS)

- [x] 2.1 Create `src/diting/lan_probes.py` skeleton with three async functions: `probe_nbns(hosts, *, timeout_ms=100)`, `probe_ssdp(*, timeout_s=3, fetch_locations=True)`, mDNS active query is delegated to `BonjourPoller.send_meta_query()`.
- [x] 2.2 Implement NBNS Status Query construction + Status Response parsing (RFC 1002 §4.2.18). Hand-roll the 50-byte packet; parse the name table; pull the WORKSTATION (`0x00`) name. Concurrency bounded by 30-way semaphore.
- [x] 2.3 Implement SSDP M-SEARCH: bind ephemeral UDP socket, send to `239.255.255.250:1900`, listen 3 s, parse HTTP-style header blocks into `(SERVER, LOCATION, USN, ST)` tuples per response.
- [x] 2.4 Implement UPnP LOCATION fetch: stdlib `urllib` GET with 500 ms timeout, 4 KB response cap; parse with `xml.etree.ElementTree` (no external entities); extract `<friendlyName>`, `<modelName>`.
- [x] 2.5 Extend `BonjourPoller` with `send_meta_query()` that sends one mDNS query for `_services._dns-sd._meta._tcp.local`. Reuse the existing listener for response capture.
- [x] 2.6 In `src/diting/scene.py`, extend `scene_defaults()` to include `lan_active_probe` per the table in the scenes spec delta.
- [x] 2.7 In `src/diting/cli.py`, parse `DITING_LAN_PROBE=0|1` and `DITING_LAN_UPNP_FETCH=0|1` at startup; surface the parsed resolution into the LANInventoryPoller constructor.
- [x] 2.8 Update `--help` output to document both env vars under global options.
- [x] 2.9 Wire `LANInventoryPoller._do_sweep_and_emit()` to call into `lan_probes` when the resolved active-probe flag is True (or when `_one_shot_probe_armed` is True); merge probe enrichments into per-host `nbns_name`, `upnp_server`, `upnp_friendly_name`, `upnp_model` fields.
- [x] 2.10 Extend `LANHost` dataclass with the four new fields. Update detail modal's `Active discovery` section accordingly.
- [x] 2.11 Update `tests/TESTING.md` + `docs/zh/TESTING.md` for active-probe scenarios.
- [x] 2.12 Write `tests/test_lan_probes.py` covering NBNS encoding/decoding, SSDP parsing, UPnP XML parsing, malicious-LOCATION resilience.
- [x] 2.13 Extend `tests/test_lan.py` to verify scene-gating: home runs probes, public doesn't; env override toggles both ways.
- [x] 2.14 Extend `tests/test_cli.py` for the two new env vars + invalid-value warning behaviour.
- [x] 2.15 Run `uv run pytest`; all green.

## 3. Phase 3 — heuristics (TTL fingerprint + device classifier)

- [x] 3.1 Extend `_ping_one()` to also parse `ttl=N` from ping stdout; change return type to `tuple[bool, float | None, int | None]`.
- [x] 3.2 Update `_sweep()` return-type signature and all callers accordingly.
- [x] 3.3 Add `_ttl_class(ttl)` helper applying the 50-64 / 100-128 / 200-255 buckets; populate `LANHost.ttl` + `LANHost.ttl_class` in the merge step.
- [x] 3.4 Create `src/diting/lan_classify.py` with `classify(host: LANHost) -> str | None` and the documented rules table.
- [x] 3.5 Wire `classify()` into the merge step so `device_class` lands on every `LANHost`.
- [x] 3.6 Update detail modal's Identity section with the `Class:` row when `device_class` is non-None.
- [x] 3.7 Update detail modal's Network section with the TTL row.
- [x] 3.8 Update `tests/TESTING.md` + ZH with TTL + classifier scenarios.
- [x] 3.9 Write `tests/test_device_class.py` covering all class branches + None fallback.
- [x] 3.10 Extend `tests/test_lan.py` for TTL bucket behaviour (raw value preserved, class derived correctly, decremented-hop tolerance).
- [x] 3.11 Run `uv run pytest`; all green.

## 4. Phase 4 — UX (new chip, class column, public probe override)

- [x] 4.1 Add `_COL_LAN_CLASS = 8` constant in `src/diting/tui.py`; update `_lan_header_line()` to include the class column header.
- [x] 4.2 Update `_lan_row_line()` to render the class column between vendor and name, and to prepend the `[new]` chip when `(now - first_seen) < 24 h`.
- [x] 4.3 Add EN/ZH strings to `src/diting/i18n.py` per the i18n spec delta. EN keys + ZH values must land in the same PR.
- [x] 4.4 Define `LANActiveProbeConsentedEvent` in `src/diting/events.py`.
- [x] 4.5 Add `EventLogger.emit_lan_active_probe_consented(event)` in `src/diting/event_log.py`; update the event-to-JSONL serializer.
- [x] 4.6 Build `LANProbeConsentScreen(ModalScreen)` in `src/diting/tui.py` with the 2-second cooldown on the `y` binding; render the scene/SSID header, the packet-enumeration body, and the consequences statement.
- [x] 4.7 Wire the LAN view's `P` key to push `LANProbeConsentScreen` only when active scene is `public` AND `DITING_LAN_PROBE` is unset; otherwise no-op.
- [x] 4.8 On modal confirm: emit the JSONL event, set `_one_shot_probe_armed=True` on the poller, call `poller.force_now()`, close modal.
- [x] 4.9 Add `[probing]` subtitle chip rendering when `_one_shot_probe_armed` is True; clear chip after the resulting `LANInventoryUpdate` lands.
- [x] 4.10 Update `--help` to mention the `P` keybinding under the LAN view's section.
- [x] 4.11 Update `README.md` + `docs/zh/README.md` with a new `## LAN identification` section (multi-tier OUI, active discovery, scene-gating, public override).
- [x] 4.12 Update `tests/TESTING.md` + `docs/zh/TESTING.md` for the new chip, class column, consent modal, JSONL event.
- [x] 4.13 Extend `tests/test_tui.py` for the consent modal: cooldown defeats press-through, esc cancels, y after 2 s confirms, P is no-op in non-public scenes.
- [x] 4.14 Extend `tests/test_event_log.py` for the new event type's JSONL shape.
- [x] 4.15 Extend `tests/test_events.py` for the new event dataclass.
- [x] 4.16 Capture new regression fixtures via `uv run python scripts/tui_snapshot.py --mode regression`; verify the LAN panel renders the new column + chip correctly.

## 5. CHANGELOG + version bump + final validation

- [x] 5.1 Bump `pyproject.toml` version (minor: 1.6.0 → 1.7.0).
- [x] 5.2 Update `CHANGELOG.md` + `docs/zh/CHANGELOG.md` with a "v1.7.0 — LAN identification" entry covering the four phases. EN/ZH parity required.
- [x] 5.3 Run `uv run pytest`; all green.
- [x] 5.4 Run `uv run python scripts/tui_snapshot.py --mode regression`; all green.
- [x] 5.5 Run `openspec validate --specs --strict`; all canonical specs valid.
- [x] 5.6 Run `openspec validate expand-lan-identification --strict`; change valid.
- [x] 5.7 Self-audit: `/tui-audit 10` against the developer's home network; capture findings under `/tmp/wfs-tui-audit-*/findings.md`.
- [x] 5.8 Commit all changes on a new branch `feature/expand-lan-identification`; open PR.
