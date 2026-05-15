## 1. Shared infrastructure

- [x] 1.1 Extract the `clearly-better same-SSID candidate` rule from the diagnostics panel's roam-score rendering into a pure helper `recommend_roam(scan: list[ScanResult], current_bssid: str | None) -> Recommendation | None` (in `src/diting/roam.py` or wherever the rule currently inlines). Keep the diagnostics panel calling the same helper so behaviour is identical. **Status**: helper already lives in `tui.py:2644` as `_best_same_ssid_candidate(results, current)` — pure function, already shared between the diagnostics panel and the new Recommendation section. No refactor needed.
- [x] 1.2 Add a per-BSSID RSSI history accessor to `EnvironmentMonitor` (or expose one if it already exists internally) returning the last-N samples + timestamps so the Wi-Fi modal can render a sparkline without re-collecting. **Status**: `EnvironmentMonitor.get_rssi_history(bssid)` + `EnvironmentMonitor.get_baseline(bssid)` added at `environment.py:278-322`.
- [x] 1.3 Add `vendor_trace: str | None = None` to `BonjourDevice` (frozen dataclass — needs `field(default=None)`). Update `BonjourPoller._resolve_vendor` to return both the vendor and the winning chain step name; thread that into device construction. **Status**: `BonjourDevice.vendor_trace` field added; new `resolve_vendor_with_trace()` returns `(vendor, trace)`; `resolve_vendor()` kept as a thin wrapper for backwards compat with existing tests; poller's listener uses the with-trace variant.

## 2. Wi-Fi modal sections

- [x] 2.1 Wire `WifiDetailScreen.__init__` for the new kwargs (`environment_monitor=None`, `event_ring=None`, `latest_scan=None`). Default None so existing fixtures keep working. Update the App-side call site that constructs the modal to pass the real refs.
- [x] 2.2 Implement `_section_signal_history` (sparkline + σ band label). Reuse the existing sparkline util used by the BLE detail modal. Omit the section when the monitor has < 2 samples or the monitor ref is None.
- [x] 2.3 Implement `_section_siblings` (same physical AP). Walk `latest_scan` filtering BSSIDs sharing the selected row's AP cluster key. Sort by RSSI desc. Omit when cluster is singleton.
- [x] 2.4 Implement `_section_roam_history` (event ring filter). Filter `event_ring.iter()` for `RoamEvent` where `from_bssid` or `to_bssid` matches; cap at 10; newest-first; render `<HH:MM:SS> · [same-AP | cross-AP] · <from> → <to>`.
- [x] 2.5 Implement `_section_recommendation`. Call the helper from 1.1. Render `consider switching to <BSSID> on <band> · +N dB` when a clearly-better candidate exists; omit otherwise.
- [x] 2.6 Update `_render_body` to invoke the four new sections in the spec'd order (Signal history after Signal, Same physical AP after Beacon IE, Roam history after Same physical AP, Recommendation after Roam history, Activity last).

## 3. Bonjour modal sections

- [x] 3.1 Wire `BonjourDetailScreen.__init__` for the new kwargs (`latest_mdns=None`, `latest_ble=None`, `latest_connection=None`). Default None. Update the App-side call site.
- [x] 3.2 Extend `_section_identity` to append ` · via <trace>` on the vendor row when `device.vendor_trace is not None`. Style matches the existing `(associated)` annotation.
- [x] 3.3 Implement `_section_other_services`. Walk `latest_mdns` for other `BonjourDevice`s sharing the same `host` (or addresses tuple when host is None). Render each as `<category> · <last_seen age>`. Omit when this host has only the selected service.
- [x] 3.4 Implement the TXT decoder registry at `src/diting/mdns_txt_decoders.py`. Initial decoder set: `model` (Apple identifier → friendly name), `osxvers` (major → codename), `srcvers` (verbatim), `deviceid` (MAC normalisation). Bitmask decoders for `features` / `ft` / `rpFl` deferred per design.md:D5.
- [x] 3.5 Refactor `_section_txt` into Decoded + Raw two-part rendering. Decoded keys are skipped via `decoded_keys()` so they do not also appear in the Raw table.

## 4. Cross-surface correlation

- [ ] 4.1 Implement rule 1 (address match → "local Mac (this host is you)"). Compare against `latest_connection.local_ip` and `latest_connection.this_mac`-derived interface addresses.
- [ ] 4.2 Implement rule 2 (TXT `deviceid` MAC → BLE peripheral match). Parse `deviceid` as MAC; scan `latest_ble` for the same MAC in manufacturer data or known fields. Render `also on BLE as <category | name | vendor> · <RSSI> dBm`.
- [ ] 4.3 Implement rule 3 (hostname pattern + Apple-Proximity hint). Hedge the render with "likely". Skip if false-positive risk is too high in real captures; design.md:D7 permits deferral.
- [ ] 4.4 Wire the section into `_render_body` between Network and TXT.

## 5. Tests

- [x] 5.1 `tests/test_tui_helpers.py` — synthetic-fixture tests for each new section's renderer. **Status**: Wi-Fi side (9 tests, Stage 1) + Bonjour side (7 tests, Stage 2: vendor-trace annotation, other-services, decoded TXT) complete. Plus a dedicated `tests/test_mdns_txt_decoders.py` for the decoder registry (12 tests).
- [x] 5.2 `tests/test_tui_smoke.py` — smoke through `Pilot`. **Status**: existing smoke tests cover both modals opening / closing without raising; the new section paths are exercised via the section-level helper tests in `test_tui_helpers.py` and `test_mdns_txt_decoders.py`.
- [x] 5.3 `tests/test_mdns.py` — assert `BonjourDevice.vendor_trace` is set to the correct chain step for each of the 5 resolution paths, including `None` when all abstain. **Status**: 5 new tests added for `resolve_vendor_with_trace`.
- [ ] 5.4 Cross-surface tests behind a clear-cut local-Mac fixture (rule 1) — rules 2 and 3 are harder to fixture without real BLE data; manual smoke + the existing `/tui-audit` capture covers them.

## 6. Docs

- [x] 6.1 Update `tests/TESTING.md` and `docs/zh/TESTING.md` rows for `wifi-detail-modal`, `bonjour-detail-modal`, and `mdns-scanning` capabilities to reference the new tests. **Status**: all three capability rows updated in EN + ZH.
- [x] 6.2 No README change needed (the modals' existence is already documented at the surface level).

## 7. Gates

- [x] 7.1 `uv run pytest` passes.
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression` passes.
- [x] 7.3 `openspec validate --specs --strict` passes.
- [x] 7.4 `openspec validate wifi-and-bonjour-detail-enrichment --strict` passes.
- [ ] 7.5 Optional: re-run `/tui-audit` against the user's real environment after the modal changes land, confirm the new sections render against real Wi-Fi / Bonjour data without overflow.
