## 1. Test plan first (test-first discipline)

- [x] 1.1 Add a new `## ### mdns-scanning` section to
      `tests/TESTING.md` with one row per Requirement in the new
      capability spec (8 Requirements → 8 rows). Rows reference
      `tests/test_mdns.py` for the unit cases and
      `tests/test_tui_smoke.py` for the wire-up smokes.
- [x] 1.2 Update the existing `tui-shell` section's view-toggle
      row to cite the new 3-way cycle test cases.
- [x] 1.3 Mirror to `docs/zh/TESTING.md`.

## 2. Dependencies + data

- [x] 2.1 Add `zeroconf >= 0.130` to `pyproject.toml` dependencies.
      Pin only the lower bound — security fixes upstream should
      flow.
- [x] 2.2 Create `src/diting/data/bonjour_services.json` mapping
      the curated service-type list to friendly categories:
      `_airplay._tcp` → `AirPlay`, `_raop._tcp` → `AirPlay audio`,
      `_googlecast._tcp` → `Chromecast`, `_sonos._tcp` → `Sonos`,
      `_ipp._tcp` / `_ipps._tcp` / `_printer._tcp` → `Printer`,
      `_smb._tcp` → `File share`, `_afpovertcp._tcp` → `File share`,
      `_workstation._tcp` → `Mac`, `_hap._tcp` → `HomeKit`,
      `_homekit._tcp` → `HomeKit`,
      `_companion-link._tcp` → `Apple Companion`,
      `_rfb._tcp` → `Screen sharing`, `_ssh._tcp` → `SSH`,
      `_http._tcp` → `HTTP`, `_https._tcp` → `HTTP`,
      `_meshcop._udp` → `Thread`, `_matter._tcp` → `Matter`.
- [x] 2.3 Add i18n entries for the friendly categories under the
      same neighbourhood as the existing service-category block
      (e.g., `AirPlay → AirPlay 接收` already exists; add the new
      ones: `Chromecast`, `Sonos`, `Printer`, `File share`, `Mac`,
      `HomeKit`, `Apple Companion`, `Screen sharing`, `SSH`, `HTTP`,
      `Thread`, `Matter`).

## 3. New module `src/diting/mdns.py`

- [x] 3.1 Top of file: lazy-import `from zeroconf import (
      InterfaceChoice, ServiceBrowser, ServiceListener, Zeroconf )`.
      Per the spec the import lives in this module only — `tui.py`
      MUST NOT import it.
- [x] 3.2 Define `BonjourDevice` (frozen dataclass) with the
      fields enumerated in the `mdns-scanning` spec: service_type,
      name, host, port, addresses, txt, vendor, category, first_seen,
      last_seen.
- [x] 3.3 Define `BonjourScanUpdate` (frozen dataclass) carrying
      `devices: list[BonjourDevice]`.
- [x] 3.4 `class _Listener(ServiceListener)` with the three
      callbacks `add_service` / `update_service` / `remove_service`.
      Marshal each callback onto the poller's asyncio queue (the
      callbacks fire on the zeroconf background thread; never call
      asyncio code directly from them — use
      `loop.call_soon_threadsafe`).
- [x] 3.5 `class BonjourPoller`:
      - `__init__(snapshot_interval_s=2.0, ttl_s=60.0)`.
      - `async events() -> AsyncIterator[BonjourScanUpdate]`.
      - `stop()` calls `Zeroconf.close()` synchronously.
- [x] 3.6 Load `bonjour_services.json` at import time, expose
      `service_category(service_type) -> str | None` (returns
      `None` for unknown — but in v1 unknown types are filtered
      out by the curated browse list, so this is forward-compat).
- [x] 3.7 Vendor resolution `resolve_vendor(device) -> str | None`
      implementing the 5-step chain from the spec. Reuse
      `ble.lookup_oui_vendor` and `ble._NAME_PATTERN_VENDORS`
      (export the latter from `ble.py` if it isn't already
      module-public; otherwise import as `_NAME_PATTERN_VENDORS`).
- [x] 3.8 TXT parser: decode bytes-keyed dict to str-keyed dict,
      drop entries whose value bytes don't decode as UTF-8.
- [x] 3.9 Snapshot loop: every `snapshot_interval_s`, expire
      entries whose `last_seen` is older than `ttl_s`, emit
      `BonjourScanUpdate(devices=sorted(values))`.

## 4. Wire `BonjourPanel` into the TUI

- [x] 4.1 `class BonjourPanel(VerticalScroll)` in `src/diting/tui.py`
      mirroring `BLEPanel`'s composition: `Static` body, border
      title `t("Nearby Bonjour devices")`. Empty-state placeholder
      `t("(no Bonjour devices yet — scanning...)")`.
- [x] 4.2 `_bonjour_row_line(d: BonjourDevice, now: datetime)`
      helper rendering vendor / name / services / age / id columns.
      Cribbed from `_ble_row_line` minus the RSSI / signal-bar /
      connected-vs-advertising branches.
- [x] 4.3 `_bonjour_diagnostic_lines(devices) -> list[Text]`
      helper producing the three diagnostic rows from the spec
      ("Visible Bonjour", "Top services", "Top vendors").
- [x] 4.4 `_refresh_environment_panel()` dispatch: when
      `_view_mode == "mdns"`, call
      `panel.update_environment_mdns(self._latest_mdns,
      self._mdns_permission_state)`. Add the new method on
      `EnvironmentPanel`.
- [x] 4.5 Add `BonjourPanel` to `DitingApp.compose()` between
      `BLEPanel` and `EventsPanel`. Initial `display = False`.

## 5. Extend the view-mode toggle to 3-way

- [x] 5.1 Replace `_view_mode` boolean assumptions with a tuple
      cycle: `_VIEW_MODES = ("wifi", "ble", "mdns")`. State stored
      as a string.
- [x] 5.2 `action_toggle_view()`: cycle through `_VIEW_MODES`.
- [x] 5.3 `_refresh_view_panels()` helper: based on `_view_mode`,
      set the three panels' `display` attributes
      (wifi=ScanPanel-only, ble=BLEPanel-only, mdns=BonjourPanel-only).
      Call this method from `on_mount` (initial state = wifi) AND
      from `action_toggle_view`.
- [x] 5.4 Update the `n` binding's `t()` description from
      `t("Toggle Wi-Fi / BLE view")` to
      `t("Toggle Wi-Fi / BLE / Bonjour view")` (catalog gets
      `"切换 Wi-Fi / BLE / Bonjour 视图"`).
- [x] 5.5 Footer label for `n`: change from `→ BLE` to
      `→ next view` (`下个视图`). Update i18n catalog.

## 6. Wire `BonjourPoller` to `DitingApp`

- [x] 6.1 `DitingApp.__init__`: add `_latest_mdns: list[BonjourDevice]
      = []` and `_mdns_permission_state: str = "unknown"` (the
      latter is for forward-compat with the BLE pattern; mDNS
      doesn't need TCC permission, so it's always implicitly
      "granted" once the browser fires its first event).
- [x] 6.2 `DitingApp.on_mount`: defer instantiating `BonjourPoller`
      to first-mdns-view-activation. Track via
      `_mdns_poller: BonjourPoller | None`.
- [x] 6.3 `action_toggle_view`: when transitioning INTO `mdns` for
      the first time in the session, lazy-import
      `from .mdns import BonjourPoller`, instantiate, and start the
      consumer task. Subsequent transitions reuse the existing
      poller.
- [x] 6.4 `async _consume_mdns_events()` task: drain
      `BonjourPoller.events()` into `self._latest_mdns`. When
      `_view_mode == "mdns"`, call `_refresh_environment_panel()`
      so the diagnostics row refreshes live.
- [x] 6.5 `on_unmount`: call `self._mdns_poller.stop()` if the
      poller was instantiated.

## 7. Tests in `tests/test_mdns.py`

- [x] 7.1 `test_service_category_known_type_returns_friendly_name`
      — `_airplay._tcp` → `AirPlay`.
- [x] 7.2 `test_service_category_unknown_type_returns_none` —
      `_unknown._tcp` → `None`.
- [x] 7.3 `test_resolve_vendor_txt_field_wins` — TXT
      `vendor=HomePod` overrides everything else.
- [x] 7.4 `test_resolve_vendor_hostname_pattern_falls_through_to_apple`
      — host `Macbook-Pro.local.`, no TXT vendor → `Apple, Inc.`.
- [x] 7.5 `test_resolve_vendor_service_hint_catches_chromecast` —
      `_googlecast._tcp` with no other signal → `Google`.
- [x] 7.6 `test_resolve_vendor_all_steps_abstain_returns_none`
      — pure abstain case.
- [x] 7.7 `test_txt_decode_drops_non_utf8_values` — TXT with
      one binary value: parser yields only the UTF-8 entries.
- [x] 7.8 `test_poller_emits_snapshot_after_first_announce` —
      use a stub `ServiceListener` to inject an announce; assert
      the snapshot list contains the corresponding `BonjourDevice`.
- [x] 7.9 `test_poller_removes_on_remove_service_callback`
      — same fixture, second event is `remove_service`; snapshot
      drops the entry.
- [x] 7.10 `test_poller_ttl_fallback_when_no_remove_observed`
      — set `ttl_s=0.1`, inject an announce, wait > 0.1 s, assert
      the entry expired.
- [x] 7.11 `test_poller_stop_joins_background_thread` — call
      `.stop()`, assert no background threads remain (use
      `threading.enumerate()` before and after).

## 8. TUI smoke test for the 3-way toggle

- [x] 8.1 Extend `tests/test_tui_smoke.py` with
      `test_view_toggle_cycles_wifi_ble_mdns_wifi`:
      build a `DitingApp(_FakeBackend(), _INVENTORY)`, drive `n`
      three times, assert the `_view_mode` lands back on `"wifi"`
      after three cycles and that each intermediate state has the
      correct panel visible.
- [x] 8.2 Add `test_app_constructs_bonjour_panel_lazily` — assert
      that on first construction `_mdns_poller is None`, and after
      one transition into `mdns` it's a `BonjourPoller` instance.

## 9. CHANGELOG

- [x] 9.1 `CHANGELOG.md` `[Unreleased] → ### Added` entry: one
      paragraph for mDNS / Bonjour discovery, mentioning the new
      panel, the 3-way `n` cycle, the curated service-type list,
      and the new `zeroconf` dependency.
- [x] 9.2 `docs/zh/CHANGELOG.md` mirror.

## 10. Self-test + ship

- [x] 10.1 `uv run pytest` — expect 434 + ~11 new unit cases + ~2
      TUI smokes = ~447 pass.
- [x] 10.2 `uv run python scripts/tui_snapshot.py --mode regression
      --check` — 16/16. Synthetic fixtures don't exercise mDNS;
      baseline unchanged.
- [x] 10.3 `openspec validate --specs --strict` — 16/16 (canonical
      specs unchanged until archive).
- [x] 10.4 `openspec validate mdns-bonjour-discovery --strict` —
      change valid.
- [x] 10.5 Live `DITING_LANG=zh` capture via
      `scripts/tui_snapshot.py --mode explore` — confirm the third
      panel appears on `n` × 2 cycles and renders some real
      Bonjour devices from your network.
- [ ] 10.6 Commit (explicit `git add <files>` — no `git add -A`),
      push, open PR.

## 11. Post-merge

- [ ] 11.1 `openspec archive mdns-bonjour-discovery` — applies the
      new `mdns-scanning` capability spec under canonical
      `openspec/specs/mdns-scanning/spec.md` AND the MODIFIED
      `tui-shell` Requirements into canonical
      `openspec/specs/tui-shell/spec.md`.
