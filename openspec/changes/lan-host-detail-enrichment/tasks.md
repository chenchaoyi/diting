## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — under the existing `### lan-inventory` section, add rows for: `_ping_one` returns `(reachable, rtt_ms)`, `_sweep` returns per-IP results dict, `LANHost.last_rtt_ms` populated from sweep, `LANHost.last_reachable_at` preserved across silent ticks. Under `tui-shell`, add rows for: Latency row in LANDetailScreen Network section, Reachable row variants (`this sweep` / `Xs ago` / `never`), Bonjour services empty-state placeholder.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. OUI refresh script

- [x] 2.1 `scripts/refresh_ouis.py` (new) — fetch `https://standards-oui.ieee.org/oui/oui.csv`, parse the CSV, filter to `MA-L` rows, dedupe, normalise keys to `aa:bb:cc`, write to `src/diting/data/wifi_ouis.json` with a refreshed `_meta` block (source URL, fetch timestamp, license attribution).
- [x] 2.2 Run the refresh script once; commit the resulting full dataset.

## 3. RTT capture + reachable tracking (`lan-inventory`)

- [x] 3.1 `src/diting/lan.py::_ping_one` — change signature to `async def _ping_one(ip, *, timeout_ms) -> tuple[bool, float | None]`. Capture stdout via `PIPE`, parse `time=X.XXX ms` regex, return `(rc == 0, rtt | None)`. On any subprocess failure return `(False, None)`.
- [x] 3.2 `src/diting/lan.py::_sweep` — change signature to return `dict[str, tuple[bool, float | None]]`. Build the dict from the per-host gather results.
- [x] 3.3 `src/diting/lan.py::LANHost` — add `last_rtt_ms: float | None = None` and `last_reachable_at: datetime | None = None` fields.
- [x] 3.4 `src/diting/lan.py::LANInventoryPoller._do_sweep_and_emit` — capture the sweep result dict; pass it into the merge step.
- [x] 3.5 `src/diting/lan.py::LANInventoryPoller._merge_arp_into_state` — accept `sweep_results: dict[str, tuple[bool, float | None]]`. For each ARP triple, look up the IP in `sweep_results`; if the host responded, set `last_rtt_ms` and `last_reachable_at=now`. If the host did NOT respond this sweep, preserve the existing entry's `last_rtt_ms` and `last_reachable_at` (frozen at last successful ping).

## 4. LANDetailScreen rendering (`tui-shell`)

- [x] 4.1 `src/diting/tui.py::LANDetailScreen._render_body` — Network section: add `Latency` row (omit when `last_rtt_ms is None`); add `Reachable` row (always rendered, three variants).
- [x] 4.2 `src/diting/tui.py::LANDetailScreen._render_body` — Bonjour services section: keep the section header even when empty; render `(no Bonjour services)` dim-italic placeholder.
- [x] 4.3 `src/diting/tui.py` — small helper for formatting `last_rtt_ms` to `XX.X ms` and `last_reachable_at` to one of `this sweep` / `Xs ago` / `never`.

## 5. i18n

- [x] 5.1 `src/diting/i18n.py` — EN+ZH entries:
  - `"Latency"` → `"延迟"`
  - `"Reachable"` → `"可达"`
  - `"this sweep"` → `"此次扫描"`
  - `"never"` → `"从未"`
  - `"(no Bonjour services)"` → `"（无 Bonjour 服务）"`

## 6. Tests

- [x] 6.1 `tests/test_lan.py` — `test_ping_one_returns_rtt_on_zero_exit`, `::test_ping_one_returns_none_rtt_on_nonzero_exit`, `::test_ping_one_returns_true_none_when_stdout_unparseable`, `::test_sweep_returns_per_ip_results`, `::test_lan_host_last_rtt_ms_populated_from_sweep`, `::test_lan_host_last_reachable_at_preserved_when_silent`, `::test_oui_refresh_script_parses_csv`.
- [x] 6.2 `tests/test_tui_helpers.py` — `test_lan_detail_modal_renders_latency_row_when_rtt_known`, `::test_lan_detail_modal_omits_latency_row_when_rtt_unknown`, `::test_lan_detail_modal_renders_reachable_row_this_sweep_when_within_cadence`, `::test_lan_detail_modal_renders_reachable_row_with_relative_time_when_older`, `::test_lan_detail_modal_renders_never_when_never_reachable`, `::test_lan_detail_modal_renders_bonjour_empty_state_when_no_services`.

## 7. Snapshot regression scenario

- [x] 7.1 `scripts/tui_snapshot.py::_switch_to_lan_inventory` — populate synthetic hosts with `last_rtt_ms` + `last_reachable_at`. Update `lan_view` scenario assertions to verify Latency / Reachable rows appear in the diagnostics rendering (or add a `lan_detail_modal` scenario).

## 8. Docs

- [x] 8.1 `README.md` — IEEE attribution under "Acknowledgements" or similar; note `scripts/refresh_ouis.py` under contributor docs.
- [x] 8.2 `docs/zh/README.md` — mirror.

## 9. CI gates

- [x] 9.1 `uv run pytest`
- [x] 9.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 9.3 `openspec validate --specs --strict`
- [x] 9.4 `openspec validate lan-host-detail-enrichment --strict`
