<sub>**English** · [中文](../docs/zh/TESTING.md)</sub>

# Test Design

This document is the **canonical test plan** for wifiscope. It lives
next to the test code in `tests/`. It describes what we test, why,
and the exact set of scenarios captured as automated cases. Tests in
this directory **must conform** to this document — adjustments / new
scenarios start by editing this file and only then translate into
Python.

If you are reviewing a PR, this is what to read first; the code
should match it case-for-case.

---

## 1. Scope

### In scope

- **Pure-logic transforms** that decide what wifiscope shows: AP
  resolution, signal-band labelling, scan / connection merging,
  group-by-AP clustering.
- **External-protocol parsing**: helper subprocess JSON (schema v1
  and v2), inventory YAML loading.
- **TUI smoke**: the App can mount, every binding fires without
  raising, the help modal opens and closes.

### Out of scope

- **Live CoreWLAN / SCDynamicStore calls.** These depend on whether
  a Wi-Fi association exists at the moment of the test, which is
  neither deterministic nor available on CI runners. SCDynamicStore
  bplist parsing is also out of scope here — there is no good way to
  fixture a representative blob without snapshotting hex.
- **The Swift helper binary itself.** It is exercised by hand during
  development; the Python side mocks `subprocess.run` at the boundary.
- **Visual rendering** (colours, bar widths, alignment). Smoke tests
  prove the App composes; pixel-perfect screenshots would be brittle
  without buying us much.
- **Performance.** Polling and rendering are dominated by I/O on the
  helper subprocess; we monitor anecdotally rather than benchmark.

---

## 2. Layers

| Layer | Where | What it proves |
|---|---|---|
| Unit  | `tests/test_network.py`, `test_helper.py`, `test_tui_helpers.py`, `test_ble.py`, `test_i18n.py` | Each pure function behaves as specified across its full input space, including the regression cases from real bugs. |
| Smoke | `tests/test_tui_smoke.py` | The Textual App can be composed, mounted, driven through every binding (including the new `n` view toggle), and unmounted, without exceptions. Uses a `_FakeBackend` that returns deterministic data. |

---

## 3. Module: `wifiscope.network`

Resolves a BSSID to a physical-AP identity. This module has had two
real production bugs (prefix5 collisions in one OUI; cross-OUI VAP
allocations) so the matching rules carry the most test weight.

**Coverage targets:**

- [x] Primary rule — first 5 octets match + last-byte proximity window
- [x] Secondary rule — octets 2..5 match + same window
- [x] Window cap at 8 (no false matches across loose-distance APs)
- [x] `radio_overrides` precedence
- [x] `is_same_ap` symmetry across OUI variants and across rule
      tiers
- [x] `cluster_label` chip-bit grouping
- [x] `band_label` channel→band mapping (2.4 / 5 / unknown)
- [x] `format_bssid` rendering when alias known / unknown / None
- [x] `load_inventory` YAML happy path + error paths

### Test cases — `tests/test_network.py`

| Test | Scenario | Why it matters |
|---|---|---|
| `test_resolve_primary_rule[...]` (10 parameter rows) | Each AP's 2.4 GHz radio (mgmt + 1) and 5 GHz radio (mgmt + 4) resolves to the right AP name, across all 5 user APs (4 × AX51-E, 1 × AX60_2). | This is the primary rule's complete proof on real-world data from the user's H3C deployment. |
| `test_resolve_three_aps_in_one_oui_do_not_collapse` | Three APs share `40:fe:95:8a:3c:..` prefix and differ only in the last mgmt byte (07 / 15 / 54). Each AP's radios resolve to *its own* name, not all to AP 1. | Regression for the bug where prefix5 alone matched any AP in the OUI and `resolve` returned the first list entry, mislabelling B2 / 3F radios as B1. |
| `test_resolve_outside_window_returns_none` | A BSSID whose last byte is `0x40` — far outside the +8 window from any mgmt MAC — does NOT match an AP that happens to share its prefix5. | Window cap prevents the primary rule from sweeping in arbitrary unrelated BSSIDs whose first five octets happen to coincide. |
| `test_resolve_secondary_rule_cross_oui[...]` (5 parameter rows) | H3C's "internal" SSIDs sit on `44:fe:95:..` but the chip serial bytes (positions 2..5) match the `40:fe:95:..` mgmt MAC. All variants resolve. | Secondary rule's proof. Without it `H3C_89C7DF_WIFI5` showed as a stranger AP in the user's screenshot. |
| `test_resolve_unrelated_returns_none` (5 parameter rows) | Neighbour APs (`82:48:3b:..`, `c2:91:7c:..`, etc.) and `None` itself do not match any inventory entry. | Defends against false positives — the user's neighbours must not light up as their own APs. |
| `test_radio_overrides_win_over_rule_match` | A BSSID that *would* resolve via the primary rule is overridden by an explicit entry in `radio_overrides`. | Documents the documented escape hatch's precedence. Important for vendors that randomise per-radio MACs. |
| `test_radio_overrides_case_insensitive` | An override keyed lower-case matches an upper-case BSSID lookup. | YAML editors / vendor docs use mixed casing; lookup must not care. |
| `test_is_same_ap_within_inventory` | Two BSSIDs that resolve to the same AP name return True; two distinct AP names return False. | Drives roam classification — band-switch vs inter-AP roam. |
| `test_is_same_ap_cross_oui_within_inventory` | A 40: BSSID and a 44: BSSID both resolving to the same AP are treated as one AP. | Specifically tests that the band-switch detection survives the H3C cross-OUI layout. |
| `test_is_same_ap_neither_in_inventory_falls_back_to_prefix` | When neither side is in inventory, fall back to prefix5 / mid4 grouping. | Lets roam classification work on a fresh install without `aps.yaml`. |
| `test_is_same_ap_mismatch_when_one_resolves` | One resolves, the other doesn't, even though prefixes match — they are NOT the same AP. | Prevents an unaliased neighbour from being conflated with a known AP just because they share a chip-prefix coincidence. |
| `test_band_label[...]` (9 parameter rows) | Channels 1, 6, 14 → 2.4G; 36, 157, 177 → 5G; 15, 200, None → None. | Boundary coverage of the channel-to-band mapping. Drives the `band` column header. |
| `test_cluster_label_groups_chip` | Five BSSIDs across 40:/44: prefixes that share octets 3..5 collapse to one `?XX:YY:ZZ` label. | Auto-discovery groups every radio of one chip without inventory. |
| `test_cluster_label_separates_unrelated` | Three different physical neighbour APs each get their own cluster label. | Defends against the "all neighbours look like one AP" failure. |
| `test_cluster_label_none_or_malformed` | None → `?`; non-MAC string → `?`. | Defensive: the function never raises. |
| `test_format_bssid_known_with_band` | Inventory-resolved BSSID renders as `<AP-name> (<band>) (<bssid>)`. | The full identity string the Connection panel displays. |
| `test_format_bssid_unknown_passthrough` | Unaliased BSSID renders as the raw MAC, no prefixes added. | Avoids confusing the user with a `?` prefix in places where they only see one AP. |
| `test_format_bssid_none` | None renders as the literal `n/a`. | Disconnected or fully-redacted state. |
| `test_load_inventory_missing_file_returns_empty` | `load_inventory(<missing>)` returns an empty inventory, not an exception. | First-run UX: no `aps.yaml` should be friendly. |
| `test_load_inventory_well_formed` | A correct YAML with `aps:` and `radio_overrides:` round-trips into the right structure. | Happy-path proof against the documented schema. |
| `test_load_inventory_missing_keys_raises` | A `name`-only AP entry (no `mgmt_mac`) raises `ValueError`. | Editing typos must fail loudly, not silently produce a half-configured inventory. |
| `test_load_inventory_top_level_must_be_mapping` | A YAML list at the top level raises `ValueError`. | Same loud-failure contract. |

---

## 4. Module: `wifiscope._helper`

Owns the subprocess protocol with the Swift sidecar. The wire format
is forward-compatible (the helper's `schema` field), so we test both
v1 (string `interface`) and v2 (dict `interface`) shapes.

**Coverage targets:**

- [x] JSON schema v1 ↔ v2 compatibility
- [x] Identity field redaction handling (None vs populated)
- [x] CWNetwork "0 is no measurement" sentinel normalisation
- [x] BSSID case normalisation
- [x] Robustness: malformed JSON, non-zero exit, timeout
- [x] `has_permission` heuristic (any populated BSSID = granted)
- [x] `bundle_path` extraction from binary path
- [x] `find_helper` search-order honouring of `WIFISCOPE_HELPER`

### Test cases — `tests/test_helper.py`

| Test | Scenario | Why it matters |
|---|---|---|
| `test_scan_v2_returns_networks_and_iface_meta` | Schema v2 payload (interface dict with country / hardware) parses into ScanResult list and a non-empty meta dict. | Primary case for the current helper output. |
| `test_scan_v1_iface_string_yields_empty_meta` | Schema v1 payload (interface plain string) parses networks correctly; meta dict comes back empty rather than crashing. | Back-compat with helpers built before the v2 schema. Old `/Applications/wifiscope-helper.app` still works after `uv run wifiscope` upgrades. |
| `test_scan_zero_noise_and_zero_rssi_become_none` | Helper output of `0` for noise / RSSI is normalised to `None` on the Python side. | CoreWLAN uses `0` as "no measurement"; passing it through would render misleading values (e.g. "0 dBm" — which is a perfect signal!) in the panel. |
| `test_scan_lowercases_bssid` | An upper-case BSSID in the JSON comes back lower-case in `ScanResult.bssid`. | Inventory lookup is case-insensitive only because data is normalised on ingest. |
| `test_scan_redacted_row_keeps_bssid_none` | A network entry without `ssid` / `bssid` keys (helper has no Location grant) yields a ScanResult with both as None and other fields populated. | Without permission, RSSI / channel still flow through; the panel's "(redacted)" label depends on this exact shape. |
| `test_scan_malformed_json_returns_empty` | Garbage stdout returns `([], {})`. | A broken helper must not crash the TUI. |
| `test_scan_nonzero_exit_returns_empty` | Non-zero exit code returns `([], {})`. | Same. Backend then falls back to direct CoreWLAN. |
| `test_scan_subprocess_timeout_returns_empty` | `subprocess.TimeoutExpired` returns `([], {})`. | A hung helper must not block the poll loop indefinitely. |
| `test_has_permission_true_when_any_bssid_populated` | At least one network with a populated BSSID → `True`. | The "the helper has Location grant" liveness probe used in the auto-launch flow. |
| `test_has_permission_false_when_all_redacted` | Every network has BSSID None → `False`. | Drives the prompt-for-grant logic on first launch. |
| `test_has_permission_false_on_subprocess_error` | OSError (helper binary missing / not executable) → `False`. | Defensive: lack of grant is indistinguishable from missing helper here. |
| `test_bundle_path_extracts_app_dir` | Given a path inside `<bundle>.app/Contents/MacOS/binary`, `bundle_path` returns the `.app` directory. | Lets the auto-launch flow `open` the bundle (which triggers the system Location prompt) given only the binary it found. |
| `test_bundle_path_none_for_loose_binary` | A binary not inside any `.app` returns None. | Honest about the limitation — without a bundle there is no UI to launch. |
| `test_find_helper_env_override_wins` | `WIFISCOPE_HELPER` set to a bundle path beats any standard install location. | Documents the documented override priority. |
| `test_find_helper_env_override_can_point_at_binary` | The env var may also point directly at the executable rather than the bundle. | Dev-loop convenience. |
| `test_find_helper_returns_none_when_nothing_present` | Env var pointing at a missing path AND `HOME` redirected away → `None`. | Auto-launch then falls through to the build path. |

---

## 5. Module: `wifiscope.tui` (helpers)

Pure data transforms used by the Nearby APs panel. The TUI wiring
itself is covered by the smoke tests in section 6.

**Coverage targets:**

- [x] `_merge_current` synthesises when the current AP is missing from
      scan
- [x] `_merge_current` replaces when the current AP is already in
      scan, preserving Connection-side authoritative values
- [x] `_merge_current` no-op when disconnected or BSSID unknown
- [x] `_group_by_ap` clusters inventory matches AND cross-OUI variants
- [x] `_group_by_ap` floats the user's current group to position 0
- [x] `_group_by_ap` sorts groups by best RSSI desc otherwise
- [x] `_group_by_ap` sorts within each group by RSSI desc
- [x] `_group_by_ap` collapses unaliased rows under cluster_label

### Test cases — `tests/test_tui_helpers.py`

| Test | Scenario | Why it matters |
|---|---|---|
| `test_merge_current_prepends_when_scan_omits_associated_ap` | CoreWLAN scan returns rows for OTHER APs; the current AP gets prepended as a synthetic row sourced from Connection. | The most common production case — macOS often omits the associated AP from scan output. The user must always see their own row. |
| `test_merge_current_replaces_when_scan_already_has_ap` | Scan already includes the current AP with stale RSSI / channel; the merged list keeps the BSSID once but with Connection-side values. | Avoids the panel showing "ch 161 / -80" for the same BSSID the Connection panel displays as "ch 157 / -50" — DFS hops can desync the two snapshots. |
| `test_merge_current_no_op_when_disconnected` | Connection is `None`; the scan list is returned unchanged. | Disassociated state should not synthesise a phantom row. |
| `test_merge_current_no_op_when_connection_has_no_bssid` | Connection has `bssid=None` (e.g. fully redacted, no helper); the scan list is returned unchanged. | Cannot synthesise a row without a key to dedup against. |
| `test_merge_current_case_insensitive_match` | Connection BSSID lower-case, scan BSSID upper-case — dedup still hits. | Scan output sometimes comes from CoreWLAN in upper-case while Connection paths normalise to lower. |
| `test_group_by_ap_clusters_inventory_matches` | Three BSSIDs all resolving to one AP (incl. one cross-OUI 44:* variant) form one group with three rows. | Demonstrates the grouping uses the same `resolve()` path as the rest of the UI. |
| `test_group_by_ap_separates_distinct_aps` | Two BSSIDs from two different APs go into two groups. | Sanity. |
| `test_group_by_ap_floats_current_to_first` | A weak-signal current AP (-80) sits above a strong neighbour (-30). | The user's own AP must be discoverable at a glance, regardless of signal. |
| `test_group_by_ap_otherwise_sorts_by_best_rssi` | With no current AP, groups order by their strongest member. | The default reading order matches "what's nearby and strong". |
| `test_group_by_ap_within_group_sorts_by_rssi_desc` | Within one AP's bucket, rows go strongest first. | Lets the user spot the radio with the best link to that AP. |
| `test_group_by_ap_unaliased_uses_cluster_label` | Two BSSIDs sharing octets 3..5 (e.g. neighbour with two BSSIDs) collapse under one `?XX:YY:ZZ` cluster — and that key starts with `?` so the renderer can style it dimly. | Inventory-free grouping, plus the renderer-style contract. |
| `test_group_by_ap_empty_input` | Empty input → empty groups list. | Defensive. |

---

## 5b. Module: `wifiscope.ble`

The async BLE scanning layer. Owns the JSONL line parser, the rolling
device-map TTL, the rotated-UUID fuzzy merger, vendor lookup, and
service-category inference. The Swift helper subprocess is mocked at
the spawn boundary via the `BLEPoller(_spawn=...)` test seam so the
suite stays hermetic on Linux CI runners that have no Bluetooth
hardware (and macOS runners that have no granted helper).

**Coverage targets:**

- [x] JSONL line parsing — every advertisement field populates the
      BLEDevice correctly; subsequent ads carry `first_seen` forward
      and bump `ad_count`.
- [x] Vendor lookup — Apple's company ID resolves; unknown / None
      input is friendly.
- [x] Bundled vendor JSON ships with at least the Apple entry — guards
      against `make update-vendors` regressing the file.
- [x] Service category inference — known 16-bit UUIDs map to readable
      names; long-form (128-bit) is normalised; unknown UUIDs pass
      through.
- [x] Decay / TTL — devices unseen for >ttl_s drop from the snapshot;
      devices within ttl_s are kept.
- [x] Fuzzy merge — same `(vendor_id, name)` within ±10 dB folds into
      one row with `ad_count` summed and `merged_count` set; entries
      outside the window stay separate; anonymous (no vendor, no name)
      devices never merge.
- [x] Snapshots are sorted by RSSI desc.
- [x] Permission denied — both via JSON error line and via subprocess
      exit code 3 — flips `permission_state` to `"denied"` cleanly.
- [x] Subprocess crash mid-stream — no exception bubbles up; subsequent
      snapshots remain stable.
- [x] Helper binary missing — flips state to `"unavailable"`, snapshots
      keep coming.
- [x] Malformed JSON line — silently skipped; subsequent valid lines
      parse normally.

### Test cases — `tests/test_ble.py`

| Test | Scenario | Why it matters |
|---|---|---|
| `test_parse_advertisement_populates_all_fields` | A well-formed JSONL event becomes a BLEDevice with every field populated and identifier lower-cased. | Primary parser proof — the wire format from the helper. |
| `test_parse_subsequent_advertisement_carries_history` | A repeat ad for the same identifier preserves `first_seen` and bumps `ad_count`; `last_seen` advances. | Ad rate / duration drives the panel's "X seconds ago" column and merge heuristic stability. |
| `test_lookup_vendor_known_company_id` | Apple's well-known SIG company ID resolves to "Apple, Inc.". | Sanity for the most common BLE vendor. |
| `test_lookup_vendor_unknown_returns_none` | An unassigned company ID resolves to None. | Renderer falls back to the raw ID for the user to investigate. |
| `test_lookup_vendor_none_input_returns_none` | The "no manufacturer data" case (most common BLE state) is silent. | Defensive — function never raises. |
| `test_load_vendors_ships_apple_id` | The bundled JSON contains entry 76 → "Apple, Inc.". | Guards against `make update-vendors` writing an empty / malformed file. |
| `test_service_category_heart_rate` | `180D` → `"Heart Rate"`. | Spec-listed category mapping. |
| `test_service_category_hid` | `1812` → `"HID"`. | Spec-listed category mapping. |
| `test_service_category_unknown_passthrough` | An unknown UUID returns unchanged. | Honest about what we don't know. |
| `test_service_category_long_form_normalised` | The 128-bit Bluetooth SIG base form of `180D` resolves to `"Heart Rate"`. | macOS reports either form; lookup must match both. |
| `test_expire_drops_unseen_devices` | A device whose `last_seen` is older than `ttl_s` is removed from the snapshot. | Stops the panel hoarding stale rows after a device walks away. |
| `test_expire_keeps_recent_devices` | A device seen within `ttl_s` is retained. | Sanity bound — dropped only when stale. |
| `test_merge_folds_same_vendor_and_name_within_rssi_window` | Two records sharing `(vendor_id, name)` and within ±10 dB merge into one row with `ad_count` summed and `merged_count = 2`. | Primary fuzzy-merge proof — drives the (merged N) badge. |
| `test_merge_keeps_distant_rssi_separate` | Two records sharing identity but with RSSIs > 10 dB apart stay separate. | Likely different physical devices in different rooms; merging would lie. |
| `test_merge_does_not_combine_anonymous_devices` | Devices with both `vendor_id` and `name` None are never merged. | The heuristic would conflate every nameless beacon nearby — spec says "never silently fall back". |
| `test_merge_sorts_by_rssi_descending` | The post-merge list is ordered by signal strength. | The closest device is at the top of the panel. |
| `test_permission_denied_line_surfaces_state` | A JSON error line with "unauthorized" returns `"permission_denied"` from `update_from_line`. | Driver for the BLE panel's "(BLE permission required)" placeholder. |
| `test_permission_denied_via_subprocess_exit_code` | Helper exits with code 3 — poller flips `permission_state` to `"denied"`. | Same outcome regardless of which signalling channel the helper used. |
| `test_subprocess_crash_does_not_raise` | Helper killed mid-stream (137) leaves the poller quiet — future snapshots are empty, no exception bubbles up. | A SIGKILL during a system Bluetooth restart should not tear down the TUI. |
| `test_helper_binary_missing_marks_unavailable` | OSError at spawn flips state to `"unavailable"`; snapshots keep coming. | First-launch case before the helper is built / granted. |
| `test_malformed_line_skipped_subsequent_parsed` | Garbage line is skipped; the next valid line parses. | Helper line corruption (encoding glitch, partial write) cannot wedge the parser. |
| `test_line_without_id_field_skipped` | A JSON object lacking `id` is skipped, not raised. | Defensive against schema drift from the helper. |

---

## 6. TUI smoke

End-to-end via Textual's `run_test` pilot. The fake backend ensures
the test runs the same on a CI runner with no Wi-Fi as it does on a
real Mac.

**Coverage targets:**

- [x] App composes and unmounts cleanly
- [x] Each binding (`q`, `p`, `r`, `s`, `c`, `h`, `n`) does not raise
- [x] Help modal opens and closes via Esc and via `h` again
- [x] Help modal actually appears in the screen stack
- [x] `scan_interval` constructor argument threads through to the
      poller
- [x] `n` toggles the third panel slot between Wi-Fi scan and BLE
      view; both widgets stay mounted, only `display` flips

### Test cases — `tests/test_tui_smoke.py`

| Test | Scenario | Why it matters |
|---|---|---|
| `test_app_boots_and_quits` | Compose, mount, render once, press `q`, exit. | Minimum proof the App is wired — guards against import-time / mount-time errors that the unit tests would not catch. |
| `test_pause_and_resume` | Press `p` twice. | Pause mutation does not break rendering on resume. |
| `test_force_rescan_does_not_crash` | Press `r`. | The poller's `force_rescan` path executes without issues. |
| `test_cycle_sort_modes` | Press `s` twice. | Both sort modes render to completion. Cross-references `_group_by_ap` from section 5. |
| `test_help_modal_open_and_close` | Press `h`, then Esc. | Regression — an earlier version used `bold $accent` (Textual CSS variable) in a Rich style and crashed on first show. |
| `test_help_modal_h_to_close` | Press `h` to open, `h` again to close. | Convenience binding inside the modal. |
| `test_help_modal_renders_through_pilot_query` | Open the modal and assert via `app.screen_stack` that exactly one HelpScreen is on the stack; close and assert zero. | Catches regressions where the binding handler runs but the widget never actually mounts. |
| `test_custom_scan_interval_threads_through` | Construct `WifiScopeApp(..., scan_interval=4.5)` and inspect `app._poller._scan_interval`. | The `WIFISCOPE_SCAN_INTERVAL` env var lands here; if the kwarg path silently lost it, we'd never know. |
| `test_toggle_view_swaps_third_panel` | Press `n` to toggle from the Wi-Fi scan view to the BLE view; press again to return. Asserts on the `display` flag of both panels and on `app._view_mode`. | Locks the spec's "toggle in place" behaviour — neither panel ever unmounts, so consumer state on either side survives the swap. |

---

## 7. Running the suite

```bash
uv run pytest                            # full suite
uv run pytest tests/test_network.py      # one module
uv run pytest -k "merge_current"         # name-substring filter
uv run pytest -v                         # one PASSED line per test
uv run pytest -x                         # stop on first failure
uv run pytest --tb=long                  # full tracebacks
uv run pytest --collect-only -q          # list every case without running
```

CI runs `uv run pytest` on macos-latest against Python 3.11 / 3.12 /
3.13 for every push and pull request to `main`. See
[`.github/workflows/test.yml`](../.github/workflows/test.yml).

---

## 8. Adding tests

The workflow when iterating wifiscope:

1. **Edit this document first.** Add the new test row(s) to the
   appropriate module section. Frame the scenario in plain language
   and explain why it matters (a bug? a UX invariant? a contract
   with another module?).
2. **Translate to code.** Implement the test in the matching
   `tests/test_*.py` file with the same name and docstring.
3. **Run locally.** `uv run pytest` must be green before pushing.
4. **CI runs the same.** Pushing and opening a PR triggers the
   `tests` workflow.

When a behavior change is made:

1. Find the test rows here that the change invalidates.
2. Update the row's "Scenario" / "Why it matters" to reflect the
   new behaviour.
3. Update the test code.
4. If the change captures a new bug, add a new "regression" row
   with a brief one-line description of the bug it prevents from
   recurring.

When deleting / merging tests:

- Remove the row here in the same commit. Documentation drift on
  test cases is the main thing this file is here to prevent.

---

## 9. Future / deferred

Capturing here so they don't get lost:

- **Live CoreWLAN integration test** that actually exercises
  `MacOSWiFiBackend.get_connection()` against a real Mac — gated
  behind a `--live` flag so CI skips it but a developer can run
  `uv run pytest --live` on a connected Mac before a release.
- **SCDynamicStore parser test** with a captured bplist fixture
  (base64-encoded, ~5 KB) so the channel / BSSID extraction logic
  in `_dynamic_store.py` has a regression net.
- **Helper Swift smoke** via `swift build` + `bundle/MacOS/binary
  scan` in CI, asserting at least an empty-shape JSON document.
- **Visual snapshot of the TUI** (Textual SVG or text) on a known
  fake backend — useful when refactoring rendering.
- **Property-based tests** for `_group_by_ap` invariants
  (associativity over scan order, current-AP-first regardless of
  RSSI).

These are deferred until the maintenance cost is justified by an
observed gap.
