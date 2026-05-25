## 1. Test plan updates (test-first, per CLAUDE.md hard rule)

- [x] 1.1 Add a "MAC zero-pad at ARP ingest" section to `tests/TESTING.md` describing the `_read_arp_cache` normalisation cases (already-padded, stripped, mixed)
- [x] 1.2 Mirror the section into `docs/zh/TESTING.md` (ZH parity rule)
- [x] 1.3 Add a "BLE rotating-ID name guard" section to `tests/TESTING.md` covering predicate true/false cases, raw-name modal row, and EN+ZH catalog strings
- [x] 1.4 Mirror into `docs/zh/TESTING.md`
- [x] 1.5 Add an "Events modal consecutive BLE-seen grouping" section to `tests/TESTING.md` covering consecutive fold, vendor break, non-BLE break, rotating-ID label fold, JSONL untouched, filter-then-group order
- [x] 1.6 Mirror into `docs/zh/TESTING.md`

## 2. Fix 1 — MAC zero-pad at ARP ingest

- [x] 2.1 In `src/diting/lan.py`, introduce a small `_canon_mac(raw: str) -> str` helper that zero-pads each octet and lowercases. Idempotent on already-padded input.
- [x] 2.2 Apply `_canon_mac` to the regex-captured MAC inside `_read_arp_cache`, before the multicast-destination filter so the filter sees canonical form too.
- [x] 2.3 Verify `_is_multicast_dest_mac` still works (it splits on `:`, so canonicalised octets compose cleanly).
- [x] 2.4 Add unit tests in `tests/test_lan.py`:
  - macOS-stripped input → padded output
  - already-padded input → identity
  - all-zeros tail (`00:00:…:00`) → preserved
  - upper-case input → lower-case padded output
  - one-octet line is rejected silently (existing behaviour preserved)
- [x] 2.5 Confirm the LAN detail modal pulls the padded form (no code change in `tui.py:5744`; covered by the data-boundary fix).

## 3. Fix 2 — BLE rotating-ID name guard

- [x] 3.1 In `src/diting/tui.py`, add `_looks_like_rotating_id(name: str | None) -> bool` near the BLE row formatter — pre-compiled regex constant, hard-coded Apple-product prefix tuple.
- [x] 3.2 In the BLE list row renderer, when `_looks_like_rotating_id(device.name)` is True, substitute the i18n string `(rotating ID)` (dim italic style) for the name column. Leave `device.name` untouched on the data class.
- [x] 3.3 Add `(rotating ID)` to `src/diting/i18n.py` (EN catalog key → `(临时标识)` ZH value).
- [x] 3.4 In the BLE detail modal (`BLEDetailScreen._render_body` in `src/diting/tui.py:4078+`), add a `Raw name:` row in the Identity section that surfaces `device.name` verbatim — only when `device.name` is non-empty. Add the i18n key (`Raw name` → `原始名称`).
- [x] 3.5 Unit tests in `tests/test_tui.py`:
  - predicate True on Apple Continuity-shape names (`NZ1NhvIw3H5T5cSy3kULrJ`)
  - predicate True on Huami serials (`Z-GM0YXG6A`)
  - predicate False on `iPhone`, `ccy's iPhone 15 Pro Max`, `HW Watch GT`, `abc`, `None`
  - row renders `(rotating ID)` (EN) or `(临时标识)` (ZH) when predicate True
  - detail modal renders `Raw name:` row when predicate True and `device.name` is non-empty
  - detail modal omits `Raw name:` row when `device.name` is None

## 4. Fix 3 — Events modal consecutive BLE-seen grouping

- [x] 4.1 In `src/diting/tui.py`, locate the EventsScreen body renderer (the function consuming `EventRing` snapshots into row text). Wrap the per-row loop with a run-length compaction pass that groups consecutive `BLEDeviceSeenEvent`s with the same `(vendor, name_label)` tuple.
- [x] 4.2 The `name_label` computation SHALL reuse the same `_looks_like_rotating_id` predicate from Fix 2 so rotating-ID rows fold together even when the underlying names differ per identifier.
- [x] 4.3 Apply the existing filter cycle BEFORE grouping (the spec is explicit on order — filtering happens first; grouping happens over the filtered list).
- [x] 4.4 Render the grouped row as `HH:MM:SS  [BLE]  device seen: <vendor>  ·  <name_label>  ×N  → HH:MM:SS` (the trailing `→` only when `N ≥ 2`).
- [x] 4.5 Confirm `event_log.EventLogger.emit_ble_device_seen` is untouched — grouping is purely modal-render-time.
- [x] 4.6 Confirm `tests/test_event_log.py` still passes byte-identical JSONL assertions.
- [x] 4.7 Unit tests in `tests/test_tui.py` (events modal section):
  - three consecutive identical Apple-anonymous events fold to one `×3` row with `→` to the latest timestamp
  - vendor change breaks the run
  - non-BLE event between two identical BLE-seens breaks the run
  - rotating-ID label fold (three different identifier names from the same vendor all collapse under `(rotating ID) ×3`)
  - filter to roam suppresses BLE entirely; switching back to BLE recomputes grouping over the filtered list

## 4b. Fix 4 — ZH catalog copy gaps (2026-05-25 ZH-locale audit)

- [x] 4b.1 Add the missing `"LAN view, public scene only: open consent modal for a one-shot active probe (NBNS / SSDP / mDNS) — see below"` key to the ZH catalog in `src/diting/i18n.py` — the EN string at `tui.py:609-611` currently falls through to itself in ZH.
- [x] 4b.2 Change the self-mapped `"service": "service"` entry in `i18n.py` (line ~313) to `"service": "服务"`. Verify no caller compares against the EN display form rather than the canonical internal token (the sort-mode dispatch keys live on `_sort_mode`, not on the displayed string).
- [x] 4b.3 Change the self-mapped basics-modal section heading `"Noise / SNR": "Noise / SNR"` (i18n.py ~1096) to `"Noise / SNR": "Noise / 信噪比"`. Mirror the half-EN-half-ZH shape that `RSSI / 信号` already uses.
- [x] 4b.4 Change `" ago": "前"` (i18n.py:283) to `" ago": " 前"` so the bare time-ago key preserves its leading space. Verify the five concat sites (`tui.py:1783, 4112, 5954, 5957, 6140`) now render `8s 前`.
- [x] 4b.5 Change the Apple-Continuity category translations to brand-verbatim — `"Apple Companion": "Apple Companion"` (replaces `Apple 配对` at i18n.py:294) and add `"Apple Nearby": "Apple Nearby"` if the key isn't already self-mapped. Half-translated `Apple 邻近` SHALL NOT survive the change.
- [x] 4b.6 Reorder the BLE detail Activity ad-interval hint in ZH — the key is `"~{n} ms between ads"` or close; ZH currently echoes EN word order. Update to `"广告间隔约 {n} ms"` (or whichever placeholder name the EN key uses; preserve it exactly per the placeholder-parity requirement).
- [x] 4b.7 Re-run the ZH-locale audit to confirm every defect listed in iterations 1.1 / 2.1 / 3.1 / 4.1 / 5.1 / 6.1 / 8.1 of `/private/tmp/wfs-tui-audit-20260525-185519/findings.md` is gone.

## 5. Snapshot regression

- [x] 5.1 Run `uv run python scripts/tui_snapshot.py --mode regression`. All existing fixtures SHALL pass — none of them rely on un-padded MACs, high-entropy BLE names, or anti-grouped event flood.
- [x] 5.2 Add a synthetic fixture under `tests/snapshots/` that exercises the rotating-ID guard (a BLE row whose `name` matches the predicate) so future regressions land on the heuristic immediately.
- [x] 5.3 Add a synthetic fixture that exercises the events-modal grouping (an EventRing with 5+ identical consecutive BLE-seens).

## 6. CI gates

- [x] 6.1 `uv run pytest` — green
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression` — green
- [x] 6.3 `openspec validate --specs --strict` — green
- [x] 6.4 `openspec validate tui-audit-followup-2026-05-25 --strict` — green

## 7. Wrap-up

- [x] 7.1 Confirm no edits leaked into `openspec/specs/*` outside the archive step
- [x] 7.2 Confirm EN ↔ ZH parity on every `i18n.py` and `docs/` edit
- [x] 7.3 README + `docs/zh/README.md` audit — no user-facing surface change here, so likely no edit; verify and note in the PR description
- [x] 7.4 Commit and push the branch `fix/tui-audit-followup-2026-05-25`
- [x] 7.5 Open the PR using the repo template; reference the audit findings file path in the PR description
