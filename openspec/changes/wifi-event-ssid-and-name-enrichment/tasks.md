## 1. Test plan (test-first)

- [ ] 1.1 `tests/TESTING.md` (EN) — append entries under `events` (RoamEvent + RFStirEvent SSID schema, JSONL keys), under `tui-shell` (event-line SSID rendering rules), and under `roam-detection` / `environment-monitor` (poller / monitor fill the SSID at emission).
- [ ] 1.2 `docs/zh/TESTING.md` — mirror entries in ZH.

## 2. Event model additions (`events`)

- [ ] 2.1 `src/diting/poller.py::RoamEvent` — add `previous_ssid: str | None = None` and `new_ssid: str | None = None` AFTER the existing fields. Frozen-dataclass-safe (new defaulted fields at the end).
- [ ] 2.2 `src/diting/environment.py::RFStirEvent` — add `ssid: str | None = None` AFTER the existing fields.
- [ ] 2.3 `src/diting/event_log.py::event_to_jsonl` — extend the roam serialiser to emit `previous_ssid` / `new_ssid` after the existing BSSID / channel keys; extend the rf_stir serialiser to emit `ssid` after `bssid` / `location`. Skip the new keys when value is `None` (matches the existing "omit-None" pattern on the other writers).
- [ ] 2.4 `tests/test_event_log.py` — `test_event_to_jsonl_roundtrip_roam_with_ssid_pair`, `test_event_to_jsonl_roundtrip_rf_stir_with_ssid`, `test_event_to_jsonl_omits_ssid_keys_when_none`.

## 3. Poller fills SSID on roam emission (`roam-detection`)

- [ ] 3.1 `src/diting/poller.py::WiFiPoller` — track `_last_ssid: str | None` alongside `_last_bssid` / `_last_channel`. Update all three together when the connection changes; pass both SSIDs into the `RoamEvent` constructor on emission.
- [ ] 3.2 `tests/test_poller.py` — `test_roam_event_fills_ssid_from_connection_updates`: synthesize two `ConnectionUpdate`s with different BSSIDs / SSIDs, drive the poller, assert the emitted `RoamEvent` carries `previous_ssid` / `new_ssid` matching the connections. (If `test_poller.py` doesn't exist, add it.)

## 4. Environment monitor fills SSID on stir emission (`environment-monitor`)

- [ ] 4.1 `src/diting/environment.py::EnvironmentMonitor` — when emitting an `RFStirEvent`, pass the current `Connection.ssid` to the constructor.
- [ ] 4.2 `tests/test_environment.py` — extend an existing fire-an-event test to assert `event.ssid` reflects the connection that drove the σ crossing.

## 5. TUI renderer (`tui-shell`)

- [ ] 5.1 `src/diting/tui.py::_format_roam_event` — append the SSID segment per the rendering rules (single `SSID: <name>` when previous_ssid == new_ssid; `SSID: <prev> → <new>` when they differ; omit when both are `None` or both are `""`).
- [ ] 5.2 `src/diting/tui.py::_format_rf_stir_event` — append `· SSID <name>` when `event.ssid` is non-empty.
- [ ] 5.3 `src/diting/i18n.py` — add EN+ZH catalog entries for `"SSID: {ssid}"`, `"SSID: {prev} → {new}"`, `"SSID {ssid}"` (and any new comma/separator strings as needed).
- [ ] 5.4 `tests/test_tui_helpers.py` — `test_format_roam_event_includes_ssid_when_same_on_both_sides`, `test_format_roam_event_renders_ssid_transition_when_different`, `test_format_roam_event_omits_ssid_segment_when_both_none`, `test_format_roam_event_omits_ssid_segment_for_hidden_ssid`, `test_format_rf_stir_event_includes_ssid_when_present`, `test_format_rf_stir_event_omits_ssid_segment_when_none`.

## 6. CI gates

- [ ] 6.1 `uv run pytest`
- [ ] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [ ] 6.3 `openspec validate --specs --strict`
- [ ] 6.4 `openspec validate wifi-event-ssid-and-name-enrichment --strict`
