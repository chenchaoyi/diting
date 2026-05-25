## 1. Test plan updates (test-first, per CLAUDE.md hard rule)

- [ ] 1.1 Add a "MAC zero-pad at ARP ingest" section to `tests/TESTING.md` describing the `_read_arp_cache` normalisation cases (already-padded, stripped, mixed)
- [ ] 1.2 Mirror the section into `docs/zh/TESTING.md` (ZH parity rule)
- [ ] 1.3 Add a "BLE rotating-ID name guard" section to `tests/TESTING.md` covering predicate true/false cases, raw-name modal row, and EN+ZH catalog strings
- [ ] 1.4 Mirror into `docs/zh/TESTING.md`
- [ ] 1.5 Add an "Events modal consecutive BLE-seen grouping" section to `tests/TESTING.md` covering consecutive fold, vendor break, non-BLE break, rotating-ID label fold, JSONL untouched, filter-then-group order
- [ ] 1.6 Mirror into `docs/zh/TESTING.md`

## 2. Fix 1 — MAC zero-pad at ARP ingest

- [ ] 2.1 In `src/diting/lan.py`, introduce a small `_canon_mac(raw: str) -> str` helper that zero-pads each octet and lowercases. Idempotent on already-padded input.
- [ ] 2.2 Apply `_canon_mac` to the regex-captured MAC inside `_read_arp_cache`, before the multicast-destination filter so the filter sees canonical form too.
- [ ] 2.3 Verify `_is_multicast_dest_mac` still works (it splits on `:`, so canonicalised octets compose cleanly).
- [ ] 2.4 Add unit tests in `tests/test_lan.py`:
  - macOS-stripped input → padded output
  - already-padded input → identity
  - all-zeros tail (`00:00:…:00`) → preserved
  - upper-case input → lower-case padded output
  - one-octet line is rejected silently (existing behaviour preserved)
- [ ] 2.5 Confirm the LAN detail modal pulls the padded form (no code change in `tui.py:5744`; covered by the data-boundary fix).

## 3. Fix 2 — BLE rotating-ID name guard

- [ ] 3.1 In `src/diting/tui.py`, add `_looks_like_rotating_id(name: str | None) -> bool` near the BLE row formatter — pre-compiled regex constant, hard-coded Apple-product prefix tuple.
- [ ] 3.2 In the BLE list row renderer, when `_looks_like_rotating_id(device.name)` is True, substitute the i18n string `(rotating ID)` (dim italic style) for the name column. Leave `device.name` untouched on the data class.
- [ ] 3.3 Add `(rotating ID)` to `src/diting/i18n.py` (EN catalog key → `(临时标识)` ZH value).
- [ ] 3.4 In the BLE detail modal (`BLEDetailScreen._render_body` in `src/diting/tui.py:4078+`), add a `Raw name:` row in the Identity section that surfaces `device.name` verbatim — only when `device.name` is non-empty. Add the i18n key (`Raw name` → `原始名称`).
- [ ] 3.5 Unit tests in `tests/test_tui.py`:
  - predicate True on Apple Continuity-shape names (`NZ1NhvIw3H5T5cSy3kULrJ`)
  - predicate True on Huami serials (`Z-GM0YXG6A`)
  - predicate False on `iPhone`, `ccy's iPhone 15 Pro Max`, `HW Watch GT`, `abc`, `None`
  - row renders `(rotating ID)` (EN) or `(临时标识)` (ZH) when predicate True
  - detail modal renders `Raw name:` row when predicate True and `device.name` is non-empty
  - detail modal omits `Raw name:` row when `device.name` is None

## 4. Fix 3 — Events modal consecutive BLE-seen grouping

- [ ] 4.1 In `src/diting/tui.py`, locate the EventsScreen body renderer (the function consuming `EventRing` snapshots into row text). Wrap the per-row loop with a run-length compaction pass that groups consecutive `BLEDeviceSeenEvent`s with the same `(vendor, name_label)` tuple.
- [ ] 4.2 The `name_label` computation SHALL reuse the same `_looks_like_rotating_id` predicate from Fix 2 so rotating-ID rows fold together even when the underlying names differ per identifier.
- [ ] 4.3 Apply the existing filter cycle BEFORE grouping (the spec is explicit on order — filtering happens first; grouping happens over the filtered list).
- [ ] 4.4 Render the grouped row as `HH:MM:SS  [BLE]  device seen: <vendor>  ·  <name_label>  ×N  → HH:MM:SS` (the trailing `→` only when `N ≥ 2`).
- [ ] 4.5 Confirm `event_log.EventLogger.emit_ble_device_seen` is untouched — grouping is purely modal-render-time.
- [ ] 4.6 Confirm `tests/test_event_log.py` still passes byte-identical JSONL assertions.
- [ ] 4.7 Unit tests in `tests/test_tui.py` (events modal section):
  - three consecutive identical Apple-anonymous events fold to one `×3` row with `→` to the latest timestamp
  - vendor change breaks the run
  - non-BLE event between two identical BLE-seens breaks the run
  - rotating-ID label fold (three different identifier names from the same vendor all collapse under `(rotating ID) ×3`)
  - filter to roam suppresses BLE entirely; switching back to BLE recomputes grouping over the filtered list

## 5. Snapshot regression

- [ ] 5.1 Run `uv run python scripts/tui_snapshot.py --mode regression`. All existing fixtures SHALL pass — none of them rely on un-padded MACs, high-entropy BLE names, or anti-grouped event flood.
- [ ] 5.2 Add a synthetic fixture under `tests/snapshots/` that exercises the rotating-ID guard (a BLE row whose `name` matches the predicate) so future regressions land on the heuristic immediately.
- [ ] 5.3 Add a synthetic fixture that exercises the events-modal grouping (an EventRing with 5+ identical consecutive BLE-seens).

## 6. CI gates

- [ ] 6.1 `uv run pytest` — green
- [ ] 6.2 `uv run python scripts/tui_snapshot.py --mode regression` — green
- [ ] 6.3 `openspec validate --specs --strict` — green
- [ ] 6.4 `openspec validate tui-audit-followup-2026-05-25 --strict` — green

## 7. Wrap-up

- [ ] 7.1 Confirm no edits leaked into `openspec/specs/*` outside the archive step
- [ ] 7.2 Confirm EN ↔ ZH parity on every `i18n.py` and `docs/` edit
- [ ] 7.3 README + `docs/zh/README.md` audit — no user-facing surface change here, so likely no edit; verify and note in the PR description
- [ ] 7.4 Commit and push the branch `fix/tui-audit-followup-2026-05-25`
- [ ] 7.5 Open the PR using the repo template; reference the audit findings file path in the PR description
