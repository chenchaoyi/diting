<sub>**English** · [中文](../docs/zh/TESTING.md)</sub>

# Test Design

This document is the **canonical test plan** for diting. It lives
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

- **Pure-logic transforms** that decide what diting shows: AP
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
| Unit  | `tests/test_*.py` (excluding tui_smoke) | Each pure function behaves as specified across its full input space, including the regression cases from real bugs. |
| Smoke | `tests/test_tui_smoke.py` | The Textual App can be composed, mounted, driven through every binding, and unmounted, without exceptions. Uses a `_FakeBackend` that returns deterministic data. |
| Snapshot regression | `scripts/tui_snapshot.py --mode regression` | 11 scenarios exercise the rendered TUI under fixed synthetic inputs; assertions verify panel content, modal layout, and decoder output. CI uploads `snapshot-output/` on failure. |

---

## 2.5. Spec coverage matrix

For every Requirement under `openspec/specs/<name>/spec.md`, this
matrix points to the test that exercises it. Entries marked
**(review-enforced)** are conventions whose violation can't be caught
by a unit test; reviewers check them in PR. Entries marked
**(regression-only)** are exercised through `scripts/tui_snapshot.py
--mode regression` rather than direct pytest cases. **(gap)** flags
a Requirement with no current automated coverage — file an entry in
the roadmap to close it.

When a new Requirement lands in any spec, an entry MUST be added here
(and a test, unless review-enforced).

### `analyze`

| Requirement | Test |
|---|---|
| Pure rules, no LLM, no network | (review-enforced — code imports no network libs) |
| Report opens with span / counts / connection timeline | `test_analyze.py::test_render_includes_path_and_event_counts`, `::test_analyze_records_associations_and_roams` |
| Insights produced by named heuristics with explicit triggers | `test_analyze.py::test_repeated_disassociates_warns`, `::test_loss_burst_present_warns_real_loss`, `::test_short_session_triggers_low_data_hint`, `::test_timezone_mismatch_heuristic_triggers_on_hour_jump`, `::test_single_ap_medium_only_triggers_redundancy_hint`, `::test_latency_without_loss_triggers_jitter_hint` |
| Loss-pct rendering auto-detects 0..1 fractions vs 0..100 percent | `test_analyze.py::test_loss_burst_present_warns_real_loss` (covers the scaled-loss path) |
| Duration formatting honesty (`30s`, never `1 min`) | `test_tui_helpers.py::test_format_duration_short_buckets`, `::test_format_duration_short_negative_clamps_to_zero` |
| TODO section gates on whether any insight fires | `test_analyze.py::test_render_handles_zero_events`, `::test_empty_log_warns` |

### `anomaly-watchdog`

| Requirement | Test |
|---|---|
| `--notify` raises macOS Notification Centre alerts for `rf_stir` / `latency_spike` / `loss_burst` (both `monitor` and default TUI subcommand) | `test_watchdog.py::test_maybe_notify_fires_for_latency_spike`, `::test_maybe_notify_fires_for_loss_burst`, `::test_maybe_notify_fires_for_rf_stir_high_confidence`, `::test_maybe_notify_silent_when_notify_disabled` (call-site bail); TUI wire-up: `test_tui_smoke.py::test_app_with_notify_calls_watchdog_on_event` |
| `rf_stir` notifications gate on `DITING_NOTIFY_STIR_CONFIDENCE` (`high` default, `medium`, `all`) | `test_watchdog.py::test_should_notify_stir_default_gate`, `::test_should_notify_stir_medium_gate`, `::test_should_notify_stir_all_gate`, `::test_watchdog_config_falls_back_on_invalid_stir_gate` |
| Per-(event-type, target) silence window (default 60 s, `DITING_NOTIFY_SILENCE_S` override) | `test_watchdog.py::test_silence_clock_first_fire_returns_true`, `::test_silence_clock_second_fire_within_window_returns_false`, `::test_silence_clock_second_fire_after_window_returns_true`, `::test_silence_clock_independent_per_tuple`, `::test_watchdog_config_defaults_when_env_unset`, `::test_watchdog_config_parses_valid_env`, `::test_watchdog_config_falls_back_on_invalid_silence` |
| Notifications dispatched via the helper bundle's `notify` subcommand (icon = diting logo); missing helper → silent skip (no osascript fallback) | `test_watchdog.py::test_macos_notify_invokes_helper_notify_subcommand`, `::test_macos_notify_silent_when_helper_absent` |

### `ble-decoders`

| Requirement | Test |
|---|---|
| Decoders are `@register`-decorated functions | `test_decoders.py::test_registry_has_built_in_decoders` |
| Decoders never raise on malformed input | `test_decoders.py::test_decode_all_swallows_decoder_exceptions`; per-protocol `test_*_skips_truncated_*`, `test_*_skips_when_too_short` |
| Output keys protocol-namespaced | (review-enforced — convention checked in code review; canonical-decode tests assert namespaced keys) |
| Bundled decoders cover the public-spec protocols | iBeacon: `test_ibeacon_canonical_decode`; Eddystone: `test_eddystone_url_canonical_decode`, `::test_eddystone_uid_decode`, `::test_eddystone_tlm_decode`, `::test_eddystone_eid_frame_recognised_but_not_decoded`; Apple Continuity: `test_nearby_info_canonical_short_form`, `::test_find_my_short_form_minimum_payload`, `::test_handoff_canonical_decode`, `::test_handoff_chained_with_nearby_info_decodes_both`; MS CDP: `test_ms_device_beacon_real_capture`, `::test_swift_pair_decodes_utf8_model_name`; Ruuvi: `test_ruuvi_format5_canonical_decode`; Xiaomi / Huami: `test_xiaomi_canonical_decode_with_body`, `::test_xiaomi_short_frame_decodes_just_frame_byte`, `::test_xiaomi_skips_non_xiaomi_cid` |
| No semantic claims for unstable bits | (review-enforced — bundled decoders surface raw byte hex, no flag interpretations) |
| Decoders gate on identifying bytes | `test_decoders.py::test_ibeacon_skips_non_apple_cid`, `::test_nearby_info_skips_non_apple_cid`, `::test_eddystone_skips_non_feaa_service_data`, `::test_ms_device_beacon_skips_when_subtype_is_swift_pair`, `::test_ruuvi_skips_non_ruuvi_cid` |

### `ble-detail-modal`

| Requirement | Test |
|---|---|
| Rows selectable by identifier, stable across snapshots | `tui_snapshot.py::ble_detail_decoded` (regression-only) |
| Keyboard `up` / `down` / `enter` / `i` priority bindings | `tui_snapshot.py::ble_detail_decoded` walks cursor with `down` × N then `i` (regression-only) |
| Mouse click → select-and-inspect | (gap — manual / future regression) |
| Modal renders every BLEDevice field + decoded payload | `tui_snapshot.py::ble_detail_decoded` asserts `Decoded section header`, `iBeacon UUID rendered`, `iBeacon major+minor` (regression-only) |
| Activity section hides ad_count for connected peripherals | (review-enforced; visible in `live_ble_detail` explore captures) |
| RSSI sparkline when ≥ 2 history samples | `test_tui_helpers.py::test_rssi_sparkline_empty_history_returns_empty`, `::test_rssi_sparkline_single_sample_returns_empty`, `::test_rssi_sparkline_constant_rssi_renders_flat_line`, `::test_rssi_sparkline_maps_extremes_to_top_and_bottom_blocks`, `::test_rssi_sparkline_renders_one_char_per_sample` (rendering); `test_ble.py::test_history_records_and_returns_samples_in_order` (data path) |
| Modal close (Esc / `i` / `q`) doesn't mutate selection | (manual; modal binding is declarative) |
| Distance estimate labelled "rough free-space" | `test_tui_helpers.py::test_free_space_distance_m_at_one_meter_returns_one`, `::test_free_space_distance_m_doubles_at_minus_six_db`, `::test_free_space_distance_m_zero_rssi_returns_none` |

### `bonjour-detail-modal`

| Requirement | Test |
|---|---|
| Bonjour rows selectable by service-instance FQDN, stable across snapshots | `test_tui_smoke.py::test_bonjour_selection_keyed_by_fqdn_survives_resort`, `::test_bonjour_selection_clears_when_target_drops_out` |
| Keyboard `up` / `down` / `enter` / `i` priority bindings (no-op outside Bonjour view) | `test_tui_smoke.py::test_bonjour_inspect_opens_modal_on_first_press` |
| Mouse click → select-and-inspect | (manual; mouse path is the same `_bonjour_set_selected(inspect=True)` entry as the keyboard `i`) |
| Modal renders every `BonjourDevice` field, with TXT folding for long values | `test_tui_helpers.py::test_bonjour_detail_renders_identity_network_txt_activity_sections`, `::test_bonjour_detail_folds_long_txt_values`, `::test_bonjour_detail_omits_txt_section_when_empty` |
| Service-category lookup via i18n | `test_tui_helpers.py::test_bonjour_detail_renders_translated_category_when_known`, `::test_bonjour_detail_omits_category_row_when_unknown` |
| Modal close (Esc / `i` / `q`) doesn't mutate selection | (review-enforced; binding is declarative) |

### `bluetooth-scanning`

| Requirement | Test |
|---|---|
| Each helper JSONL line → exactly one BLEDevice | `test_ble.py::test_parse_advertisement_populates_all_fields`, `::test_parse_subsequent_advertisement_carries_history`, `::test_line_without_id_field_skipped` |
| Vendor resolution: 5-step deterministic chain | `test_ble.py::test_vendor_fallback_via_member_uuid_when_manufacturer_id_absent`, `::test_manufacturer_id_takes_priority_over_member_uuid_vendor`, `::test_service_data_uuid_resolves_vendor_when_service_uuids_empty`, `::test_advertising_vendor_falls_back_to_name_pattern`, `::test_vendor_id_carries_forward_when_scan_response_omits_manufacturer_data` |
| Connected peripherals via separate code path | `test_ble.py::test_connected_line_routes_to_connected_dict_only`, `::test_connected_entries_skip_advertising_ttl`, `::test_connected_snapshot_sentinel_prunes_disappeared_entries` |
| Rotated-identifier merge folds privacy-rotated rows | `test_ble.py::test_merge_folds_same_vendor_and_name_within_rssi_window`, `::test_merge_keeps_distant_rssi_separate`, `::test_merge_sorts_by_rssi_descending` |
| `(anonymous)` vs `(unknown)` distinction | `test_ble.py::test_merge_does_not_combine_anonymous_devices` (data path); `tui_snapshot.py::ble_normal` (rendering) |
| RSSI smoothing for stable sort order | `test_ble.py::test_rssi_smooth_seeds_from_first_sample`, `::test_rssi_smooth_dampens_packet_jitter`, `::test_merge_sort_key_uses_smoothed_rssi` |
| Schema-4 raw fields plumbed onto BLEDevice | `test_ble.py::test_schema_4_raw_passthrough_fields_populate`, `::test_schema_4_fields_default_when_helper_omits`, `::test_schema_4_fields_carry_forward_on_scan_response` |
| BLE history capped + pruned | `test_ble.py::test_history_records_and_returns_samples_in_order`, `::test_history_drops_none_rssi`, `::test_history_caps_at_maxlen`, `::test_history_get_unknown_device_returns_empty`, `::test_history_expire_drops_devices_not_in_set` |
| Categories diagnostic excludes protocol-utility GATT services | `test_ble.py::test_service_category_category_only_excludes_protocol_services` |
| Vendors diagnostic annotates folded-RPA-rotation count | `test_tui_helpers.py::test_ble_vendors_line_annotates_folded_rotation_count`, `::test_ble_vendors_line_skips_annotation_when_nothing_folded` |
| BLE row Name column cascades through `type` and `device_class` before falling back to `(unknown)`; Services column shows service-category only (no longer duplicates `type` / `device_class`) | `test_tui_helpers.py::test_ble_row_line_name_uses_helper_name_when_present`, `::test_ble_row_line_name_falls_back_to_type`, `::test_ble_row_line_name_falls_back_to_device_class`, `::test_ble_row_line_name_unknown_when_no_signal`, `::test_ble_label_summary_services_only` |

### `cli`

| Requirement | Test |
|---|---|
| `diting` no-subcommand launches TUI | (manual — App boot covered by `test_tui_smoke.py::test_app_boots_and_quits`) |
| Five subcommands: `once` / `watch` / `monitor` / `calibrate` / `analyze` | (gap — no integration test of the dispatch table; subcommand internals are tested individually) |
| `--lang en|zh` overrides env / locale | `test_i18n.py::test_resolve_cli_override_wins_over_env`, `::test_resolve_no_override_uses_env`, `::test_resolve_rejects_unknown_cli_value` |
| `--log [PATH]` enables JSONL logging with optional default path | `test_event_log.py::test_default_log_path_is_timestamped_jsonl`, `::test_resolve_log_path_cli_no_value_uses_default`, `::test_resolve_log_path_cli_explicit_path_wins`, `::test_resolve_log_path_env_auto_uses_default`, `::test_resolve_log_path_env_blank_disables`, `::test_extract_log_arg_no_value_returns_sentinel` |
| TUI exit prints analyze tip when `--log` was used | (gap — exit-hint string isn't covered by an automated assertion) |
| `diting monitor` emits JSONL on stdout, no banner | `test_event_log.py::test_to_path_writes_appendable_jsonl` (event format); banner-cleanliness is manual |
| `--config <PATH>` overrides aps.yaml search | `test_network.py::test_resolve_config_path_env_override_wins`, `::test_resolve_config_path_no_env_falls_through_to_default` |
| `--notify` valid on both default TUI subcommand and `monitor` | `test_tui_smoke.py::test_app_with_notify_calls_watchdog_on_event` (TUI wire-up); `test_watchdog.py::test_maybe_notify_fires_for_latency_spike` (monitor wire-up); flag-parsing is review-enforced |
| `--version` (or `-V`) prints `diting <version>` and exits 0, short-circuits before locale / TUI / helper work | `test_cli.py::test_version_flag_prints_running_version`, `::test_version_flag_short_dash_v`, `::test_version_short_circuits_before_locale` |

### `environment-monitor`

| Requirement | Test |
|---|---|
| σ thresholds defined as named constants | (review-enforced — STIR legend pulls from `DEFAULT_SPIKE_RATIO` / `DEFAULT_SPIKE_MIN_DB` at render time; `test_environment.py::test_sigma_above_threshold_fires_event` indirectly verifies the constants are wired correctly) |
| Spike fires only when ratio AND floor both exceeded | `test_environment.py::test_sigma_above_threshold_fires_event`, `::test_sigma_below_threshold_no_event` |
| Three fusion modes (co_located / spatial_channel / ignored) | `test_environment.py::test_co_located_vs_spatial_channel_classification`, `::test_redundancy_fusion_makes_two_co_located_events_high_confidence`, `::test_single_co_located_event_is_medium_confidence`, `::test_spatial_channel_event_uses_ap_location_label`, `::test_aps_below_minus_85_excluded` |
| Cooldown + rearm prevents repeat events | (gap — no direct cooldown / rearm test; behaviour is observed indirectly through fusion-confidence tests) |
| Calibration loadable from file | `test_environment.py::test_calibration_overrides_adaptive_baseline`, `::test_calibration_round_trip`, `::test_load_calibration_returns_empty_dict_on_missing_file` |
| Wording: correlation, not presence | (review-enforced — no string in `i18n.py` asserts "person" / "motion" / "presence") |

### `event-log`

| Requirement | Test |
|---|---|
| `--log` and `diting monitor` produce byte-identical streams | `test_event_log.py::test_to_path_writes_appendable_jsonl`, `::test_unicode_user_strings_survive_readable` (single shared writer class) |
| Writer flushes after every event | `test_event_log.py::test_line_buffered_writes_are_visible_before_close` |
| atexit hook closes writer cleanly | (gap — no direct test; behaviour validated by `test_line_buffered_writes_are_visible_before_close`) |
| JSONL keys English regardless of UI language | `test_event_log.py::test_schema_keys_stay_english_under_zh_locale` |
| Timestamps local-TZ ISO-8601 with offset | `test_event_log.py::test_timestamps_are_iso_utc`, `::test_naive_datetime_treated_as_local_not_utc` |
| Writer accepts `None` as no-op | `test_event_log.py::test_disabled_logger_is_a_no_op` |
| `connection_update` is log-only (not in EventRing) | `test_event_log.py::test_connection_update_emits_associated_on_first_poll`, `::test_connection_update_silent_when_first_poll_is_disassociated`, `::test_connection_update_emits_disassociate_on_drop`, `::test_connection_update_does_not_emit_on_bssid_to_bssid_change` |

### `events`

| Requirement | Test |
|---|---|
| Five event types share one schema and ring | `test_event_log.py::test_emit_roam_includes_kind_when_supplied`, `::test_emit_latency_spike_carries_target_and_rtt`, `::test_emit_loss_burst_carries_lost_in_window`, `::test_emit_link_state_dataclass_passthrough`, `::test_emit_network_change_carries_router_ip_transition` |
| Each event a frozen dataclass with timestamp | (compiler/dataclass-enforced; verified at construction in test files that build them) |
| EventRing size-bounded, single-thread async | (gap — no direct EventRing-cap test; ring is owned by App in production) |
| JSONL serialisation uses English keys | `test_event_log.py::test_schema_keys_stay_english_under_zh_locale` |
| Timestamps local-TZ ISO with offset | `test_event_log.py::test_timestamps_are_iso_utc`, `::test_naive_datetime_treated_as_local_not_utc` |
| `NetworkChangeEvent` is control-plane, not user-visible | `test_event_log.py::test_emit_network_change_carries_router_ip_transition` (the writer accepts it); user-visible-routing absence is review-enforced |

### `i18n`

| Requirement | Test |
|---|---|
| Language resolved exactly once at startup | `test_i18n.py::test_detect_explicit_diting_lang_wins_over_locale`, `::test_detect_zh_from_lang_env`, `::test_detect_zh_from_lc_all_overrides_lang`, `::test_detect_falls_back_to_english`, `::test_detect_ignores_invalid_diting_lang_value`, `::test_resolve_cli_override_wins_over_env`, `::test_resolve_no_override_uses_env`, `::test_resolve_rejects_unknown_cli_value`, `::test_set_lang_rejects_unknown_value` |
| User strings go through `t()` | `test_i18n.py::test_t_returns_english_when_lang_is_english`, `::test_t_falls_back_to_english_when_zh_key_missing`, `::test_t_substitutes_placeholders`, `::test_t_substitutes_in_english_too` (`t()` behaviour); review-enforced for "no hardcoded strings" coverage |
| Column-aligned widgets use `pad_cells` / `fit_cells` | `test_i18n.py::test_pad_cells_pads_ascii_to_target_width`, `::test_pad_cells_treats_cjk_as_two_cells_each`, `::test_pad_cells_returns_unchanged_if_already_wide`, `::test_pad_cells_handles_mixed_ascii_and_cjk` (note: `fit_cells` itself has no direct test — gap) |
| JSONL keys stay English in ZH UI | `test_event_log.py::test_schema_keys_stay_english_under_zh_locale` |
| Acronyms (SSID/BSSID/RSSI/...) untranslated | (review-enforced — catalog convention) |
| Catalog `{placeholder}` parity preserved | (review-enforced — would surface as KeyError at render) |

### `inventory`

| Requirement | Test |
|---|---|
| Four-step AP attribution chain | `test_network.py::test_radio_overrides_win_over_rule_match`, `::test_radio_overrides_case_insensitive`, `::test_resolve_primary_rule`, `::test_resolve_secondary_rule_cross_oui`, `::test_resolve_three_aps_in_one_oui_do_not_collapse`, `::test_resolve_outside_window_returns_none`, `::test_cluster_label_groups_chip` (fallback) |
| `aps.yaml` optional, tool runs without it | `test_network.py::test_load_inventory_missing_file_returns_empty` |
| Inventory carries Wi-Fi-OUI vendor map | `test_network.py::test_lookup_ap_vendor_known_oui_returns_name`, `::test_lookup_ap_vendor_unknown_oui_returns_none`, `::test_lookup_ap_vendor_invalid_input_returns_none`, `::test_lookup_ap_vendor_accepts_custom_map`, `::test_load_wifi_ouis_ships_xiaomi`, `test_ble.py::test_load_ouis_ships_apple_magic_keyboard_oui` |
| Cluster labels stable across sessions | `test_network.py::test_cluster_label_groups_chip`, `::test_cluster_label_separates_unrelated`, `::test_cluster_label_none_or_malformed` |
| BSSID format normalised (lowercase, colon-separated) | `test_network.py::test_format_bssid_known_with_band`, `::test_format_bssid_unknown_passthrough`, `::test_format_bssid_none`, `test_ble.py::test_lookup_oui_vendor_dash_separated_mac`, `::test_lookup_oui_vendor_colon_separated_mac` |

### `installation`

| Requirement | Test |
|---|---|
| One-line installer drops a working `diting` onto macOS without Python / uv / Xcode | (manual — end-to-end install on a fresh user account; the per-branch unit tests below cover the install.sh logic in isolation) |
| Installer refuses to run on non-macOS hosts with a clear error | `test_install.py::test_install_script_refuses_linux`, `::test_install_script_refuses_unknown_uname` |
| Tarball SHA256 verified against `SHASUMS256.txt`, mismatch aborts | `test_install.py::test_install_script_aborts_on_sha_mismatch`, `::test_install_script_accepts_matching_sha` |
| Tarball extracted under `~/.local/share/diting/`, symlinked at `~/.local/bin/diting`; sudo not required | `test_install.py::test_install_script_lays_out_user_local_paths_in_dry_run` |
| Helper bundle copied to `~/Library/Application Support/diting/`, quarantine xattr stripped, `open` primes TCC | `test_install.py::test_install_script_primes_application_support_helper_in_dry_run` |
| Install-time locale derived from `defaults read -g AppleLanguages` and threaded into the helper launch via `--env DITING_LANG=` AND `--args -AppleLanguages '(<tag>)'` so the helper UI and macOS TCC prompts agree on language | `test_install.py::test_install_script_primes_application_support_helper_in_dry_run` |
| PATH-update hint printed when `~/.local/bin` not on PATH (zsh / bash / fish detected) | `test_install.py::test_install_script_emits_zsh_path_hint`, `::test_install_script_silent_when_already_on_path` |
| `DITING_VERSION=vX.Y.Z` env var pins the install to a specific tag | `test_install.py::test_install_script_uses_diting_version_override` |
| Frozen-binary install coexists with `uv run diting` developer flow | (review-enforced — search-path priority pins the in-repo dev build first; tested via `test_helper.py::test_find_helper_repo_dev_build_shadows_application_support`) |

### `link-health`

| Requirement | Test |
|---|---|
| Gateway via ICMP, WAN via TCP/53 | `test_latency.py::test_ping_once_records_rtt`, `::test_parse_ping_time_ms_decimal`, `::test_parse_ping_time_ms_integer` (ICMP); `::test_tcp_probe_records_rtt_on_successful_connect`, `::test_tcp_probe_loss_on_timeout`, `::test_tcp_probe_loss_on_connection_refused` (TCP) |
| Rolling 60s window, monotonic clock eviction | `test_latency.py::test_aggregate_yields_median_loss_and_jitter`, `::test_aggregate_window_actually_drops_old_samples`, `::test_aggregate_loss_pct_in_zero_to_hundred_range`, `::test_aggregate_empty_returns_none_fields` |
| Network change → probe reset | (gap — `NetworkChangeEvent` is plumbed; reset behaviour observed via DNS-refresh tests `test_dns_refresh_runs_on_cadence`) |
| Loss burst + latency spike events | `test_latency.py::test_detect_latency_spike_requires_both_thresholds`, `::test_detect_loss_burst_three_of_last_five`, `::test_detect_loss_burst_one_loss_does_not_fire` |
| WAN-only outage distinguishable from full link loss | `test_latency.py::test_wan_skipped_reason_dns_eq_gateway`, `::test_wan_skipped_reason_no_dns` |

### `macos-helper`

| Requirement | Test |
|---|---|
| Helper ships as `.app` bundle, cdhash-keyed TCC grants | (manual — bundle build path; tested by users at install) |
| Helper exposes discrete subcommands as integration surface | `test_helper.py::test_has_ble_scan_subcommand_true_when_help_lists_it`, `::test_has_ble_scan_subcommand_false_for_pre_0_5_helper`, `::test_has_bluetooth_permission_true_on_zero_exit`, `::test_has_bluetooth_permission_false_on_unauthorized` |
| Wi-fi-scan JSON carries `schema` integer | `test_helper.py::test_scan_v2_returns_networks_and_iface_meta`, `::test_scan_v1_iface_string_yields_empty_meta`, `::test_scan_v3_parses_bss_load_and_station_count`, `::test_scan_v3_parses_802_11r_capability_flag` |
| BLE scan stream emits one JSON object per advertisement | `test_ble.py::test_malformed_line_skipped_subsequent_parsed`, `::test_mixed_stream_routes_each_line_to_correct_bucket` |
| Adv objects plumb required CoreBluetooth fields | `test_ble.py::test_schema_4_raw_passthrough_fields_populate` |
| Connected snapshots from IOBluetoothDevice (not CoreBluetooth) | `test_ble.py::test_connected_line_routes_to_connected_dict_only`, `::test_ble_scan_update_propagates_connected_through_poller` |
| Helper auto-detectable from Python | `test_helper.py::test_find_helper_env_override_wins`, `::test_find_helper_env_override_can_point_at_binary`, `::test_find_helper_returns_none_when_nothing_present`, `::test_bundle_path_extracts_app_dir`, `::test_bundle_path_none_for_loose_binary` |
| `find_helper()` also picks up the one-line installer's drop at `~/Library/Application Support/diting/diting-tianer.app`, with the in-repo dev build keeping priority | `test_helper.py::test_find_helper_picks_up_application_support_bundle`, `::test_find_helper_repo_dev_build_shadows_application_support` |
| Helper exits 3 + writes "bluetooth unauthorized" on TCC denial | `test_ble.py::test_permission_denied_via_subprocess_exit_code`, `test_helper.py::test_has_bluetooth_permission_false_on_unauthorized` |
| Helper bundle ships the diting logo as its AppIcon (`CFBundleIconFile=AppIcon`, full iconset committed) | `test_helper.py::test_helper_bundle_declares_appicon_and_ships_iconset` |
| Helper requests Location → Bluetooth → Notifications in sequence at install time (state machine in `HelperAppDelegate`) | (manual — verified by running `open helper/diting-tianer.app` after build and observing one prompt at a time on top of the status window) |
| Helper exposes `notify --title T --body B` subcommand using `UNUserNotificationCenter` under the bundle's identity | (manual — `helper/diting-tianer.app/Contents/MacOS/diting-tianer notify --title test --body hi` posts a banner with the diting logo) |
| Helper language fallback uses `Bundle.preferredLocalizations.first` (not `Locale.preferredLanguages.first`) so the helper UI matches the macOS-chosen `.lproj` | (review-enforced — Swift code in `detectHelperLang`) |

### `mdns-scanning`

| Requirement | Test |
|---|---|
| `BonjourPoller` passively browses the curated service-type list, never the meta-discovery type | `test_mdns.py::test_service_category_known_type_returns_friendly_name`, `::test_service_category_unknown_type_returns_none`, `::test_poller_subscribes_only_to_curated_list` |
| `BonjourDevice` carries the announce-derived fields (service_type, name, host, port, addresses, txt, vendor, category, first/last_seen) | `test_mdns.py::test_poller_emits_snapshot_after_first_announce`, `::test_txt_decode_drops_non_utf8_values` |
| Vendor resolved via 5-step chain (TXT vendor → OUI → hostname pattern → service-type hint → abstain) | `test_mdns.py::test_resolve_vendor_txt_field_wins`, `::test_resolve_vendor_hostname_pattern_falls_through_to_apple`, `::test_resolve_vendor_service_hint_catches_chromecast`, `::test_resolve_vendor_all_steps_abstain_returns_none` |
| State map expires on `remove_service` AND falls back to TTL | `test_mdns.py::test_poller_removes_on_remove_service_callback`, `::test_poller_ttl_fallback_when_no_remove_observed` |
| `BonjourPanel` renders vendor / name / services / age / id columns (no RSSI / signal-bar / connected split) | `test_tui_smoke.py::test_view_toggle_cycles_wifi_ble_mdns_wifi`, `tui_snapshot.py` (regression via explore mode; rendering shape) |
| Diagnostics panel renders mDNS-side rows when view is `mdns` | `test_tui_smoke.py::test_view_toggle_cycles_wifi_ble_mdns_wifi` |
| `BonjourPoller.stop()` cleanly joins zeroconf background threads | `test_mdns.py::test_poller_stop_joins_background_thread` |
| `zeroconf` import is lazy — never imported while the user stays in Wi-Fi view | `test_tui_smoke.py::test_app_constructs_bonjour_panel_lazily` |
| Bonjour stack pre-warms on the wifi → BLE step so the second `n` press (BLE → mDNS) does not pause | `test_tui_smoke.py::test_bonjour_prewarms_on_first_wifi_to_ble_switch` |
| Bonjour init runs on a worker thread (`asyncio.to_thread`) so the event loop is not blocked by the import or the `Zeroconf()` socket setup | `test_mdns.py::test_start_browser_runs_on_worker_thread`, `test_tui_smoke.py::test_bonjour_prewarms_on_first_wifi_to_ble_switch` |
| A crashed consumer task resets `_mdns_poller` so a subsequent `n` press rebuilds it | `test_tui_smoke.py::test_bonjour_consumer_task_resets_poller_on_unexpected_error` |

### `roam-detection`

| Requirement | Test |
|---|---|
| 0–100 link score with reasoned adjustments | `test_tui_helpers.py::test_link_score_rewards_stronger_cleaner_candidate` |
| Same-SSID better-candidate surfaces only when ≥+10 dB stronger | `test_tui_helpers.py::test_best_same_ssid_candidate_requires_meaningful_delta` |
| Surfaced candidate carries score + press-`c` hint | `test_tui_helpers.py::test_score_line_reports_better_same_ssid_candidate` |
| Press-`c` cycles Wi-Fi off/on | (manual — `force_reroam()` is backend-specific) |
| Vocabulary aligned between `_health_line` and `_link_score` | (review-enforced — convention; the bug it guards against landed once already) |

### `tui-shell`

| Requirement | Test |
|---|---|
| Four stacked panels in fixed order; third slot swaps wifi/ble/mdns | `test_tui_smoke.py::test_app_boots_and_quits` (App composes; panel presence implicit), `::test_view_toggle_cycles_wifi_ble_mdns_wifi` |
| Third-slot panel border_title carries an always-visible tab indicator listing all three views; detail content moves to border_subtitle | `test_tui_helpers.py::test_view_tabs_border_title_lists_all_three_views`, `::test_view_display_name_maps_internal_tokens_to_user_names`; `test_tui_smoke.py::test_panel_border_title_carries_tab_indicator` |
| Diagnostics content follows active view | `test_tui_smoke.py::test_toggle_view_swaps_third_panel`, `::test_view_toggle_cycles_wifi_ble_mdns_wifi`, `::test_diagnostics_renders_link_line_when_latency_data_available` |
| Modals push onto stack, Esc/letter closes | `test_tui_smoke.py::test_help_modal_open_and_close`, `::test_help_modal_h_to_close`, `::test_help_modal_renders_through_pilot_query`, `::test_events_modal_open_and_close`; `tui_snapshot.py::events_modal`, `::help_modal`, `::basics_modal`, `::ble_detail_decoded` (regression) |
| Footer is one GroupedFooter with three semantic groups | (gap — no footer-grouping unit test; visible in regression captures) |
| Hidden bindings exist for power-user navigation | `test_tui_smoke.py::test_pause_and_resume`, `::test_force_rescan_does_not_crash`, `::test_cycle_sort_modes` (binding firing); footer omission of hidden bindings is review-enforced |
| Header shows title + clock; subtitle reflects live state | (gap — no subtitle assertion in pytest; visible in regression captures) |
| App title pinned to `diting v<version>` (sourced from importlib.metadata) so the running version is always visible | `test_tui_smoke.py::test_app_title_carries_version` |
| Every list-style view panel shares the same row-select + inspect gesture (`up` / `down`, `i` / `enter`, mouse-click-to-inspect; modal close `Esc` / `i` / `q` does not mutate selection); deviations require modifying this Requirement | `test_tui_smoke.py::test_wifi_inspect_opens_modal_on_first_press`, `::test_bonjour_inspect_opens_modal_on_first_press` (alongside existing BLE coverage in `tui_snapshot.py::ble_detail_decoded`) |

### `wifi-detail-modal`

| Requirement | Test |
|---|---|
| Wi-Fi rows selectable by BSSID with `(ssid, channel)` fallback for redacted scans | `test_tui_smoke.py::test_wifi_selection_keyed_by_bssid_survives_resort`, `::test_wifi_selection_clears_when_target_drops_out`, `test_tui_helpers.py::test_scan_row_key_uses_bssid_when_available`, `::test_scan_row_key_falls_back_to_ssid_and_channel`, `::test_scan_row_key_handles_hidden_ssid` |
| Keyboard `up` / `down` / `enter` / `i` priority bindings (no-op outside Wi-Fi view) | `test_tui_smoke.py::test_wifi_inspect_opens_modal_on_first_press` |
| Mouse click → select-and-inspect | (manual; mouse path is the same `_wifi_set_selected(inspect=True)` entry as the keyboard `i`) |
| Modal renders every `ScanResult` field, grouped into Identity / Radio / Signal / Beacon IE / Activity | `test_tui_helpers.py::test_wifi_detail_renders_identity_radio_signal_activity_sections`, `::test_wifi_detail_renders_beacon_ie_when_present`, `::test_wifi_detail_omits_beacon_ie_when_all_fields_absent` |
| Signal history section renders the RSSI sparkline + σ baseline when EnvironmentMonitor has ≥2 samples for this BSSID; omitted otherwise | `test_tui_helpers.py::test_wifi_detail_signal_history_omitted_when_no_env_monitor`, `::test_wifi_detail_signal_history_omitted_when_under_two_samples`, `::test_wifi_detail_signal_history_renders_sparkline_and_sigma` |
| Same physical AP section lists sibling BSSIDs via `NetworkInventory.is_same_ap`; omitted when the AP is a singleton | `test_tui_helpers.py::test_wifi_detail_siblings_omitted_when_singleton`, `::test_wifi_detail_siblings_renders_when_inv_groups_radios` |
| Roam history section filters the event ring for this BSSID, newest-first, capped at 10; omitted when no matching events | `test_tui_helpers.py::test_wifi_detail_roam_history_omitted_when_ring_empty`, `::test_wifi_detail_roam_history_renders_matching_events_newest_first` |
| Recommendation section fires only when the inspected row is the currently-associated BSSID AND `_best_same_ssid_candidate` returns a stronger candidate | `test_tui_helpers.py::test_wifi_detail_recommendation_omitted_when_not_associated`, `::test_wifi_detail_recommendation_renders_for_associated_row_with_better_candidate`, `::test_wifi_detail_recommendation_omitted_when_no_clearly_better` |
| BSSID redaction surfaces a TCC hint rather than going silent | `test_tui_helpers.py::test_wifi_detail_redacted_bssid_renders_tcc_hint_and_omits_vendor` |
| AP-name pulled from `aps.yaml` only; absent when no entry matches | `test_tui_helpers.py::test_wifi_detail_renders_ap_name_when_inventory_matches`, `::test_wifi_detail_omits_ap_name_row_when_inventory_misses` |
| Modal close (Esc / `i` / `q`) doesn't mutate selection | (review-enforced; binding is declarative) |

### `wifi-scanning`

| Requirement | Test |
|---|---|
| Scan rows carry RSSI / channel / band / security / BSSID | `test_helper.py::test_scan_v2_returns_networks_and_iface_meta`, `::test_scan_lowercases_bssid`, `::test_scan_zero_noise_and_zero_rssi_become_none` |
| Redacted scans surface `(redacted)` placeholder, not silence | `tui_snapshot.py::wifi_redacted` (regression-only); `test_helper.py::test_scan_redacted_row_keeps_bssid_none` (data path) |
| Beacon IE keys optional and additive | `test_helper.py::test_scan_v2_keeps_ie_fields_none`, `::test_scan_v3_parses_bss_load_and_station_count`, `::test_scan_v3_parses_802_11r_capability_flag`, `::test_scan_v3_rejects_malformed_ie_values` |
| CoreWLAN throttle respected (≥7s cadence) | (gap — poller cadence is configured, not unit-tested) |
| Sentinel RSSI rows filtered before panel | `test_ble.py::test_rssi_unavailable_sentinel_filtered`, `::test_rssi_zero_or_positive_dbm_treated_as_invalid` (BLE side; `test_helper.py::test_scan_zero_noise_and_zero_rssi_become_none` Wi-Fi side) |
| Current BSSID merged into scan when CoreWLAN omits it | `test_tui_helpers.py::test_merge_current_prepends_when_scan_omits_associated_ap`, `::test_merge_current_replaces_when_scan_already_has_ap`, `::test_merge_current_no_op_when_disconnected`, `::test_merge_current_no_op_when_connection_has_no_bssid`, `::test_merge_current_case_insensitive_match` |

---

## 3. Module: `diting.network`

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

## 4. Module: `diting._helper`

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
- [x] `find_helper` search-order honouring of `DITING_HELPER`

### Test cases — `tests/test_helper.py`

| Test | Scenario | Why it matters |
|---|---|---|
| `test_scan_v2_returns_networks_and_iface_meta` | Schema v2 payload (interface dict with country / hardware) parses into ScanResult list and a non-empty meta dict. | Primary case for the current helper output. |
| `test_scan_v1_iface_string_yields_empty_meta` | Schema v1 payload (interface plain string) parses networks correctly; meta dict comes back empty rather than crashing. | Back-compat with helpers built before the v2 schema. Old `/Applications/diting-tianer.app` still works after `uv run diting` upgrades. |
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
| `test_find_helper_env_override_wins` | `DITING_HELPER` set to a bundle path beats any standard install location. | Documents the documented override priority. |
| `test_find_helper_env_override_can_point_at_binary` | The env var may also point directly at the executable rather than the bundle. | Dev-loop convenience. |
| `test_find_helper_returns_none_when_nothing_present` | Env var pointing at a missing path AND `HOME` redirected away → `None`. | Auto-launch then falls through to the build path. |

---

## 5. Module: `diting.tui` (helpers)

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

#### BLE diagnostics helpers

| Test | Scenario | Why it matters |
|---|---|---|
| `test_ble_visible_line_counts_total_connectable_anonymous` | The Visible BLE row reports total devices, connectable count, and anonymous count (no vendor + no name). | Drives the BLE diagnostics panel's first row. |
| `test_ble_vendors_line_top_four_plus_unknown` | The Vendors row shows the top four vendor names by headcount plus a `? N` tail for devices with no vendor. | Compresses a long tail without dropping unknown devices. |
| `test_ble_categories_line_groups_by_service_category` | Multi-service devices (e.g. Apple Watch on both HID and Heart Rate) count once per bucket; uncategorised devices roll into "N other". | Categories row must reflect the population without double-counting. |
| `test_ble_categories_line_includes_deep_id_types` | The Categories row counts schema-3 `type` (iBeacon, AirTag, …) and `device_class` (iPhone, …) alongside service-UUID categories. | iBeacon advertises no service UUIDs; without this the row would never reflect them. |
| `test_ble_closest_line_picks_strongest_rssi` | The Closest row labels the strongest-RSSI device with name + vendor. | Quickest answer to "what's right next to me". |
| `test_ble_closest_line_falls_back_to_anonymous_label` | When the strongest device has neither name nor vendor, the row still shows its RSSI with an `(anonymous)` label. | Honest about what we don't know, without dropping the row. |
| `test_ble_diagnostic_lines_returns_four_rows` | With no connected list the dispatcher returns 4 rows. | Layout invariant — panel min-height accounts for 4 rows; an accidental fifth pushes other content. |
| `test_ble_diagnostic_lines_adds_connected_row_when_present` | Supplying a non-empty `connected` arg appends a fifth row summarising connected peripherals. | The v0.6.0 spec's "fifth line appears only when connected peripherals exist" rule. |
| `test_ble_label_summary_prefers_type_over_service_category` | A device with `type="AirTag"` and service `FD5A` renders as `AirTag · Find My`. | The "what is this" label leads; the category gives extra context. |
| `test_ble_label_summary_falls_back_to_service_category_when_no_type` | No type / device_class → label is just the service-UUID category. | v0.5.0 behaviour preserved for non-Tier-1 devices. |
| `test_ble_label_summary_uses_device_class_when_no_type` | Apple Nearby Info gives `device_class` only; the summary surfaces `iPhone` / `Mac` / `Apple Watch`. | Replaces the v0.5.0 "Apple, Inc. (anonymous)" experience. |
| `test_ble_connected_line_counts_peripherals_and_categories` | The Connected diagnostics row counts total peripherals plus a per-category breakdown. | Drives the "Connected  3 peripherals · 2 Audio · 1 HID" rendering. |

---

## 5b. Module: `diting.ble`

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
| `test_detect_ibeacon_from_apple_manufacturer_payload` | An Apple manufacturer payload starting with `4c0002...` resolves to `type="iBeacon"` via `detect_advertisement`. | Tier-1 deep-ID for the most common BLE format. |
| `test_detect_airtag_apple_type_0x12_with_find_my_service` | Apple type `0x12` with an owner-paired length payload is labelled `AirTag`; Find My service confirms the category. | Replaces the v0.5.0 "Apple, Inc. (anonymous) Find My" wall with an actionable label. |
| `test_detect_find_my_target_short_payload` | A short Find My broadcast (lost-mode beacon) without the AirTag length signature degrades to `Find My target`. | Recognises the format but stays honest about subtype precision. |
| `test_detect_eddystone_url_from_helper_supplied_type` | A schema-3 JSON line with `type="Eddystone-URL"` propagates through `update_from_line` to `BLEDevice.type`. | Helper-side detection via service-data byte; Python side just propagates. |
| `test_detect_eddystone_generic_from_service_uuid_only` | Without a frame byte, `service_uuids=["FEAA"]` falls back to the generic `Eddystone` label. | Back-compat path; helpers post-0.6.0 specialise. |
| `test_detect_tile_from_feed_service_uuid` | Tile beacons advertising `FEED` or `FEEC` resolve to `type="Tile"`. | Tier-1 spec category. |
| `test_detect_smarttag_samsung_company_id_disambiguates_fd5a` | `FD5A` alone is ambiguous (Apple Find My vs Samsung SmartTag); the Samsung company ID `0x0075` flips the label. | Disambiguation rule the spec calls out specifically. |
| `test_detect_swift_pair_microsoft_company_id_plus_leading_byte` | Microsoft company ID `0x0006` + leading `0x03` → `Swift Pair`. | Tier-1 spec category. |
| `test_apple_nearby_info_device_class[iPhone,iPad,Mac,Apple TV,HomePod,Apple Watch]` (6 parametric rows) | Apple type `0x10` (Nearby Info) action-byte high-nibble maps to each of the six recognised device classes. | Reverse-engineered from `furiousMAC/continuity`; the deeper "what is this Apple device" answer. |
| `test_connected_line_routes_to_connected_dict_only` | A `{"connected": true, ...}` line goes to the connected dict and never to the advertising one. | Two-section panel cleanliness — cross-talk would corrupt the layout. |
| `test_connected_entries_skip_advertising_ttl` | `expire_devices` only sees the advertising dict; connected entries persist regardless of time. | Different lifecycles for different sources. |
| `test_connected_snapshot_sentinel_prunes_disappeared_entries` | `connected_snapshot` with a fresh `ids` list prunes entries no longer connected. | A peripheral the user just powered off must not linger in the panel. |
| `test_schema_2_json_back_compat_type_and_device_class_default_none` | A schema-2 JSON line (no `type` / `device_class`) parses cleanly with both fields defaulting to `None`. | Freshly-upgraded TUI keeps working until the user rebuilds the helper bundle. |
| `test_mixed_stream_routes_each_line_to_correct_bucket` | Interleaved advertising and connected lines route independently regardless of arrival order. | Routing correctness under realistic helper output cadence. |
| `test_ble_scan_update_propagates_connected_through_poller` | The poller's snapshot loop emits `BLEScanUpdate` whose `.connected` reflects the running connected dict. | Field the BLEPanel reads to render the Connected section. |

---

## 5c. Module: `diting.latency`

The latency probe poller. Tests cover ICMP output parsing, the
spike / loss-burst detectors, the rolling-window aggregate, and
seven distinct DNS auto-detection shapes captured from real
networks (home / corporate / Cloudflare DoH / multi-resolver /
no-DNS / empty list / malformed). All subprocess calls and
SCDynamicStore reads are mocked at the module seam.

**Coverage targets:**

- [x] `_parse_ping_time_ms` decimal / integer / `time<1.0` /
      missing
- [x] `LatencyPoller._ping_once` records rtt on success
- [x] `_ping_once` lost on non-zero exit / no `time=` / subprocess
      error
- [x] `aggregate` median / loss% / MAD jitter
- [x] `aggregate` empty window returns None fields
- [x] `detect_latency_spike` requires both thresholds (200 ms AND
      5× median)
- [x] `detect_loss_burst` 3-of-5 rule
- [x] `LatencyPoller.stop`
- [x] DNS auto-detection: typical home (DNS == gateway → None)
- [x] DNS auto-detection: corporate internal resolver
- [x] DNS auto-detection: Cloudflare DoH
- [x] DNS auto-detection: multi-resolver, gateway listed first
- [x] DNS auto-detection: SCDynamicStore returns None
- [x] DNS auto-detection: empty ServerAddresses
- [x] DNS auto-detection: malformed (None / int / object) entries
- [x] `DITING_LATENCY_WAN_TARGET` env override beats
      auto-detect
- [x] DNS refresh cadence (clock-injected, no real time)
- [x] Explicit `wan_ip=` disables refresh entirely
- [x] `wan_skipped_reason` distinguishes `no_dns` vs
      `dns_eq_gateway`
- [x] `_scutil_dns_fallback` parses resolver-#1 nameservers,
      stops at #2

### Test cases — `tests/test_latency.py`

27 cases, one per row above. See module docstrings for the live
text per case.

---

## 5d. Module: `diting.environment`

The RF-stir detector. Tests build deterministic RSSI traces with
explicit timestamps so the rolling-window math is exact.

**Coverage targets:**

- [x] σ above threshold fires `RFStirEvent`
- [x] σ below threshold stays quiet
- [x] Mode auto-classification (co_located / spatial_channel /
      ignored)
- [x] Redundancy fusion: 2 co-located APs spike → high
      confidence
- [x] Single co-located AP spike → medium confidence
- [x] Spatial-channel event labelled with the AP's inventory name
- [x] Calibration baseline overrides adaptive
- [x] `baseline_summary()` shape
- [x] APs below -85 dBm excluded from σ calculation
- [x] `aggregate_sigma` label `active` / `quiet` / `stable`
- [x] `write_calibration` / `load_calibration` round trip
- [x] `load_calibration` returns `{}` for missing file

### Test cases — `tests/test_environment.py`

13 cases, one per row above.

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
| `test_custom_scan_interval_threads_through` | Construct `DitingApp(..., scan_interval=4.5)` and inspect `app._poller._scan_interval`. | The `DITING_SCAN_INTERVAL` env var lands here; if the kwarg path silently lost it, we'd never know. |
| `test_toggle_view_swaps_third_panel` | Press `n` to toggle from the Wi-Fi scan view to the BLE view; press again to return. Asserts on the `display` flag of both panels and on `app._view_mode`. | Locks the spec's "toggle in place" behaviour — neither panel ever unmounts, so consumer state on either side survives the swap. |
| `test_ble_panel_renders_both_connected_and_advertising_sections` | Seed both `_latest_ble` (advertising) and `_latest_ble_connected` (connected), press `n`, and assert the BLEPanel body contains both `Connected (1)` and `Advertising (1)` section headers plus a row from each. | End-to-end proof of the v0.6.0 two-section render through the Textual pilot — rendering bug here breaks the spec's question-2 ("what's actually connected to my Mac?") answer. |
| `test_events_modal_open_and_close` | Press `m` to open EventsScreen, press Esc to close. | Locks the v0.7.0 modal binding the same way `test_help_modal_open_and_close` locks the help binding. |
| `test_diagnostics_renders_link_line_when_latency_data_available` | Construct latency aggregates + an environment tuple, call `panel.update_environment(..., link=, env=)`, and confirm the rendered body contains `Link`, `gw 14 ms`, `Environment`, and `stable`. | The Diagnostics panel must accept the new tuples without dropping them on the floor — guards the v0.7.0 contract between the consumer and the renderer. |
| `test_unified_events_panel_renders_roam_and_stir_interleaved` | Push a `RoamEvent` and an `RFStirEvent` into the unified panel; assert both `[ROAM]` and `[STIR]` prefixes plus the location label appear in the rendered output. | The Roam log → Events panel rename is allowed only because both event types render correctly through the same widget. |

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

The workflow when iterating diting:

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
