<sub>[English](../../tests/TESTING.md) · **中文**</sub>

# 测试设计

本文档是 diting 的 **canonical 测试计划**，与测试代码一起放在
`tests/` 目录。它描述测什么、为什么测，以及作为自动化用例的具体场景。
该目录的测试**必须与本文档保持一致** —— 调整 / 新增场景请先改这份
文档，再翻译成 Python 代码。

评审 PR 时请先读它；代码应当与文档一一对应。

---

## 1. 范围

### 在范围内

- **决定 diting 显示什么的纯逻辑变换**：AP 解析、信号频段标签、
  扫描 / 连接合并、按 AP 分组聚簇。
- **外部协议解析**：辅助子进程的 JSON（schema v1 与 v2）、清单 YAML
  加载。
- **TUI 冒烟**：App 能 mount，每个绑定都能触发不报错，help 模态能
  打开和关闭。

### 不在范围内

- **真实 CoreWLAN / SCDynamicStore 调用**。结果取决于测试瞬间是否
  存在 Wi-Fi 关联，既不确定也无法在 CI runner 上跑。SCDynamicStore
  的 bplist 解析也不在范围内 —— 没有合适办法在不快照原始字节的前提下
  造一个具有代表性的 fixture。
- **Swift 辅助二进制本身**。开发期手工测；Python 这一侧在
  `subprocess.run` 边界 mock。
- **视觉渲染**（颜色、信号条宽度、对齐）。冒烟测试证明 App 能 compose；
  像素级截图脆弱，性价比不高。
- **性能**。轮询与渲染受 helper 子进程 I/O 主导；偶尔肉眼观察，不做
  benchmark。

---

## 2. 分层

| 层 | 位置 | 证明的事 |
|---|---|---|
| 单元 | `tests/test_*.py`（除 tui_smoke） | 每个纯函数在其全部输入空间内表现符合规约，包括来自真实 bug 的回归用例。 |
| 冒烟 | `tests/test_tui_smoke.py` | Textual App 能被 compose、mount、走完每个绑定、unmount，全程不抛异常。使用一个返回确定数据的 `_FakeBackend`。 |
| 快照回归 | `scripts/tui_snapshot.py --mode regression` | 11 个场景在固定合成输入下渲染 TUI；断言验证面板内容、模态布局、解码输出。CI 失败时上传 `snapshot-output/`。 |

---

## 2.5. Spec 覆盖矩阵

`openspec/specs/<name>/spec.md` 里每条 Requirement，本表都指出对应的
测试。标 **(review-enforced)** 表示是约定，违反需要 reviewer 拦，没
办法做单元测试；标 **(regression-only)** 表示通过
`scripts/tui_snapshot.py --mode regression` 而不是 pytest 直接验证。
**(gap)** 标的是当前没有自动化覆盖，需要在路线图里补。

任何 spec 加新 Requirement 时，本表必须同步加一行（并补对应测试，
除非 review-enforced）。

### `analyze`

| Requirement | 测试 |
|---|---|
| 纯规则、不联网 | (review-enforced — 代码不 import 任何网络库) |
| 报告以 span / 计数 / 关联时间线开头 | `test_analyze.py::test_render_includes_path_and_event_counts`、`::test_analyze_records_associations_and_roams` |
| Insights 由命名启发式产出，触发条件显式 | `test_analyze.py::test_repeated_disassociates_warns`、`::test_loss_burst_present_warns_real_loss`、`::test_short_session_triggers_low_data_hint`、`::test_timezone_mismatch_heuristic_triggers_on_hour_jump`、`::test_single_ap_medium_only_triggers_redundancy_hint`、`::test_latency_without_loss_triggers_jitter_hint` |
| 丢包率自动识别 0..1 分数 vs 0..100 百分比 | `test_analyze.py::test_loss_burst_present_warns_real_loss`（覆盖 scaled-loss 路径） |
| 时长格式诚实（`30s`，永远不写 `1 min`） | `test_tui_helpers.py::test_format_duration_short_buckets`、`::test_format_duration_short_negative_clamps_to_zero` |
| 有 insight 时才出 TODO 段 | `test_analyze.py::test_render_handles_zero_events`、`::test_empty_log_warns` |
| 多文件 glob 输入 — 多个 JSONL 合并为单个按时间戳排序的事件流 | `test_analyze.py::test_glob_expansion_via_multiple_paths_aggregates_into_single_report`、`test_cli.py::test_analyze_multi_path_args_thread_through` |
| `--since DURATION` 解析 `<int><unit>` 形式并过滤最近 DURATION 内的事件 | `test_analyze.py::test_since_filter_parses_30d_24h_15m_etc`、`::test_since_filter_rejects_invalid_format`、`test_cli.py::test_analyze_since_flag_threads_through` |
| `Scope` 头行：文件数 + 观察跨度 + 当前 `--since` | `test_analyze.py::test_scope_header_renders_single_file_no_since`、`::test_scope_header_renders_multi_file_with_since` |
| `aggregate_hour_of_day` — 24 桶 + 每桶事件类型 Counter | `test_analyze.py::test_aggregate_hour_of_day_buckets_events_into_24_slots`、`::test_aggregate_hour_of_day_carries_type_breakdown` |
| `aggregate_day_of_week_x_hour` — 7×24 整数网格；渲染用 `▁▂▃▄▅▆▇█` 密度块 | `test_analyze.py::test_aggregate_day_of_week_x_hour_returns_7x24_grid`、`::test_render_day_x_hour_heatmap_normalises_to_block_chars` |
| `aggregate_per_network` — 通过 connection_update 历史走查归到关联 BSSID；找不到归 `(unknown network)` | `test_analyze.py::test_aggregate_per_network_groups_by_associated_bssid`、`::test_aggregate_per_network_attributes_orphan_events_to_unknown` |
| `aggregate_daily_trend` — 每日总数 + 7 天滚动均值；按事件家族出 sparkline | `test_analyze.py::test_aggregate_daily_trend_yields_per_day_counts`、`::test_aggregate_daily_trend_includes_rolling_avg`、`::test_render_daily_trend_emits_one_sparkline_per_family` |
| `aggregate_top_contributors` — 三套子排行（BSSID / BLE / LAN）按各自信号计数 | `test_analyze.py::test_top_contributors_ranks_bssids_by_roam_plus_stir`、`::test_top_contributors_ranks_ble_identifiers_by_seen_count`、`::test_top_contributors_ranks_lan_hosts_by_dhcp_rotation_count` |
| 跨会话块「只追加」— 单文件无 `--since` 时旧布局原样保留 | `test_analyze.py::test_single_file_no_since_preserves_existing_layout`、`::test_multi_file_or_since_appends_cross_session_blocks` |
| `--for-llm [outdir]` 写 `report.md` + `prompt.txt` 包；默认 outdir 是 `./diting-llm-<timestamp>/`（相对当前目录 —— 测试传显式 tmp_path 或先 chdir 到 tmp_path，绝不写进仓库树） | `test_analyze.py::test_for_llm_writes_report_markdown`、`::test_for_llm_writes_prompt_txt`、`::test_for_llm_default_outdir_is_cwd_relative_not_repo` |
| 报告 Markdown 含 Glossary；ASCII 图在 ` ```text ` 围栏块里；排行数据为 Markdown 表 | `test_analyze.py::test_render_markdown_includes_glossary`、`::test_render_markdown_wraps_ascii_in_fenced_blocks`、`::test_render_markdown_renders_per_network_as_table` |
| Prompt 模板含 role + 任务 + 输出格式 + 「不要超出数据推断」护栏 + 匿名感知条款 | `test_analyze.py::test_build_llm_prompt_includes_all_five_sections`、`::test_build_llm_prompt_substitutes_span_and_files` |
| `--anonymize` 用首见顺序的稳定句柄替换 SSID / BSSID / RFC1918 IP / 主机名 / BLE 标识 / MAC | `test_analyze.py::test_anonymizer_assigns_stable_handles`、`::test_anonymizer_same_value_returns_same_handle`、`::test_for_llm_with_anonymize_replaces_identifiers` |
| 公网 IP（8.8.8.8、1.1.1.1）原样保留；厂商 + 类别名不变 | `test_analyze.py::test_anonymizer_preserves_public_ip_addresses`、`::test_anonymizer_passes_through_vendor_names` |
| 匿名映射只打到终端 stdout；report.md 里是占位说明，不含映射 | `test_analyze.py::test_render_markdown_anonymization_section_is_placeholder`、`test_cli.py::test_analyze_anonymize_prints_mapping_to_stdout` |
| 终端引导文案含 4 步粘贴流程；未开 `--anonymize` 时多一行提示 | `test_cli.py::test_analyze_for_llm_prints_four_step_guidance`、`::test_analyze_for_llm_nudges_anonymize_when_off` |
| `session_meta` 消费：Markdown 报告头显示 scene + scene_source；多会话混合时聚合；缺失 session_meta 时降级为 `unknown`；同场景多源时优先级 cli > env > default | `test_analyze.py::test_analyze_collects_scene_from_session_meta`、`::test_analyze_multi_scene_mix_recorded_in_order_seen`、`::test_analyze_missing_session_meta_leaves_scenes_empty`、`::test_scene_summary_single_scene_names_source`、`::test_scene_summary_source_promotion_uses_strongest`、`::test_render_markdown_includes_scene_line`、`::test_render_markdown_pre_scene_aware_shows_unknown` |
| `--for-llm` 把 `[Scene context]` 段落注入 prompt 开头；回填观察到的 BSSID + BLE 数量；多场景 bundle 要求 LLM 跨场景对比；不带 session_meta 的日志退回到通用 prior | `test_analyze.py::test_build_llm_prompt_starts_with_scene_context`、`::test_build_llm_prompt_includes_observed_counts_when_available`、`::test_build_llm_prompt_multi_scene_acknowledges_mix`、`::test_build_llm_prompt_pre_scene_aware_falls_back_to_general_priors` |

### `anomaly-watchdog`

| Requirement | 测试 |
|---|---|
| `--notify` 对 `rf_stir` / `latency_spike` / `loss_burst` 三种异常都触发 macOS 通知中心横幅（`monitor` 与默认 TUI 子命令均生效） | `test_watchdog.py::test_maybe_notify_fires_for_latency_spike`、`::test_maybe_notify_fires_for_loss_burst`、`::test_maybe_notify_fires_for_rf_stir_high_confidence`、`::test_maybe_notify_silent_when_notify_disabled`（调用方早返）；TUI wire-up：`test_tui_smoke.py::test_app_with_notify_calls_watchdog_on_event` |
| `rf_stir` 通知按 `DITING_NOTIFY_STIR_CONFIDENCE` 阈值（默认 `high`，可选 `medium` / `all`）过滤 | `test_watchdog.py::test_should_notify_stir_default_gate`、`::test_should_notify_stir_medium_gate`、`::test_should_notify_stir_all_gate`、`::test_watchdog_config_falls_back_on_invalid_stir_gate` |
| 按 (event-type, target) 维度的静默窗口（默认 60 s，`DITING_NOTIFY_SILENCE_S` 可覆盖） | `test_watchdog.py::test_silence_clock_first_fire_returns_true`、`::test_silence_clock_second_fire_within_window_returns_false`、`::test_silence_clock_second_fire_after_window_returns_true`、`::test_silence_clock_independent_per_tuple`、`::test_watchdog_config_defaults_when_env_unset`、`::test_watchdog_config_parses_valid_env`、`::test_watchdog_config_falls_back_on_invalid_silence` |
| 通知通过 helper bundle 的 `notify` 子命令派发（图标 = diting logo）；helper 不存在则静默跳过（不再 fallback 到 osascript） | `test_watchdog.py::test_macos_notify_invokes_helper_notify_subcommand`、`::test_macos_notify_silent_when_helper_absent` |
| **add-insight-events** —— `--notify` 为 `note`/`warn` 的 `insight` 弹通知（正文 = 合成的一行摘要）；`info` 不通知；静默窗口按 insight `code` 计键，使不同 insight 各自去抖 | `test_watchdog.py::test_maybe_notify_fires_for_warn_insight`、`::test_maybe_notify_skips_info_insight`、`::test_insight_silence_window_keyed_per_code` |

### `ble-decoders`

| Requirement | 测试 |
|---|---|
| Decoder 是 `@register` 装饰过的函数 | `test_decoders.py::test_registry_has_built_in_decoders` |
| Decoder 永不在格式不对时抛 | `test_decoders.py::test_decode_all_swallows_decoder_exceptions`；每个协议另有 `test_*_skips_truncated_*`、`test_*_skips_when_too_short` |
| 输出键带协议命名空间前缀 | (review-enforced — 代码 review 时确认；canonical-decode 测试断言带前缀的键) |
| 内置 decoder 覆盖公开 spec 协议 | iBeacon: `test_ibeacon_canonical_decode`；Eddystone: `test_eddystone_url_canonical_decode`、`::test_eddystone_uid_decode`、`::test_eddystone_tlm_decode`、`::test_eddystone_eid_frame_recognised_but_not_decoded`；Apple Continuity: `test_nearby_info_canonical_short_form`、`::test_find_my_short_form_minimum_payload`、`::test_handoff_canonical_decode`、`::test_handoff_chained_with_nearby_info_decodes_both`；MS CDP: `test_ms_device_beacon_real_capture`、`::test_swift_pair_decodes_utf8_model_name`；Ruuvi: `test_ruuvi_format5_canonical_decode`；小米 / 华米: `test_xiaomi_canonical_decode_with_body`、`::test_xiaomi_short_frame_decodes_just_frame_byte`、`::test_xiaomi_skips_non_xiaomi_cid` |
| 不为含义未稳定的 bit 编造语义 | (review-enforced — 内置 decoder 都只暴露 byte hex) |
| Decoder 用识别字节做 gate | `test_decoders.py::test_ibeacon_skips_non_apple_cid`、`::test_nearby_info_skips_non_apple_cid`、`::test_eddystone_skips_non_feaa_service_data`、`::test_ms_device_beacon_skips_when_subtype_is_swift_pair`、`::test_ruuvi_skips_non_ruuvi_cid` |
| 通用 `manufacturer` 识别器为长尾厂商呈现 cid/厂商/body；跳过已有专用 decoder 的 cid；缺失/过短时弃权；不编造 device_type | `test_decoders.py::test_manufacturer_generic_surfaces_cid_and_body`、`::test_manufacturer_generic_surfaces_vendor_name_when_known`、`::test_manufacturer_generic_skips_dedicated_cids`、`::test_manufacturer_generic_abstains_without_or_on_short_mfg` |

### `ble-detail-modal`

| Requirement | 测试 |
|---|---|
| 行选择按 identifier、跨 snapshot 稳定 | `tui_snapshot.py::ble_detail_decoded`（regression-only） |
| 键盘 `up` / `down` / `enter` / `i` 优先级绑定 | `tui_snapshot.py::ble_detail_decoded` 用 `down` × N + `i` 走光标（regression-only） |
| 鼠标单击 → 选中并 inspect | (gap — 人工 / 后续回归) |
| Modal 渲染所有 BLEDevice 字段 + 解码后 payload | `tui_snapshot.py::ble_detail_decoded` 断言 `Decoded section header`、`iBeacon UUID rendered`、`iBeacon major+minor`（regression-only） |
| Activity 段对已连接外设隐藏 ad_count | (review-enforced；在 `live_ble_detail` 真机捕获里可见) |
| ≥ 2 历史样本时显示 RSSI sparkline | `test_tui_helpers.py::test_rssi_sparkline_empty_history_returns_empty`、`::test_rssi_sparkline_single_sample_returns_empty`、`::test_rssi_sparkline_constant_rssi_renders_flat_line`、`::test_rssi_sparkline_maps_extremes_to_top_and_bottom_blocks`、`::test_rssi_sparkline_renders_one_char_per_sample`（渲染）；`test_ble.py::test_history_records_and_returns_samples_in_order`（数据通路） |
| Esc / `i` / `q` 关闭 modal 不动选择 | (人工；模态 binding 是声明式的) |
| 距离估算标 "rough free-space" | `test_tui_helpers.py::test_free_space_distance_m_at_one_meter_returns_one`、`::test_free_space_distance_m_doubles_at_minus_six_db`、`::test_free_space_distance_m_zero_rssi_returns_none` |
| Services / Extra UUID lists 空状态以独立的 dim-italic 占位行渲染（不走 `_label`，避免拖一个 em-dash 尾巴） | `test_tui_helpers.py::test_ble_detail_services_empty_state_has_no_trailing_emdash`、`::test_ble_detail_extra_uuids_empty_state_has_no_trailing_emdash` |

### `bonjour-detail-modal`

| Requirement | 测试 |
|---|---|
| Bonjour 行按 service-instance FQDN 选中，re-sort + churn 不丢 | `test_tui_smoke.py::test_bonjour_selection_keyed_by_fqdn_survives_resort`、`::test_bonjour_selection_clears_when_target_drops_out` |
| 键盘 `up` / `down` / `enter` / `i` priority binding（Bonjour 视图外 no-op） | `test_tui_smoke.py::test_bonjour_inspect_opens_modal_on_first_press` |
| 鼠标点击 → 一手选中+打开 modal | （人工；鼠标路径与键盘 `i` 共用 `_bonjour_set_selected(inspect=True)` 入口） |
| Modal 渲染每个 `BonjourDevice` 字段，过长 TXT 值做折叠 | `test_tui_helpers.py::test_bonjour_detail_renders_identity_network_txt_activity_sections`、`::test_bonjour_detail_folds_long_txt_values`、`::test_bonjour_detail_omits_txt_section_when_empty` |
| 服务类别走 i18n 翻译 | `test_tui_helpers.py::test_bonjour_detail_renders_translated_category_when_known`、`::test_bonjour_detail_omits_category_row_when_unknown` |
| Identity 段在 `BonjourDevice.vendor_trace` 有值时为 vendor 行追加 ` · via <trace>` 注解 | `test_tui_helpers.py::test_bonjour_detail_vendor_trace_annotation_appears_when_set`、`::test_bonjour_detail_vendor_trace_omitted_when_none` |
| Other services on this host 段列出同 host（或匿名 host 时通过 addresses 重叠）的其他 `BonjourDevice`；只有自身一个服务时省略 | `test_tui_helpers.py::test_bonjour_detail_other_services_omitted_when_lone_host`、`::test_bonjour_detail_other_services_lists_same_host_categories`、`::test_bonjour_detail_other_services_falls_back_to_addresses` |
| TXT records 段先渲染 Decoded（注册到 `mdns_txt_decoders` 的已知键），再渲染 Raw；Decoded 命中的键不出现在 Raw 表里 | `test_tui_helpers.py::test_bonjour_detail_decoded_txt_appears_for_known_keys`、`::test_bonjour_detail_decoded_txt_skipped_when_no_known_keys`；decoder 单测见 `test_mdns_txt_decoders.py` |
| Cross-surface 段把 Bonjour host 关联到 Wi-Fi peer（规则 1：IP 命中 → "local Mac"）、关联到 BLE peripheral（规则 2：TXT deviceid MAC 在 `manufacturer_hex` 中作为字节出现）、以及通过 hostname 模式关联到附近的 Apple-Proximity BLE 设备（规则 3，"likely" 修饰）；三条规则都不匹配时整段省略 | `test_tui_helpers.py::test_bonjour_cross_surface_omitted_when_no_refs`、`::test_bonjour_cross_surface_local_mac_when_ip_matches`、`::test_bonjour_cross_surface_local_mac_omitted_when_ips_disagree`、`::test_bonjour_cross_surface_ble_via_deviceid_finds_mac_in_manufacturer_hex`、`::test_bonjour_cross_surface_ble_via_deviceid_omitted_when_no_match`、`::test_bonjour_cross_surface_ble_via_hostname_pattern_hedges_likely`、`::test_bonjour_cross_surface_ble_via_hostname_skipped_for_non_apple_host` |
| Esc / `i` / `q` 关闭 modal 不动选择 | （review-enforced；binding 是声明式的） |

### `bluetooth-scanning`

| Requirement | 测试 |
|---|---|
| 每行 helper JSONL → 一个 BLEDevice | `test_ble.py::test_parse_advertisement_populates_all_fields`、`::test_parse_subsequent_advertisement_carries_history`、`::test_line_without_id_field_skipped` |
| Vendor 解析：5 步确定性链 | `test_ble.py::test_vendor_fallback_via_member_uuid_when_manufacturer_id_absent`、`::test_manufacturer_id_takes_priority_over_member_uuid_vendor`、`::test_service_data_uuid_resolves_vendor_when_service_uuids_empty`、`::test_advertising_vendor_falls_back_to_name_pattern`、`::test_vendor_id_carries_forward_when_scan_response_omits_manufacturer_data` |
| 已连接外设走独立代码路径 | `test_ble.py::test_connected_line_routes_to_connected_dict_only`、`::test_connected_entries_skip_advertising_ttl`、`::test_connected_snapshot_sentinel_prunes_disappeared_entries` |
| 轮换标识合并 | `test_ble.py::test_merge_folds_same_vendor_and_name_within_rssi_window`、`::test_merge_keeps_distant_rssi_separate`、`::test_merge_sorts_by_rssi_descending` |
| `(anonymous)` 与 `(unknown)` 区分 | `test_ble.py::test_merge_does_not_combine_anonymous_devices`（数据通路）；`tui_snapshot.py::ble_normal`（渲染） |
| RSSI 平滑保稳定排序 | `test_ble.py::test_rssi_smooth_seeds_from_first_sample`、`::test_rssi_smooth_dampens_packet_jitter`、`::test_merge_sort_key_uses_smoothed_rssi` |
| Schema-4 raw 字段透传到 BLEDevice | `test_ble.py::test_schema_4_raw_passthrough_fields_populate`、`::test_schema_4_fields_default_when_helper_omits`、`::test_schema_4_fields_carry_forward_on_scan_response` |
| BLE history 限长 + 剪枝 | `test_ble.py::test_history_records_and_returns_samples_in_order`、`::test_history_drops_none_rssi`、`::test_history_caps_at_maxlen`、`::test_history_get_unknown_device_returns_empty`、`::test_history_expire_drops_devices_not_in_set` |
| Categories 诊断行排除协议工具类 GATT 服务 | `test_ble.py::test_service_category_category_only_excludes_protocol_services` |
| Vendors 诊断行标注 RPA 轮换折叠数 | `test_tui_helpers.py::test_ble_vendors_line_annotates_folded_rotation_count`、`::test_ble_vendors_line_skips_annotation_when_nothing_folded` |
| BLE 行 Name 列在 helper 没给名字时依次回落到 `type` / `device_class`，最后才显示 `(未知)`；Services 列只保留 service-category（不再重复展示 `type` / `device_class`） | `test_tui_helpers.py::test_ble_row_line_name_uses_helper_name_when_present`、`::test_ble_row_line_name_falls_back_to_type`、`::test_ble_row_line_name_falls_back_to_device_class`、`::test_ble_row_line_name_unknown_when_no_signal`、`::test_ble_label_summary_services_only` |
| `BLEPoller` 在 identifier graduate 到 PRESENT 时发 `BLEDeviceSeenEvent`（带 name 的广播和已连接外设不走 gate；匿名广播必须被持续观察至少 `presence_gate_s` 秒，默认 5s）；只有 graduate 过的 identifier 在 TTL 失效时才发 `BLEDeviceLeftEvent`；`presence_gate_s=0` 恢复「不防抖」契约；identifier 发完 left 之后再次 flap 进 `_devices` 又被 TTL 清掉，本会话内不再发任何事件 | `test_ble.py::test_poller_emits_seen_event_on_first_observation`、`::test_poller_does_not_re_emit_seen_for_known_identifier`、`::test_poller_emits_left_event_on_ttl_eviction`、`::test_poller_connected_peripheral_does_not_re_emit_seen`、`::test_poller_does_not_re_emit_left_after_identifier_returns_and_evicts_again`、`::test_poller_anonymous_advert_below_gate_emits_no_seen_no_left`、`::test_poller_anonymous_advert_graduates_after_gate_elapses`、`::test_poller_named_first_advert_bypasses_gate`、`::test_poller_connected_peripheral_bypasses_gate`、`::test_poller_presence_gate_zero_restores_no_debounce`、`::test_poller_pending_identifier_graduates_when_name_appears_in_later_advert` |
| **v1.8.0** —— `BLEPoller` 对隐私轮换 identifier 做聚类（指纹与 `merge_for_display` 完全一致：`(vendor_id, name)` 精确匹配 + RSSI ±10 dB 容差 + 服务 UUID Jaccard ≥ 0.5；`(vendor_id=None 且 name=None)` 不参与聚类）。每个 cluster 首个 identifier graduate 时发一次 `BLEDeviceSeenEvent`，只有所有成员都 TTL 失效后才发一次 `BLEDeviceLeftEvent`。代表 identifier = 第一个 graduate 的。部分成员离开静默。`DITING_BLE_EVENT_MERGER=0`（或 `BLEPoller(enable_cluster_merger=False)`）恢复 per-identifier 语义。`merge_for_display` 和 cluster index 共享模块级 `_RSSI_WINDOW_DB` / `_JACCARD_THRESHOLD` 常量 | `test_ble.py::test_cluster_one_iphone_rotating_four_identifiers_fires_one_seen_one_left`、`::test_cluster_two_devices_at_different_rssi_buckets_fire_separately`、`::test_cluster_presence_gate_failing_flit_does_not_claim_cluster`、`::test_cluster_disabled_via_env_restores_per_identifier_semantics`、`::test_cluster_partial_departure_silent`、`::test_cluster_lifetime_ends_then_device_returns_fires_fresh_seen`、`::test_cluster_fully_anonymous_devices_each_get_own_cluster`、`::test_cluster_fingerprint_constants_shared_with_merge_for_display`、`::test_cluster_representative_id_survives_when_first_member_evicts` |
| **v1.11.x 载荷融合** —— 转移事件合并器在 RSSI 之外新增强路径：非平凡的厂商载荷与某 cluster 锚点完全相同的 identifier 直接并入该 cluster（隐私轮换设备在 MAC 轮换中保持载荷不变），先于 RSSI 启发式尝试。排除 Apple（0x004C，其 Continuity 状态载荷是多设备共享的通用值）；跳过仅有 header 的载荷（`< _PAYLOAD_FUSE_MIN_HEXLEN`）；以并发活跃成员上限（`_PAYLOAD_FUSE_MAX_ACTIVE`）作为过度合并的兜底 | `test_ble.py::test_payload_fuses_identical_payload_ignores_rssi`、`::test_payload_fuses_different_payload_does_not_fuse`、`::test_payload_fuses_excludes_apple`、`::test_payload_fuses_respects_active_member_cap`、`::test_payload_fuses_skips_trivial_payload`、`::test_assign_to_cluster_fuses_rotation_by_payload_across_rssi_gap` |
| **events-cascade-census-fold** —— `BLEPoller` 把 cluster 代表的 `device_type` / `device_class` 复制到每个 `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent`；在 poller 构造后 `_LAUNCH_WARMUP_S`（12.0s）窗口内 graduate 的广播设备 seen 带 `at_launch=True`，窗口外的 seen 带 `at_launch=False`，已连接外设的 seen 永远 `at_launch=False` | `test_ble.py::test_poller_seen_carries_device_type_and_class_from_representative`、`::test_poller_left_carries_device_type_and_class`、`::test_poller_seen_at_launch_true_inside_warmup_window`、`::test_poller_seen_at_launch_false_after_warmup_window`、`::test_poller_connected_peripheral_seen_never_at_launch` |
| `--ble-presence-gate D` CLI flag + `DITING_BLE_PRESENCE_GATE` 环境变量控制 `presence_gate_s`；CLI 优先于 env；空 env 回退到默认 5s；非法 env 警告后回退；`0` 是 `0s` 的快捷写法 | `test_cli.py::test_extract_ble_presence_gate_arg_parses_seconds_form`、`::test_extract_ble_presence_gate_arg_parses_equals_form`、`::test_extract_ble_presence_gate_arg_accepts_zero_shortcut`、`::test_extract_ble_presence_gate_arg_absent_returns_none`、`::test_extract_ble_presence_gate_arg_invalid_unit_exits`、`::test_resolve_ble_presence_gate_cli_wins`、`::test_resolve_ble_presence_gate_env_fallback`、`::test_resolve_ble_presence_gate_default_5s`、`::test_resolve_ble_presence_gate_blank_env_is_default`、`::test_resolve_ble_presence_gate_invalid_env_warns_and_defaults` |
| **v1.7.2** —— 轮换标识 name 守卫：BLE 行渲染器对所有匹配 `^[A-Za-z0-9+/=_-]{16,}$`（无空白字符、不以 `iPhone` / `iPad` / `Mac` / `AirPods` / `HomePod` / `Apple TV` / `Apple Watch` / `Beats` 开头）的 `BLEDevice.name` 替换为 `(rotating ID)`（英）/ `(临时标识)`（中）；BLE 详情弹窗在 name 非空时新增 `Raw name:` / `原始名称:` 一行保留原始字符串 | `test_tui_helpers.py::test_ble_looks_like_rotating_id_predicate_true_on_apple_continuity_shape`、`::test_ble_looks_like_rotating_id_predicate_true_on_huami_serial`、`::test_ble_looks_like_rotating_id_predicate_false_on_iphone_prefix`、`::test_ble_looks_like_rotating_id_predicate_false_on_whitespace_name`、`::test_ble_looks_like_rotating_id_predicate_false_on_short_name`、`::test_ble_looks_like_rotating_id_predicate_false_on_none`、`::test_ble_row_name_substitutes_rotating_id_placeholder`、`::test_ble_row_name_preserves_real_apple_device_name`、`::test_ble_detail_renders_raw_name_row_when_rotating_id`、`::test_ble_detail_omits_raw_name_row_when_name_none` |

### `companion-protocol`

桌面→移动端配对的权威线上契约。golden fixture 由真实的 `EventLogger`
生成，因此协议 payload 不会与桌面已写出的 JSONL 悄悄分叉。

| Requirement | 测试 |
|---|---|
| golden fixture + JSON Schema 可复现 —— 重新生成得到逐字节一致的已提交产物（不允许手改导致与写入器脱节） | `test_companion_protocol.py::test_committed_artifacts_match_generator`、`::test_event_schema_on_disk_matches_builder` |
| 漂移检查：每个 vendored 产物的 sha256 与 `manifest.json` 一致 | `test_companion_protocol.py::test_manifest_hashes_match_files` |
| fixture 覆盖每种线上事件类型；JSON Schema 每类型一个分支 | `test_companion_protocol.py::test_fixtures_cover_every_event_type`、`::test_json_schema_has_one_branch_per_type` |
| 事件 payload 复用已钉死的 JSONL 形状 —— 每行 fixture 都校验通过 | `test_companion_protocol.py::test_every_fixture_line_validates` |
| `validate_event` 对未知 type / 缺必填 / 多余字段 / 非法枚举 / 非法时间戳 / 非对象 全部 fail-closed | `test_companion_protocol.py::test_validate_rejects_unknown_type`、`::test_validate_rejects_missing_required`、`::test_validate_rejects_unknown_field`、`::test_validate_rejects_bad_enum`、`::test_validate_rejects_bad_timestamp`、`::test_validate_rejects_non_object` |
| 仅容忍受支持的版本；bool / str / 未知大版本一律拒绝 | `test_companion_protocol.py::test_supported_version` |
| 配对 payload 往返（URI ↔ 对象，32 字节密钥）；已提交 fixture 可解码；畸形 payload 抛错 | `test_companion_protocol.py::test_pairing_round_trip`、`::test_committed_pairing_fixture_decodes`、`::test_pairing_rejects_malformed`、`::test_encode_key_rejects_wrong_length` |
| 信封 build + validate；缺字段 / 非法 seq / 不支持版本 / 空 channel 时 fail-closed | `test_companion_protocol.py::test_envelope_build_and_validate`、`::test_envelope_validate_fails_closed` |
| APNs 触发为无内容（仅 `ch`/`n`/`c`）；每种可推送类型映射到粗粒度类别；`session_meta` 映射为 none；非法输入抛错 | `test_companion_protocol.py::test_trigger_is_content_free`、`::test_coarse_category_covers_pushable_types`、`::test_trigger_rejects_bad_input`、`::test_committed_trigger_fixture_shape` |
| 中继在存储前剥离明文 `push` 摘要兄弟字段 —— 只持久化 / 回传加密信封 | `relay/test/relay.test.js` “strips the cleartext push sibling before storing the envelope” |

### `companion-bridge`

桌面发送端：配对 + 二维码、secretbox 封装、复用 watchdog 的推送策略、
有界中继队列，以及 `companion` CLI。sink 消费的是 JSONL 写入器产出的同一个
payload dict（经 `EventLogger` observer tap），因此转发的事件不会与日志分叉。

| Requirement | 测试 |
|---|---|
| sink 消费 JSONL 写入器产出的同一 dict（observer tap），无文件 sink 时也会触发 | `test_companion_sender.py::test_event_logger_observer_sees_exact_written_payload`、`::test_event_logger_observer_fires_without_a_sink` |
| 事件用 secretbox 封装并可往返；篡改 / 错误密钥 / 错误密钥长度 全部 fail-closed | `test_companion_sender.py::test_seal_open_round_trip`、`::test_open_rejects_tampered_ciphertext`、`::test_open_rejects_wrong_key`、`::test_seal_rejects_bad_key_length` |
| 配对状态可扫码、git 忽略持久化、跨重启单调推进 seq、解除配对时清除；路径遵循 `DITING_COMPANION_STATE` | `test_companion_sender.py::test_generate_state_is_well_formed`、`::test_state_save_load_round_trip`、`::test_next_seq_persists_monotonically`、`::test_load_absent_is_none_and_clear`、`::test_render_qr_produces_block_art`、`::test_default_state_path_env_override` |
| 推送策略复用 watchdog：跳过非推送类型、在静默窗口内按目标合并、对 `rf_stir` 按置信度门控 | `test_companion_sender.py::test_policy_skips_non_pushable_types`、`::test_policy_silence_window_coalesces_same_target`、`::test_policy_distinct_targets_independent`、`::test_policy_rf_stir_confidence_gate` |
| 中继客户端按序冲刷、失败时停止并保序随后重试、溢出丢最旧并计数、转发粗粒度类别头 | `test_companion_sender.py::test_flush_sends_all_in_order_on_success`、`::test_flush_stops_and_preserves_order_on_failure`、`::test_queue_overflow_drops_oldest_and_counts`、`::test_category_header_forwarded` |
| sink 封装并入队可推送事件（可解密回原文）并推进 seq；非推送事件被拒且不推进 | `test_companion_sender.py::test_sink_seals_pushable_event_and_advances_seq`、`::test_sink_declines_non_pushable` |
| **add-familiarity-baseline** —— sink 在封装前剥离桌面本地字段（`familiarity`），使封装副本保持在 `companion-protocol` 内（移动端跑严格 `validate_event`）；不改调用方的 dict，JSONL 日志保留该字段 | `test_companion_sender.py::test_sink_strips_familiarity_before_sealing` |
| **add-event-salience** —— push policy 先过 salience 门：丢弃低于 `min_salience`（默认 `low`，`DITING_PUSH_MIN_SALIENCE` 覆盖）的事件，从而压制 `noise` 级的 habitual 到达；无 `salience` 字段的 payload 直接放行（no-op）；该门与既有静默窗口叠加。sink 另在封装前剥离 `salience` | `test_companion_sender.py::test_policy_salience_gate_suppresses_noise`、`::test_policy_salience_gate_passes_when_field_absent`、`::test_policy_salience_threshold_override`、`::test_policy_min_salience_reads_env`、`::test_sink_strips_familiarity_before_sealing`（现也断言 `salience` 被剥离） |
| 推送摘要按类型具体化，缺字段时退化为占位符再退化为类型名，绝不抛错 | `test_companion_sender.py::test_push_summary_is_specific_per_type`、`::test_push_summary_falls_back_to_a_label_then_type` |
| 明文摘要作为 `push` 兄弟字段随行而不改动信封；无内容可说时不带该字段 | `test_companion_sender.py::test_summary_rides_as_push_sibling_without_touching_envelope`、`::test_no_push_sibling_when_no_summary_or_category` |
| `companion` CLI 配对 / 状态 / 解除；未知动作退出码 2；relay URL 优先级（flag > env > default） | `test_companion_cli.py::test_pair_status_unpair_round_trip`、`::test_unknown_action_exits_2`、`::test_relay_url_precedence` |
| `--no-companion` 从 argv 剥离并固定 `DITING_COMPANION=0`（单次自测静音）；未带时不设环境变量；该门控即使已配对也让 `build_sink` 失效 | `test_cli.py::test_no_companion_flag_sets_env_and_strips`、`::test_no_companion_flag_absent_leaves_env_unset`、`::test_no_companion_env_makes_build_sink_inert` |

### `cli`

| Requirement | 测试 |
|---|---|
| `diting` 不带子命令 → 启动 TUI | (人工 — App boot 由 `test_tui_smoke.py::test_app_boots_and_quits` 间接覆盖) |
| 5 个子命令：`once` / `watch` / `monitor` / `calibrate` / `analyze` | (gap — 没有派发表的集成测试；子命令内部各自有测试) |
| `--lang en|zh` 优先于 env / locale | `test_i18n.py::test_resolve_cli_override_wins_over_env`、`::test_resolve_no_override_uses_env`、`::test_resolve_rejects_unknown_cli_value` |
| `--log [PATH]` 启用 JSONL 日志，可省略路径 | `test_event_log.py::test_default_log_path_is_timestamped_jsonl`、`::test_resolve_log_path_cli_no_value_uses_default`、`::test_resolve_log_path_cli_explicit_path_wins`、`::test_resolve_log_path_env_auto_uses_default`、`::test_resolve_log_path_env_blank_disables`、`::test_extract_log_arg_no_value_returns_sentinel` |
| 用了 `--log` 时退出印 analyze 提示 | (gap — 退出 hint 字符串没有自动化断言) |
| `diting monitor` stdout 只发 JSONL | `test_event_log.py::test_to_path_writes_appendable_jsonl`（事件格式）；banner-cleanliness 是人工 |
| `--config <PATH>` 覆盖 aps.yaml 搜索路径 | `test_network.py::test_resolve_config_path_env_override_wins`、`::test_resolve_config_path_no_env_falls_through_to_default` |
| `--notify` 在默认 TUI 子命令与 `monitor` 上都可用 | `test_tui_smoke.py::test_app_with_notify_calls_watchdog_on_event`（TUI wire-up）；`test_watchdog.py::test_maybe_notify_fires_for_latency_spike`（monitor wire-up）；旗标解析 review-enforced |
| `--version`（或 `-V`）打印 `diting <版本号>` 后退出 0，在 locale / TUI / helper 之前短路 | `test_cli.py::test_version_flag_prints_running_version`、`::test_version_flag_short_dash_v`、`::test_version_short_circuits_before_locale` |
| **v1.8.0** —— 启动 splash 渲染先于 `_ensure_helper_ready` 的 TCC 探测：所有帧的行 / 列数与 `_LOGO_MARK_ART` 一致；相邻帧相差 ≤ 2 个 cell（保持轮廓）；Tier A 交互式 TTY → Rich `Live` 渲染节奏状态行；Tier B 窄 TTY（< 30 列）→ 静态帧 + `\r` 覆盖；Tier C 非 TTY → 一行 `diting starting...`；探测返回 falsy 时标 `[✗]`；探测抛异常时 teardown 后重抛；ZH locale 渲染翻译后的状态标签 | `test_splash.py::test_frames_share_row_and_column_count`、`::test_adjacent_frames_differ_by_at_most_two_cells`、`::test_run_with_splash_tier_c_non_tty`、`::test_run_with_splash_tier_b_narrow`、`::test_run_with_splash_tick_sequence`、`::test_run_with_splash_callable_falsy_marks_step_failed`、`::test_run_with_splash_callable_raising_reraises_after_teardown`、`::test_run_with_splash_zh_locale`；`test_cli.py::test_ensure_helper_ready_drives_splash_for_two_tcc_probes` |

### `environment-monitor`

| Requirement | 测试 |
|---|---|
| σ 阈值用命名常量 | (review-enforced — STIR 图例渲染时从 `DEFAULT_SPIKE_RATIO` / `DEFAULT_SPIKE_MIN_DB` 拿值；`test_environment.py::test_sigma_above_threshold_fires_event` 间接验证常量被正确串起来了) |
| 必须同时超 ratio 和绝对 floor 才触发 | `test_environment.py::test_sigma_above_threshold_fires_event`、`::test_sigma_below_threshold_no_event` |
| 每个 AP 归三档 fusion mode | `test_environment.py::test_co_located_vs_spatial_channel_classification`、`::test_redundancy_fusion_makes_two_co_located_events_high_confidence`、`::test_single_co_located_event_is_medium_confidence`、`::test_spatial_channel_event_uses_ap_location_label`、`::test_aps_below_minus_85_excluded` |
| Cooldown + rearm 防止重复事件 | (gap — 没有专门的 cooldown / rearm 测试；行为在 fusion-confidence 测试里间接覆盖) |
| 校准从文件加载 | `test_environment.py::test_calibration_overrides_adaptive_baseline`、`::test_calibration_round_trip`、`::test_load_calibration_returns_empty_dict_on_missing_file` |
| 措辞：相关性，不是「有人」 | (review-enforced — `i18n.py` 没有任何字符串断言 "person" / "motion" / "presence") |
| `RFStirEvent` 在触发时把当前 `Connection.ssid` 带进事件 | `test_environment.py::test_rf_stir_event_carries_ssid_from_current_connection` |

### `scenes`

| Requirement | 测试 |
|---|---|
| 四个 canonical 场景名（`home` / `office` / `public` / `audit`）；默认 `home`；CLI > env > default 优先级；空 env 退到 default；非法 env 警告并退到 default；非法 CLI 报错 | `test_scene.py::test_valid_scenes_returns_exactly_four_canonical_names`、`::test_default_scene_is_home`、`::test_resolve_cli_wins_over_env`、`::test_resolve_env_fills_in_when_no_cli`、`::test_resolve_blank_env_falls_to_default`、`::test_resolve_invalid_env_warns_and_defaults`、`::test_resolve_invalid_cli_raises_value_error`、`::test_set_scene_invalid_raises`、`::test_set_scene_get_scene_roundtrip` |
| `scene_defaults(scene)` 返回稳定的每场景旋钮字典；`home=5s` / `office=15s` / `public=30s` / `audit=0s` presence gate；每场景都有非空 `llm_prior`；调用方用 `.get()` 防御性读取未来旋钮 | `test_scene.py::test_scene_defaults_home_presence_gate_is_5s`、`::test_scene_defaults_office_presence_gate_is_15s`、`::test_scene_defaults_public_presence_gate_is_30s`、`::test_scene_defaults_audit_presence_gate_is_zero`、`::test_scene_defaults_includes_llm_prior_for_every_scene`、`::test_scene_defaults_unknown_scene_raises`、`::test_callers_can_read_knobs_defensively` |
| `--scene SCENE` flag + `DITING_SCENE` env 接好；`--ble-presence-gate D` 覆盖场景默认；env 覆盖场景默认；空 / 非法 env 退到场景默认 | `test_cli.py::test_extract_scene_arg_parses_value`、`::test_extract_scene_arg_parses_equals_form`、`::test_extract_scene_arg_absent_returns_none`、`::test_extract_scene_arg_invalid_value_exits`、`::test_extract_scene_arg_missing_value_exits`、`::test_resolve_ble_presence_gate_uses_scene_default_when_no_cli_no_env`、`::test_resolve_ble_presence_gate_cli_overrides_scene_default`、`::test_resolve_ble_presence_gate_env_wins_over_scene_default`、`::test_resolve_ble_presence_gate_blank_env_falls_to_scene_default`、`::test_resolve_ble_presence_gate_invalid_env_falls_to_scene_default` |
| `classify_environment` 启发：Enterprise 认证 → office；≥ 30 BSSID → office；其他 → home；Enterprise 匹配大小写不敏感；阈值 30 含；security 为 None 时容错；开放 Wi-Fi 不自动判为 public | `test_scene.py::test_classify_wpa2_enterprise_returns_office`、`::test_classify_wpa3_enterprise_returns_office`、`::test_classify_case_insensitive_enterprise_match`、`::test_classify_dense_personal_network_is_office`、`::test_classify_sparse_personal_network_is_home`、`::test_classify_open_network_does_not_classify_as_public`、`::test_classify_null_security_falls_to_home`、`::test_classify_threshold_exactly_30_is_office`、`::test_classify_threshold_below_30_is_home`、`::test_classify_reason_is_human_readable` |
| `scenes.yaml` loader —— 缺文件 → 空；SSID 匹配；gateway_mac 匹配（大小写不敏感）；gateway_mac 优先于 SSID；非法 scene 名跳过 + 警告；缺匹配键跳过；顶层结构错误容错；YAML 解析错误容错；`DITING_SCENES_FILE` env 覆盖路径 | `test_scenes_config.py::test_missing_file_returns_empty_registry`、`::test_simple_ssid_match`、`::test_unknown_ssid_returns_none`、`::test_gateway_mac_match_case_insensitive`、`::test_gateway_mac_wins_over_ssid`、`::test_invalid_scene_name_in_entry_is_skipped`、`::test_entry_without_match_key_is_skipped`、`::test_malformed_top_level_is_tolerated`、`::test_unparseable_yaml_is_tolerated`、`::test_empty_file_is_empty_registry`、`::test_lookup_by_ssid_returns_none_for_blank`、`::test_env_var_overrides_default_path` |
| 启动 scene 解析：CLI / env 短路 yaml + 启发；yaml 命中给 source `yaml` + banner；启发在无 yaml 命中时触发；无 Wi-Fi 退到 `default` 不打 banner；`DITING_SCENE_QUIET=1` 静音 banner；banner 走 stderr 不走 stdout | `test_cli.py::test_resolve_scene_at_startup_cli_short_circuits_yaml_and_heuristic`、`::test_resolve_scene_at_startup_env_short_circuits_yaml_and_heuristic`、`::test_resolve_scene_at_startup_yaml_hit`、`::test_resolve_scene_at_startup_heuristic_when_no_yaml`、`::test_resolve_scene_at_startup_no_connection_falls_to_default`、`::test_emit_scene_banner_respects_quiet_env`、`::test_emit_scene_banner_writes_to_stderr_not_stdout`、`::test_emit_scene_banner_none_input_is_no_op` |

### `event-log`

| Requirement | 测试 |
|---|---|
| `session_meta` 在第一行；带 scene + scene_source + diting_version + ssid + gateway_ip + hostname；emit 幂等；disabled logger 是 no-op；SSID / gateway 允许 null 写入 | `test_event_log.py::test_session_meta_writes_header_with_all_fields`、`::test_session_meta_is_first_when_emitted_first`、`::test_session_meta_is_idempotent`、`::test_session_meta_disabled_logger_is_no_op`、`::test_session_meta_accepts_null_ssid_and_gateway` |
| **v1.7.1** —— `DitingApp.__init__` 和 `_run_monitor` 都在 emit `session_meta` 之前同步 `backend.get_connection()`，让 JSONL 头部带启动时的 SSID + 网关 IP，而不是 null。Backend 抛错（helper 未就绪、还没 Wi-Fi）时回退为 None | `test_tui_smoke.py::test_app_session_meta_carries_startup_ssid_and_gateway`、`::test_app_session_meta_absorbs_get_connection_failure` |
| `--log` 与 `diting monitor` 输出字节相等 | `test_event_log.py::test_to_path_writes_appendable_jsonl`、`::test_unicode_user_strings_survive_readable`（共享 writer 类） |
| 每个事件后强制 flush | `test_event_log.py::test_line_buffered_writes_are_visible_before_close` |
| atexit 钩子优雅关闭 writer | (gap — 没有专门的测试；行为在 `test_line_buffered_writes_are_visible_before_close` 里间接覆盖) |
| JSONL 键不随 UI 语言变 | `test_event_log.py::test_schema_keys_stay_english_under_zh_locale` |
| 时间戳本地时区 ISO-8601 带偏移 | `test_event_log.py::test_timestamps_are_iso_utc`、`::test_naive_datetime_treated_as_local_not_utc` |
| writer 接受 `None` 作 no-op | `test_event_log.py::test_disabled_logger_is_a_no_op` |
| `connection_update` 只进日志，不入 EventRing | `test_event_log.py::test_connection_update_emits_associated_on_first_poll`、`::test_connection_update_silent_when_first_poll_is_disassociated`、`::test_connection_update_emits_disassociate_on_drop`、`::test_connection_update_does_not_emit_on_bssid_to_bssid_change` |
| 七个新 emit 方法（`emit_ble_device_seen` / `emit_ble_device_left` / `emit_bonjour_service_seen` / `emit_bonjour_service_left` / `emit_lan_host_seen` / `emit_lan_host_left` / `emit_lan_host_dhcp_rotation`），每个 flush；no-op logger 全部吞掉 | `test_event_log.py::test_emit_ble_device_seen_writes_locale_stable_type`、`::test_emit_ble_device_left_includes_seen_for_seconds`、`::test_emit_bonjour_service_seen_writes_locale_stable_type`、`::test_emit_lan_host_dhcp_rotation_writes_previous_and_new_ip`、`::test_disabled_logger_swallows_all_seven_new_methods` |

### `events`

| Requirement | 测试 |
|---|---|
| 十二事件共享 schema 与 ring（从 5 扩到 12；新增 7 个 BLE / Bonjour / LAN 转移事件） | `test_event_log.py::test_emit_roam_includes_kind_when_supplied`、`::test_emit_latency_spike_carries_target_and_rtt`、`::test_emit_loss_burst_carries_lost_in_window`、`::test_emit_link_state_dataclass_passthrough`、`::test_emit_network_change_carries_router_ip_transition`；新增类型：`test_events.py::test_ble_device_seen_round_trip`、`::test_ble_device_left_round_trip`、`::test_bonjour_service_seen_round_trip`、`::test_bonjour_service_left_round_trip`、`::test_lan_host_seen_round_trip`、`::test_lan_host_left_round_trip`、`::test_lan_host_dhcp_rotation_round_trip` |
| BLE 转移事件携带 rotation-folded 身份（identifier、name、vendor、service_categories）+ RSSI / `last_rssi_dbm` + 离开时 `seen_for_seconds` | `test_events.py::test_ble_device_seen_carries_identity`、`::test_ble_device_left_carries_seen_for_seconds` |
| **events-cascade-census-fold** —— BLE 转移事件额外携带 `device_type` / `device_class`（默认均为 None）；`BLEDeviceSeenEvent` 携带 `at_launch: bool`（默认 False），`BLEDeviceLeftEvent` 不带。JSONL：`device_type` / `device_class` 仅在非 None 时输出（Continuity type 落在 `device_type` 键下，绝不用 `type`）；`at_launch` 仅在 True 时输出；其余情况全部省略（保持旧日志形状稳定） | `test_events.py::test_ble_device_seen_carries_device_type_class_and_at_launch`、`::test_ble_device_left_carries_device_type_class`、`::test_emit_ble_device_seen_writes_device_type_class_at_launch`、`::test_emit_ble_device_seen_omits_device_type_when_none_and_at_launch_when_false`、`::test_emit_ble_device_left_writes_device_type_under_device_type_key` |
| Bonjour 转移事件携带 (service_type, name, host, category, vendor) + 出现时 addresses + 离开时 `seen_for_seconds` | `test_events.py::test_bonjour_service_seen_carries_addresses`、`::test_bonjour_service_left_carries_seen_for_seconds` |
| LAN 转移事件：seen / left / dhcp_rotation 带 MAC 身份；轮换事件带 previous_ip / new_ip | `test_events.py::test_lan_host_seen_carries_mac_identity`、`::test_lan_host_dhcp_rotation_carries_previous_and_new_ip`、`::test_lan_host_left_carries_last_reachable_ago` |
| 新事件 JSONL：None 字段省略；空 tuple 序列化为 `[]` | `test_events.py::test_new_events_omit_none_fields_from_jsonl`、`::test_new_events_serialise_empty_tuple_as_empty_list` |
| 每个事件是 frozen dataclass + timestamp | (compiler / dataclass 层强制；构造该事件的测试间接验证) |
| EventRing 有限大小、单线程 async | (gap — 没有 EventRing 限长的直接测试；ring 在产环境由 App 持有) |
| JSONL 用英文键 | `test_event_log.py::test_schema_keys_stay_english_under_zh_locale` |
| 时间戳本地 TZ ISO-8601 带偏移 | `test_event_log.py::test_timestamps_are_iso_utc`、`::test_naive_datetime_treated_as_local_not_utc` |
| `NetworkChangeEvent` 是控制信号，用户不可见 | `test_event_log.py::test_emit_network_change_carries_router_ip_transition`（writer 接受它）；不进 user-visible-ring 是 review-enforced |
| `RoamEvent` 新增 `previous_ssid` / `new_ssid`、`RFStirEvent` 新增 `ssid`，均默认 `None`（schema 兼容性追加） | `test_event_log.py::test_event_to_jsonl_roundtrip_roam_with_ssid_pair`、`::test_event_to_jsonl_roundtrip_rf_stir_with_ssid`、`::test_event_to_jsonl_omits_ssid_keys_when_none` |
| **add-familiarity-baseline** —— seen 事件（`ble_device_seen`、`bonjour_service_seen`、`lan_host_seen`）与 `roam` 新增可选 `familiarity` 字段（`first_time`/`occasional`/`habitual`/`returning`），仅在接入 store 时由 `EventLogger` 标注；否则 JSONL 省略该 key（旧形状兼容）。`BLEDeviceSeenEvent`/`BLEDeviceLeftEvent` 另带仅内存的 `vendor_id` / `manufacturer_hex`（familiarity key 的输入，永不序列化） | `test_event_log.py::test_ble_seen_omits_familiarity_without_a_store`、`::test_ble_seen_first_sighting_is_first_time`、`::test_lan_seen_carries_familiarity_keyed_on_mac`、`::test_bonjour_seen_carries_familiarity`、`::test_roam_carries_ap_familiarity_on_new_bssid` |
| **add-event-salience** —— 事件带可选 `salience` 层级（`noise`/`low`/`notable`/`high`），由 `EventLogger._emit` 从 scorer 集中标注；弃权类型省略（旧形状兼容）；桌面本地（companion wire 剥离） | `test_event_log.py::test_emit_stamps_salience_on_scored_event`、`::test_emit_omits_salience_on_unscored_event`（完整 scorer 覆盖见 `salience` 能力段） |
| **add-insight-events** —— 新增 `insight` 事件类型，带稳定英文 `code`、`severity`（`info`/`note`/`warn`）与展平的 `detail` 键（缺省时省略）；人类一行摘要在渲染时生成，不序列化 | `test_event_log.py::test_emit_insight_writes_code_severity_and_detail`、`::test_emit_insight_omits_detail_when_absent` |

### `familiarity-store`

| 需求 | 测试 |
|---|---|
| `familiarity_key` 为每类实体推导稳定、权威的身份 —— BLE 优先用厂商 payload（payload-fusion token），仅在无可用 payload 时退回 `(vendor_id, name)`，永不用滚动 UUID；排除 Apple Continuity payload（退回）；ap→`bssid`、lan→`mac`、bonjour→`service`；无稳定身份返回 `None` | `test_familiarity.py::test_ble_key_prefers_payload_not_uuid_or_name`、`::test_ble_key_falls_back_to_vendor_name_without_payload`、`::test_ble_apple_payload_is_not_used_as_key`、`::test_other_kinds_key_on_address_not_name`、`::test_key_is_none_without_stable_identity` |
| `observe_seen` 在并入本次出现之前按历史分类：首次→`first_time`；`>= _HABITUAL_DAYS`（3）个不同日→`habitual`；曾 habitual 但缺席 `> _RETURNING_GAP_DAYS`（7）→`returning`；否则 `occasional` | `test_familiarity.py::test_first_ever_is_first_time`、`::test_second_sighting_same_day_is_occasional`、`::test_habitual_after_three_distinct_days`、`::test_returning_after_long_absence` |
| `observe_left` 把 seen→left 停留时长折进每实体 EWMA（`0.3·新 + 0.7·旧`）；首样本作种 | `test_familiarity.py::test_dwell_ewma_folds` |
| store 跨重启持久化（记录、days 集合、dwell 往返）；读取 fail-soft（文件损坏→空，记录损坏→跳过，绝不抛错） | `test_familiarity.py::test_persistence_round_trip`、`::test_corrupt_file_is_failsoft`、`::test_corrupt_record_skipped_valid_kept` |
| 有界：flush 时淘汰 `> _AGE_OUT_DAYS`（30）未见的实体；上限 `_MAX_ENTITIES`，保留最近所见 | `test_familiarity.py::test_age_out_on_flush` |
| BLE seen/left 构造时标注 `vendor_id` + `manufacturer_hex`（cluster-left 用 cluster 锚而非被淘汰成员，使 dwell 折进 seen 的 key）；left 侧 dwell 落到同一 payload key | `test_event_log.py::test_ble_familiarity_keys_on_payload_not_rotating_id`、`::test_ble_left_folds_dwell_under_payload_key` |
| 即使日志关闭基线也持续累积（store 在 sink 守卫之前更新） | `test_event_log.py::test_baseline_accrues_even_when_logging_disabled` |

### `salience`

| 需求 | 测试 |
|---|---|
| 层级有序 `noise` < `low` < `notable` < `high`；未知/缺失层级排在 `noise` 之下；`meets_threshold` 比较正确，缺失层级不满足任何阈值 | `test_salience.py::test_tier_rank_is_ordered`、`::test_unknown_or_missing_tier_ranks_below_noise`、`::test_meets_threshold` |
| 到达事件按熟悉度加权：`habitual`→`noise`、`occasional`→`low`、`returning`→`notable`、`first_time`→`notable`（仅近距 BLE 设备 `rssi_dbm >= -60` 提升到 `high`）；无熟悉度→`low`（绝不 `noise`）；启动预热封顶在 `notable` 之下 | `test_salience.py::test_habitual_arrival_is_noise`、`::test_occasional_arrival_is_low`、`::test_returning_arrival_is_notable`、`::test_first_time_arrival_is_notable_when_far`、`::test_first_time_close_ble_is_high`、`::test_close_bump_is_ble_only`、`::test_absent_familiarity_arrival_is_low_never_noise`、`::test_at_launch_caps_below_notable` |
| 固有异常与熟悉度无关：`loss_burst`→`high`、`latency_spike`/`network_change`→`notable`、`rf_stir` 随 confidence 缩放（high/medium/low）、`link_state` disassociated→`notable` / associated→`low` | `test_salience.py::test_loss_burst_is_high`、`::test_latency_spike_is_notable`、`::test_network_change_is_notable`、`::test_rf_stir_scales_with_confidence`、`::test_link_state_disassociated_is_notable_associated_low` |
| `roam`：`band_switch`→`low`（常规换频）；跨 AP 按 payload 上的 AP 熟悉度排序 | `test_salience.py::test_band_switch_roam_is_low`、`::test_inter_ap_roam_to_new_bssid_is_notable` |
| 离开（`*_left`）→`noise`、`lan_host_dhcp_rotation`→`low`；`session_meta` / 未知类型 / 畸形输入弃权（`None`），绝不抛错 | `test_salience.py::test_departures_are_noise`、`::test_dhcp_rotation_is_low`、`::test_session_meta_abstains`、`::test_unknown_type_abstains`、`::test_never_raises_on_malformed` |
| `EventLogger._emit` 集中标注 `salience`（在 `familiarity` 之后、为 JSONL writer 与 observer tap 各算一次）；弃权类型省略该 key；标注反映同次 emit 的熟悉度 | `test_event_log.py::test_emit_stamps_salience_on_scored_event`、`::test_emit_omits_salience_on_unscored_event`、`::test_first_time_ble_seen_salience_reflects_familiarity` |
| `insight` 的 salience 由 severity 映射：`warn`→`high`、`note`→`notable`、`info`→`low` | `test_event_log.py::test_emit_insight_writes_code_severity_and_detail`、`::test_warn_insight_salience_is_high` |

### `insights`

| 需求 | 测试 |
|---|---|
| 引擎把 enriched payload 折入有界滚动窗口；hermetic（注入 payload + `now`）；忽略自身 `insight` 输出；畸形不抛错；旧事件淘汰 | `test_insights.py::test_ignores_insight_payloads`、`::test_never_raises_on_malformed`、`::test_loss_burst_with_unparseable_pct_does_not_raise`、`::test_old_events_pruned` |
| **2b** `new_device_cluster` —— 簇窗内 ≥ cluster-min 个 `first_time` 到达（跨 BLE/LAN/Bonjour）触发 `note`；habitual / 不足阈值 / 超窗不触发 | `test_insights.py::test_cluster_fires_on_three_first_time_arrivals`、`::test_cluster_spans_device_kinds`、`::test_habitual_arrivals_do_not_cluster`、`::test_two_arrivals_below_threshold_do_not_cluster`、`::test_arrivals_outside_cluster_window_excluded` |
| 按 code 冷却：一窗内只触发一次，冷却过后有新证据再触发 | `test_insights.py::test_cooldown_fires_once_per_window` |
| **2c** live 化的 analyze 启发式：`repeated_disassociates`（≥3→warn）、`loss_observed`（→warn，峰值）、`latency_without_loss`（有延迟无丢包→note；有丢包则抑制）、`band_steering`（≥5 漫游、>70% 频段→info；跨 AP 不触发） | `test_insights.py::test_repeated_disassociates_warns`、`::test_two_disassociates_below_threshold`、`::test_loss_observed_warns_with_peak`、`::test_latency_without_loss_is_a_note`、`::test_latency_with_loss_suppresses_jitter_note`、`::test_band_steering_info`、`::test_mostly_inter_ap_roams_do_not_band_steer` |
| `format_insight_summary` 由 `code` + `detail` 本地化，未知 code 回退为 code 本身（EN↔ZH 在 `i18n.py` 同步） | `test_insights.py::test_format_summary_localised_keys`、`test_tui_helpers.py::test_event_format_line_insight_renders_summary`、`::test_event_format_line_insight_warn_uses_summary_for_loss` |
| TUI：引擎作为 logger observer 接入；collect 定时器把触发的 insight 落到 Events ring（并 emit + notify）；渲染 `[INSIGHT]` 行 | `test_tui_smoke.py::test_insight_engine_wired_and_drains_into_ring`、`test_tui_helpers.py::test_event_format_line_insight_renders_summary` |
| insight 为桌面本地：不在 companion push 集，永不转发 | `test_companion_sender.py::test_policy_does_not_push_insight_events` |
| 多 observer logger：每个已注册 observer 都收到每条 payload；`set_observer` 管自己的槽位而不丢弃 `add_observer` 的 tap（引擎在 companion 重新配对后仍存活） | `test_event_log.py::test_multiple_observers_all_receive_payload`、`::test_set_observer_leaves_added_observers_intact` |

### `i18n`

| Requirement | 测试 |
|---|---|
| 启动时一次性解析语言 | `test_i18n.py::test_detect_explicit_diting_lang_wins_over_locale`、`::test_detect_zh_from_lang_env`、`::test_detect_zh_from_lc_all_overrides_lang`、`::test_detect_falls_back_to_english`、`::test_detect_ignores_invalid_diting_lang_value`、`::test_resolve_cli_override_wins_over_env`、`::test_resolve_no_override_uses_env`、`::test_resolve_rejects_unknown_cli_value`、`::test_set_lang_rejects_unknown_value` |
| 用户字串走 `t()` | `test_i18n.py::test_t_returns_english_when_lang_is_english`、`::test_t_falls_back_to_english_when_zh_key_missing`、`::test_t_substitutes_placeholders`、`::test_t_substitutes_in_english_too`（`t()` 行为）；"无硬编码字串"覆盖是 review-enforced |
| 列对齐 widget 用 `pad_cells` / `fit_cells` | `test_i18n.py::test_pad_cells_pads_ascii_to_target_width`、`::test_pad_cells_treats_cjk_as_two_cells_each`、`::test_pad_cells_returns_unchanged_if_already_wide`、`::test_pad_cells_handles_mixed_ascii_and_cjk`（注：`fit_cells` 本身没有专门测试 — gap） |
| ZH UI 的 JSONL 键依然英文 | `test_event_log.py::test_schema_keys_stay_english_under_zh_locale` |
| 缩写（SSID/BSSID/RSSI 等）不译 | (review-enforced — 目录约定) |
| 目录里 `{placeholder}` 同步保留 | (review-enforced — 缺失会在渲染时 KeyError) |
| **v1.7.2** —— ZH 目录补齐 2026-05-25 中文版审计发现的七处文案缺口：Shift-P / 公共场景帮助行完整翻译；`service` 排序标记译为「服务」；`Noise / SNR` 标题译为「Noise / 信噪比」；裸 `" ago"` key 保留前导空格（`8s 前`）；Apple Continuity 协议名（Apple Companion / Apple Proximity）保留品牌字面而不半译；BLE 详情广告间隔提示改为值后置（「广告间隔约 1772 ms」） | `test_i18n.py::test_zh_catalog_has_lan_probe_help_string`、`::test_zh_catalog_translates_service_sort_token`、`::test_zh_catalog_translates_noise_snr_heading`、`::test_zh_catalog_preserves_leading_space_on_ago_key`、`::test_zh_catalog_keeps_apple_companion_brand_verbatim`、`::test_zh_catalog_keeps_apple_proximity_brand_verbatim`、`::test_zh_catalog_reorders_between_ads_hint_value_last` |
| **events-cascade-census-fold** —— ZH 目录提供启动点名汇总字符串（`session start` → `会话开始`、`{n} devices already present` → `已在场 {n} 个设备`、`enter to expand` → `回车展开`、`enter to collapse` → `回车收起`），保留 `{n}` 占位符 | `test_i18n.py::test_zh_catalog_has_census_summary_strings`、`::test_zh_catalog_preserves_placeholder_in_devices_present` |

### `inventory`

| Requirement | 测试 |
|---|---|
| 4 步 AP 归属链 | `test_network.py::test_radio_overrides_win_over_rule_match`、`::test_radio_overrides_case_insensitive`、`::test_resolve_primary_rule`、`::test_resolve_secondary_rule_cross_oui`、`::test_resolve_three_aps_in_one_oui_do_not_collapse`、`::test_resolve_outside_window_returns_none`、`::test_cluster_label_groups_chip`（fallback） |
| `aps.yaml` 可选，缺失工具仍能跑 | `test_network.py::test_load_inventory_missing_file_returns_empty` |
| Inventory 同时承载 Wi-Fi OUI 厂商表 | `test_network.py::test_lookup_ap_vendor_known_oui_returns_name`、`::test_lookup_ap_vendor_unknown_oui_returns_none`、`::test_lookup_ap_vendor_invalid_input_returns_none`、`::test_lookup_ap_vendor_accepts_custom_map`、`::test_load_wifi_ouis_ships_xiaomi`、`test_ble.py::test_load_ouis_ships_apple_magic_keyboard_oui` |
| Cluster label 跨会话稳定 | `test_network.py::test_cluster_label_groups_chip`、`::test_cluster_label_separates_unrelated`、`::test_cluster_label_none_or_malformed` |
| BSSID 格式归一（小写、冒号分隔） | `test_network.py::test_format_bssid_known_with_band`、`::test_format_bssid_unknown_passthrough`、`::test_format_bssid_none`、`test_ble.py::test_lookup_oui_vendor_dash_separated_mac`、`::test_lookup_oui_vendor_colon_separated_mac` |

### `installation`

| Requirement | 测试 |
|---|---|
| 一行 installer 在 macOS 上落地可用的 `diting`，无需 Python / uv / Xcode | （人工 — 在干净账号上端到端安装；下面单测覆盖 install.sh 各分支） |
| 在非 macOS 主机上拒绝并给出明确错误 | `test_install.py::test_install_script_refuses_linux`、`::test_install_script_refuses_unknown_uname` |
| Tarball SHA256 对 `SHASUMS256.txt` 校验，不一致即 abort | `test_install.py::test_install_script_aborts_on_sha_mismatch`、`::test_install_script_accepts_matching_sha` |
| Tarball 解压到 `~/.local/share/diting/`，symlink 落 `~/.local/bin/diting`；不要求 sudo | `test_install.py::test_install_script_lays_out_user_local_paths_in_dry_run` |
| Helper bundle 拷贝到 `~/Library/Application Support/diting/`，剥离 quarantine xattr，`open` 触发 TCC | `test_install.py::test_install_script_primes_application_support_helper_in_dry_run` |
| 安装期 locale 从 `defaults read -g AppleLanguages` 派生，并通过 `--env DITING_LANG=` + `--args -AppleLanguages '(<tag>)'` 同时透传给 helper，使 helper UI 与 macOS TCC 弹窗语言一致 | `test_install.py::test_install_script_primes_application_support_helper_in_dry_run` |
| `~/.local/bin` 不在 PATH 时输出对应 shell 的 PATH 更新提示（zsh / bash / fish 三种） | `test_install.py::test_install_script_emits_zsh_path_hint`、`::test_install_script_silent_when_already_on_path` |
| `DITING_VERSION=vX.Y.Z` 环境变量锁版本 | `test_install.py::test_install_script_uses_diting_version_override` |
| 冻结二进制与 `uv run diting` 开发流共存 | （review-enforced — 搜索路径优先级把 in-repo 开发构建排在前；通过 `test_helper.py::test_find_helper_repo_dev_build_shadows_application_support` 验证） |
| **v1.8.0** —— 三层输出梯度：TIER LOG（非 TTY）与改造前字节相同，保证 Homebrew + CI 解析继续可用；TIER PLAIN（TTY + `NO_COLOR` / `LC_ALL=C` / `TERM=dumb`）保留六步编号结构 + ASCII `[OK]` / `[FAIL]` 标记；TIER FULL（TTY + UTF-8 + 彩色）追加像素野兽 header + 24-bit ANSI 品牌橙 + Unicode `✓` / `✗` 标记 + 缩进 `Installed.` 收尾块。`DITING_INSTALL_FORMAT={full,plain,log}` 显式覆盖 | `test_install.py::test_tier_log_byte_identical_under_non_tty`、`::test_tier_full_under_pty`、`::test_tier_plain_under_pty_with_no_color`、`::test_tier_format_env_override_forces_log_on_tty`、`::test_tier_plain_under_lc_all_c`、`::test_die_with_marker_failure_path_keeps_exit_status` |
| **v1.8.0** —— CDN 回退下载梯度：`auto`（默认）先用 `curl --max-time 20` 试 GitHub，失败时回退到 `https://ghproxy.com/<github-url>`；`github` 锁回退（与改造前一致）；`ghproxy` 跳过 GitHub 直接走镜像（适合 CN 已知不通的用户）；`DITING_INSTALL_MIRROR` 取非法值时下载前即 abort。SHA256 校验对实际下载到的字节做，信任仍锚定 canonical SHASUMS（与哪条 URL 服务了字节无关） | `test_install.py::test_mirror_env_default_auto_ladder`、`::test_mirror_env_invalid_value_aborts`、`::test_mirror_env_github_only_skips_ghproxy_path`、`::test_mirror_env_ghproxy_keyword_uses_chain`、`::test_auto_ladder_falls_back_when_github_fails`、`::test_auto_ladder_emits_no_notice_when_github_succeeds`、`::test_sha_verification_runs_against_ghproxy_served_bytes`、`::test_completion_notice_uses_zh_locale_when_helper_lang_is_zh` |
| **install-mirror-resilience** —— 死掉的单一 `ghproxy.com` 回退换成有序的活代理链（`ghfast.top` → `gh-proxy.com` → `ghproxy.net`），每次尝试都做内容校验：`SHASUMS256.txt` 只有能解析出目标 tarball 的 64 位 hex 条目才接受（HTML/空的 200 一律拒绝），tarball 必须是合法 gzip 才接受；被拒的内容丢弃并试下一个；整条链都失败时报真实错误（不再是 "missing entry"）。`SHASUMS256.txt` 始终优先 GitHub 直连，与 tarball 来源无关。`DITING_INSTALL_MIRROR` 额外接受自定义 `http(s)://` 代理前缀；`ghproxy` 现在表示走活代理链（跳过 GitHub 优先）；非法值 abort 并提示 `auto\|github\|ghproxy\|<url>`（另见上一行的 `::test_mirror_env_ghproxy_keyword_uses_chain`、`::test_mirror_env_invalid_value_aborts`、`::test_sha_verification_runs_against_ghproxy_served_bytes`） | `test_install.py::test_mirror_chain_falls_through_to_second_proxy`、`::test_mirror_rejects_html_200_and_tries_next`、`::test_mirror_chain_exhausted_aborts`、`::test_shasums_prefers_github_direct_when_tarball_mirrored`、`::test_mirror_custom_url_override` |

### `lan-inventory`

| Requirement | 测试 |
|---|---|
| 能力默认开启；`LANInventoryPoller` 在用户首次进入 LAN 视图时延迟构造 | `test_lan.py::test_poller_not_constructed_before_lan_view_entry`、`::test_poller_constructed_on_first_lan_view_entry`；TUI 接线：`test_tui_smoke.py::test_lan_poller_lazy_starts_on_third_n_press` |
| 子网推导：netmask 比 /24 宽时，默认 cap 到 `iface_ip` 周围的 /24 | `test_lan.py::test_subnet_from_ifconfig_parses_typical_home_24`、`::test_subnet_caps_at_24_when_netmask_wider`、`::test_subnet_uses_full_subnet_when_netmask_is_25_or_narrower` |
| `DITING_LAN_INVENTORY_WIDE=1` 把 cap 放宽到 /22（仍强制） | `test_lan.py::test_subnet_caps_at_22_when_wide_flag_set`、`::test_subnet_still_caps_at_22_when_wide_flag_set_and_netmask_is_16`、`::test_subnet_uses_full_subnet_when_native_22_and_wide_flag_set` |
| ICMP sweep — 非特权 `ping -c 1 -W <ms>`，30 并发 `asyncio.Semaphore` | `test_lan.py::test_ping_one_returns_true_on_zero_exit`、`::test_ping_one_returns_false_on_nonzero_exit`、`::test_sweep_caps_concurrency_at_thirty` |
| `_ping_one` 解析 `time=X.XXX ms` 返回 `(reachable, rtt_ms \| None)`；stdout 解析不出时 `(True, None)`；非零退出 `(False, None)` | `test_lan.py::test_ping_one_returns_rtt_on_zero_exit`、`::test_ping_one_returns_none_rtt_on_nonzero_exit`、`::test_ping_one_returns_true_none_when_stdout_unparseable` |
| `_sweep` 返回 `{ip: (reachable, rtt_ms)}` 字典 | `test_lan.py::test_sweep_returns_per_ip_results_dict` |
| `arp -an` 解析提取 MAC ↔ IP 三元组；`<incomplete>` 行跳过 | `test_lan.py::test_arp_parse_extracts_mac_and_ip`、`::test_arp_parse_skips_incomplete_entries`、`::test_arp_parse_handles_mixed_format_lines` |
| `LANHost` 以小写 MAC 为 key；DHCP IP 轮转时 `first_seen` 保留 | `test_lan.py::test_lan_host_keyed_by_mac_keeps_first_seen_across_ip_change`、`::test_lan_host_last_seen_updates_on_every_observation` |
| `LANHost.last_rtt_ms` 由 sweep 填充；静默 tick 中保留 | `test_lan.py::test_lan_host_last_rtt_ms_populated_from_sweep`、`::test_lan_host_last_rtt_ms_preserved_when_silent_tick` |
| `LANHost.last_reachable_at` 与 `last_seen` 区分；主机静默时保留 | `test_lan.py::test_lan_host_last_reachable_at_set_on_successful_ping`、`::test_lan_host_last_reachable_at_preserved_when_silent`、`::test_lan_host_last_reachable_at_none_when_never_reached` |
| OUI refresh 脚本按 `registry` 参数解析三个 IEEE 层级（MA-L / MA-M / MA-S）| `test_lan.py::test_oui_refresh_script_parses_csv_to_aabbcc_keys`、`::test_oui_refresh_script_parses_each_tier_separately`、`::test_oui_refresh_script_dedupes_repeated_assignments` |
| 本地管理（随机）MAC 通过首字节 0x02 位标记 | `test_lan.py::test_is_randomised_mac_detects_locally_administered_bit`、`::test_is_randomised_mac_clears_for_universal_macs` |
| OUI 厂商查询走多层级注册表（MA-L 24-bit → MA-M 28-bit → MA-S 36-bit）；最长前缀胜出 | `test_oui_multitier.py::test_lookup_prefers_ma_s_over_ma_m_and_ma_l`、`::test_lookup_falls_back_to_ma_m_when_ma_s_missing`、`::test_lookup_falls_back_to_ma_l_when_higher_tiers_missing`、`::test_lookup_returns_none_when_no_tier_matches`、`::test_load_ouis_layered_tolerates_missing_files` |
| 单层级签名 `lookup_oui_vendor(mac, ouis)` 向后兼容 | `test_oui_multitier.py::test_legacy_signature_still_works`；`test_ble.py::test_lookup_oui_vendor_dash_separated_mac`、`::test_lookup_oui_vendor_colon_separated_mac`（未触动） |
| `LANHost.vendor` 是规范化显示名；`LANHost.vendor_raw` 保留 IEEE 原文；随机 MAC 两者均为 None | `test_lan.py::test_vendor_normalized_on_host_when_lookup_hits`、`::test_vendor_raw_preserved_when_normalization_changes_name`、`::test_vendor_raw_none_for_random_mac` |
| `_normalize_vendor` 剥离尾部公司形态噪声词（CO., LTD, CORPORATION, INC, TECHNOLOGIES 等） | `test_vendor_normalize.py::test_strips_co_ltd_suffix`、`::test_strips_corporation_suffix`、`::test_strips_technologies_suffix`、`::test_strips_inc_suffix` |
| `_normalize_vendor` 剥离开头的中国城市前缀（SHENZHEN、HANGZHOU、BEIJING、SHANGHAI、GUANGZHOU 等） | `test_vendor_normalize.py::test_strips_shenzhen_prefix`、`::test_strips_hangzhou_prefix`、`::test_strips_multiple_geographic_prefixes` |
| `_normalize_vendor` titlecase 输出，同时按 `_ACRONYM_OVERRIDES` 保留缩写（HP、IBM、ASUS、H3C、TP-Link 等） | `test_vendor_normalize.py::test_titlecases_default`、`::test_preserves_h3c_acronym`、`::test_preserves_asus_acronym`、`::test_preserves_tp_link_brand` |
| `_normalize_vendor` 在 16 cell 列宽处截断并加省略号 | `test_vendor_normalize.py::test_truncates_to_column_width`、`::test_idempotent_under_repeated_calls` |
| LAN 详情模态在 normalization 改了名字时，在 dim 续行展示 IEEE 原文 | `test_tui_helpers.py::test_lan_detail_shows_raw_ieee_continuation_when_normalized`、`::test_lan_detail_omits_raw_continuation_when_unchanged` |
| Bonjour 交叉引用走 `BonjourPoller._state` 填充 `bonjour_name` / `bonjour_services` | `test_lan.py::test_bonjour_cross_ref_pulls_name_from_state`、`::test_bonjour_cross_ref_aggregates_categories`、`::test_bonjour_cross_ref_leaves_name_none_when_no_match` |
| Poller 不开 raw socket、不做 TCP port scan / banner grab | (review-enforced — `src/diting/lan.py` 和 `src/diting/lan_probes.py` 可 grep 检查) |
| 主动探测层按 scene 默认开关：`home` / `office` / `audit` 默认开；`public` 默认关；`DITING_LAN_PROBE=0\|1` 覆盖 | `test_scene.py::test_scene_defaults_lan_active_probe_home_office_audit_true`、`::test_scene_defaults_lan_active_probe_public_false`；`test_lan_probes.py::test_resolve_lan_active_probe_env_overrides_scene_default`、`::test_resolve_lan_active_probe_env_blank_falls_through`、`::test_resolve_lan_active_probe_env_invalid_falls_through` |
| `DITING_LAN_UPNP_FETCH=0\|1` 控制 LOCATION HTTP GET 的可选拉取；默认开 | `test_lan_probes.py::test_resolve_upnp_fetch_enabled_default_true`、`::test_resolve_upnp_fetch_enabled_env_zero_disables` |
| NBNS Name Query：RFC 1002 50 字节通配符 `*` 包（NBSTAT 0x0021 / IN）| `test_lan_probes.py::test_encode_nbns_status_query_is_50_bytes`、`::test_encode_nbns_status_query_uses_wildcard_name_and_nbstat_type`、`::test_encode_nbns_status_query_uses_txn_id`、`::test_encode_nbns_status_query_rejects_out_of_range_txn_id` |
| NBNS Status Response 解析：提取名字表；挑选 workstation（suffix `0x00`、unique） | `test_lan_probes.py::test_parse_nbns_returns_name_table`、`::test_parse_nbns_workstation_name_picks_zero_suffix_unique`、`::test_parse_nbns_skips_group_names`、`::test_parse_nbns_truncated_data_returns_empty`、`::test_parse_nbns_malformed_data_does_not_raise` |
| SSDP M-SEARCH 包结构：HTTP/1.1、`ssdp:all`、MX 可配置 | `test_lan_probes.py::test_ssdp_msearch_packet_has_required_headers`、`::test_ssdp_msearch_packet_can_set_mx` |
| SSDP 响应解析：提取 SERVER / LOCATION / USN / ST | `test_lan_probes.py::test_parse_ssdp_extracts_server_location_usn_st`、`::test_parse_ssdp_rejects_non_200_response`、`::test_parse_ssdp_ignores_malformed_payload`、`::test_parse_ssdp_picks_source_ip_from_caller` |
| UPnP LOCATION XML 解析：提取 friendlyName + modelName；对外部实体免疫 | `test_lan_probes.py::test_parse_upnp_xml_extracts_friendly_name_and_model_name`、`::test_parse_upnp_xml_returns_none_on_missing_fields`、`::test_parse_upnp_xml_ignores_external_entity_doctype` |
| 主动探测 phase fail-soft（NBNS / SSDP / mDNS-meta 异常永不向外抛） | `test_lan.py::test_run_active_probes_swallows_nbns_exception`、`::test_run_active_probes_swallows_ssdp_exception`、`::test_run_active_probes_returns_normally_on_total_phase_failure` |
| `LANHost` 新增 `nbns_name` / `upnp_server` / `upnp_friendly_name` / `upnp_model`；通过 `_apply_probe_results` 按 IP 合并 | `test_lan.py::test_apply_probe_results_merges_nbns_into_state`、`::test_apply_probe_results_merges_upnp_into_state`、`::test_apply_probe_results_leaves_untouched_hosts_alone`、`::test_apply_probe_results_preserves_prior_enrichment_when_new_value_none` |
| Public scene 一次性 consent override：`_one_shot_probe_armed=True` 跑一次后清零 | `test_lan.py::test_one_shot_probe_armed_runs_probes_once_then_clears`、`::test_one_shot_probe_armed_clears_even_when_no_host_replied` |
| BonjourPoller 暴露 `send_meta_query()` 发一条 PTR 查询 `_services._dns-sd._meta._tcp.local.` | `test_mdns.py::test_send_meta_query_returns_false_when_zeroconf_not_started`、`::test_send_meta_query_returns_true_when_zeroconf_running` |
| `_ping_one` 在 RTT 之外解析 TTL；返回 `(reachable, rtt_ms, ttl)` 三元组 | `test_lan.py::test_ping_one_returns_rtt_on_zero_exit`、`::test_ping_one_returns_true_none_when_stdout_unparseable`、`::test_ping_one_returns_false_none_on_oserror`、`::test_ping_one_returns_none_rtt_on_nonzero_exit` |
| `ttl_class_for(ttl)` 把 TTL 分桶：`unix`（50-64）/ `windows`（100-128）/ `router`（200-255）/ None | `test_lan.py::test_ttl_class_unix_band`、`::test_ttl_class_windows_band`、`::test_ttl_class_router_band`、`::test_ttl_class_out_of_range_returns_none`、`::test_ttl_class_none_input_returns_none`、`::test_ttl_class_decremented_hop_still_unix` |
| `LANHost.ttl` + `LANHost.ttl_class` 由 sweep 结果填充；静默 tick 中保留 | `test_lan.py::test_lan_host_ttl_populated_from_sweep`、`::test_lan_host_ttl_preserved_when_silent_tick`、`::test_lan_host_ttl_class_derived_from_ttl_value` |
| `_unpack_sweep_entry` 兼容 2 元组和 3 元组的 sweep_results 形状 | `test_lan.py::test_unpack_sweep_entry_handles_three_tuple`、`::test_unpack_sweep_entry_handles_legacy_two_tuple`、`::test_unpack_sweep_entry_handles_none` |
| 设备分类器：gateway 永远 router；AirPrint Bonjour → printer；UPnP SmartTV/Hisense/Samsung → tv；Hikvision/Dahua/Tapo/Imou → camera；Tuya/Xiaomi/Aqara → smart-home；Sonos/Bose/JBL → speaker；Synology/QNAP → nas；Apple Companion → phone；Nintendo/Sony Interactive → gaming；TP-Link/H3C/Asus/Ubiquiti → router；Windows TTL fallback → desktop | `test_device_class.py::test_gateway_wins_router_regardless_of_vendor`、`::test_airprint_bonjour_signals_printer`、`::test_printer_vendor_signals_printer`、`::test_upnp_smarttv_header_signals_tv`、`::test_hisense_vendor_signals_tv`、`::test_airplay_bonjour_signals_tv`、`::test_hikvision_vendor_signals_camera`、`::test_upnp_camera_server_header_signals_camera`、`::test_tuya_vendor_signals_smart_home`、`::test_xiaomi_vendor_signals_smart_home`、`::test_sonos_bonjour_signals_speaker`、`::test_bose_vendor_signals_speaker`、`::test_synology_vendor_signals_nas`、`::test_smb_bonjour_signals_nas`、`::test_apple_companion_signals_phone`、`::test_nintendo_vendor_signals_gaming`、`::test_tp_link_vendor_signals_router`、`::test_h3c_vendor_signals_router`、`::test_windows_ttl_signals_desktop`、`::test_no_signals_returns_none`、`::test_classifier_never_raises_on_minimal_host` |
| 分类器是纯函数 —— 无 I/O、无全局状态、对任何字段组合都不抛 | `test_device_class.py::test_classifier_with_predicate_raising_skips_and_continues`、`::test_classifier_never_raises_on_minimal_host` |
| `_merge_arp_into_state` 在每个 LANHost 上填 `device_class`；`_apply_probe_results` 在探测富集后重新分类 | `test_lan.py::test_merge_populates_device_class_when_classifier_matches`、`::test_apply_probe_results_reclassifies_after_upnp_lands` |
| LAN 详情模态：`device_class` 非空时渲染 `Class:` 行；空时省略 | `test_tui_helpers.py::test_lan_detail_shows_class_row_when_device_class_present`、`::test_lan_detail_omits_class_row_when_device_class_none` |
| LAN 详情模态：ttl 非空时渲染 `<值> (<class>)`；空时省略 | `test_tui_helpers.py::test_lan_detail_shows_ttl_row_with_class`、`::test_lan_detail_shows_ttl_row_without_class`、`::test_lan_detail_omits_ttl_row_when_ttl_none` |
| `LANActiveProbeConsentedEvent` 数据类带 `timestamp / scene / ssid / nbns_packets / ssdp_packets / mdns_packets`；`EventLogger.emit_lan_active_probe_consented` 写出一条带稳定类型名的 JSONL；ssid 为 None 时省略；sink 为 None 时是无操作 | `test_events.py::test_lan_active_probe_consented_dataclass_carries_required_fields`、`::test_lan_active_probe_consented_logger_writes_jsonl`、`::test_lan_active_probe_consented_omits_ssid_when_none`、`::test_lan_active_probe_consented_logger_with_none_path_is_noop` |
| LAN 行布局（Phase 4 / Fing UX）：`[new]` chip + class 列出现在 vendor **左侧**；device_class 为 None 时 class 列空填；first_seen ≥ 24h、self、gateway 时不带 chip | `test_tui_helpers.py::test_lan_row_includes_class_column_when_device_class_set`、`::test_lan_row_class_column_blank_when_device_class_none`、`::test_lan_row_new_chip_present_when_first_seen_within_24h`、`::test_lan_row_new_chip_absent_when_first_seen_outside_24h`、`::test_lan_row_new_chip_absent_for_self`、`::test_lan_row_new_chip_absent_for_gateway`、`::test_lan_header_line_includes_class_column_before_vendor` |
| `LANProbeConsentScreen` 列出 NBNS 137 / SSDP 1900 / mDNS 5353 包 + 后果说明；SSID 为 None 时显示 `(disassociated)`；冷却中 footer 显示 `wait 2s`，过后翻为 `y probe now`；冷却中按 `y` 是静默 no-op | `test_tui_helpers.py::test_lan_probe_consent_modal_body_lists_packets_and_consequences`、`::test_lan_probe_consent_modal_renders_disassociated_when_ssid_none`、`::test_lan_probe_consent_modal_footer_shows_wait_during_cooldown`、`::test_lan_probe_consent_action_confirm_is_silent_during_cooldown` |
| OUI 查询能处理 macOS `arp -an` 去掉前导零的 octet 形式（`24:f:9b:29:c:56` → 24:0f:9b 前缀）| `test_oui_multitier.py::test_lookup_handles_stripped_zero_octets_in_first_three`、`::test_lookup_legacy_signature_also_handles_stripped_zero_octets`、`::test_lookup_rejects_malformed_octet_count`、`::test_lookup_rejects_oversize_octets` |
| **v1.7.2** —— `_read_arp_cache` 在采集时即对每个 octet 做零位补齐，保证下游所有消费方（LAN 列表、详情弹窗、JSONL 转场事件）都拿到标准的 `aa:bb:cc:dd:ee:ff` 形式，与 macOS `arp -an` 是否裁剪前导零无关；对已经补齐的输入是幂等的 | `test_lan.py::test_arp_parse_zero_pads_stripped_octets`、`::test_arp_parse_idempotent_on_already_padded_mac`、`::test_arp_parse_lowercases_upper_input`、`::test_canon_mac_handles_all_zero_octets` |
| `_read_arp_cache` 过滤掉 IPv4 / IPv6 组播目的 MAC（`01:00:5e:*`、`33:33:*`）—— 这些是 SSDP / mDNS 发送时的副产物，不是真实主机 | `test_lan.py::test_arp_parse_filters_ipv4_multicast_destination_macs`、`::test_arp_parse_filters_ipv6_multicast_destination_macs`、`::test_is_multicast_dest_mac_unit` |
| 事件面板显示本机时间而非 UTC；UTC-aware 事件时间戳通过 `.astimezone()` 转换，与 JSONL `_iso` 约定一致 | `test_tui_helpers.py::test_event_ts_renders_local_time_for_utc_aware_event`、`::test_event_ts_handles_naive_datetime` |
| 分类器：HomePod（`AirPlay audio` + `HomeKit`）→ speaker；iPad（`AirPlay` + `Apple Companion`，无 `AirPlay audio`）→ phone；Apple TV（仅 AirPlay）→ tv；**带 AirPlay receiver 的 Mac（`AirPlay audio` 无 `HomeKit`、厂商=Apple）→ laptop，绝非 speaker**。**针匹配 mdns 模块在 LANHost 上存的人类可读类别字符串（`AirPlay`、`AirPlay audio`、`Apple Companion`、`HomeKit`、`Sonos`、`Mac`、`Screen sharing` 等），不是原始 service-type 名（`_raop._tcp`、`_companion-link._tcp` 在 `bonjour_services` 里永远不会出现）。** | `test_device_class.py::test_homepod_airplay_audio_plus_homekit_signals_speaker_not_tv`、`::test_homepod_full_apple_signature_signals_speaker_not_phone`、`::test_mac_with_airplay_receiver_enabled_signals_laptop_not_speaker`、`::test_ipad_airplay_plus_companion_signals_phone_not_tv`、`::test_apple_tv_airplay_alone_still_signals_tv` |
| Bonjour TXT 里的 Apple 型号代码（`Mac14,2`、`AudioAccessory6,1`、`iPhone16,1`、`iPad14,3`、`AppleTV14,1`）通过 `_APPLE_MODEL_PREFIXES` 映射到设备类。最高置信度的 Apple 侧信号 —— 优先于规则表；解决 Bonjour 类别区分不开 Mac vs HomePod 的根本难题。iPad 路由到专属的 `tablet` 类（不是 phone）| `test_device_class.py::test_apple_model_mac_signals_laptop`、`::test_apple_model_audioaccessory_signals_speaker`、`::test_apple_model_iphone_signals_phone`、`::test_apple_model_ipad_signals_tablet_not_phone`、`::test_apple_model_appletv_signals_tv`、`::test_apple_model_unknown_prefix_falls_through`、`::test_apple_model_macbookpro_explicit_prefix_wins` |
| 设备名（Bonjour 名、反向 DNS hostname）**故意不参与**分类。两个字段都由用户控制 —— 改名不应该改变设备分类。仅使用权威信号：vendor OUI、Bonjour TXT model code、scene 门控的探测结果 | `test_device_class.py::test_bonjour_name_ipad_pattern_does_NOT_signal_tablet`、`::test_renamed_homepod_to_macbook_still_classifies_correctly`、`::test_apple_model_code_still_wins_over_misleading_name` |
| `_bonjour_extract_apple_model` 遍历 Apple Continuity TXT 键（`_airplay._tcp` 用 `model`，`_companion-link._tcp` 用 `rpMd`，`_raop._tcp` 用 `am`），第一个非空胜出。随机 MAC 的 iPad 即使只发 Apple Companion，也能通过 companion-link TXT 里的 `rpMd=iPad14,3` 分类为 tablet，无需依赖可被欺骗的 Bonjour 名 | `test_lan.py::test_bonjour_cross_ref_pulls_apple_model_code_from_txt`、`::test_bonjour_cross_ref_pulls_apple_model_code_from_rpmd_txt`、`::test_bonjour_cross_ref_pulls_apple_model_code_from_am_txt`、`::test_bonjour_cross_ref_apple_model_none_when_no_txt_key_present` |
| `_build_bonjour_index` 返回 `(host, services, apple_model)` 三元组；`LANHost.bonjour_model` 携带同一 IP 上任一 Bonjour entry 的 `model=` TXT 值 | `test_lan.py::test_bonjour_cross_ref_pulls_apple_model_code_from_txt`、`::test_bonjour_cross_ref_apple_model_none_when_no_txt_model` |
| LAN 详情模态 Identity Model 行优先用 `bonjour_model` 而非 UPnP；通过 `_APPLE_MODELS` 查表渲染为 `<友好名> (<原始代码>)`（例如 `MacBook Air 13-inch (M2, 2022) (Mac14,2)`）；未知代码原文展示 | `test_tui_helpers.py::test_lan_detail_identity_prefers_bonjour_model_with_friendly_name`、`::test_lan_detail_identity_uses_raw_code_when_apple_model_unknown` |
| Bonjour 行 vendor 为 None 时，回退到 LAN 侧 OUI 厂商（按 IP 在 `_lan_index_by_ip()` 中匹配），dim cyan 显示标记"借自 LAN" | (review-enforced — `_bonjour_borrow_vendor` in `tui.py`，由 `_bonjour_row_line` 和 `_bonjour_by_host_rows` 调用) |
| Bonjour 详情模态新增 `LAN host` 交叉引用段：MAC、OUI 厂商、设备分类、TTL、NBNS、UPnP server / friendly / model —— 与 LAN 详情模态的 Bonjour services 段对称 | (review-enforced — `BonjourDetailScreen._section_lan_cross_ref` in `tui.py`，无 LAN 主机匹配时省略) |
| LAN 详情模态：网关行的 TTL 不再加 (class) 括号（国内路由器 TTL=128 标 "windows" 误导）；非网关行仍保留括号 | `test_tui_helpers.py::test_lan_detail_ttl_row_suppresses_class_for_gateway`、`::test_lan_detail_ttl_row_keeps_class_for_non_gateway` |
| LAN 详情模态：探测后显示 Active discovery 段（NBNS / UPnP server / friendly name / model）；未探测时显示 `(not probed)`；Identity Model 行从 `upnp_model` 回退到 `upnp_friendly_name` | `test_tui_helpers.py::test_lan_detail_shows_active_discovery_section_with_nbns`、`::test_lan_detail_shows_active_discovery_placeholder_when_nothing_probed`、`::test_lan_detail_identity_shows_model_when_upnp_model_set`、`::test_lan_detail_identity_falls_back_to_friendly_name_when_no_model`、`::test_lan_detail_identity_omits_model_when_neither_field_set` |
| `[new]` chip 灰度期：`first_seen` 落在 LAN poller `_constructed_at` 的 `_NEW_CHIP_GRACE_S` 窗口内时不触发 chip（初始 sweep 基线，不是真新）；之后加入的主机正常触发 | `test_tui_helpers.py::test_lan_row_new_chip_suppressed_for_initial_sweep_with_anchor`、`::test_lan_row_new_chip_still_fires_after_grace_with_anchor`、`::test_lan_row_new_chip_falls_back_to_old_behavior_without_anchor` |
| `LANInventoryUpdate` 每 tick 发射；`r` 触发 `force_now()` 立即扫描 | `test_lan.py::test_force_now_schedules_immediate_sweep`、`::test_update_carries_cap_prefix_and_subnet_capped_flags` |
| `LANInventoryPoller` 对新增非本机非网关 MAC 发 `LANHostSeenEvent`；同 MAC 换 IP 时在 merge 前发 `LANHostDHCPRotationEvent`；静默超过 `_HOST_LEFT_TIMEOUT_S` 时发 `LANHostLeftEvent`；本机 + 网关绝不发 seen | `test_lan.py::test_poller_emits_seen_on_new_non_self_non_gateway_mac`、`::test_poller_skips_seen_for_self_and_gateway`、`::test_poller_emits_dhcp_rotation_before_ip_update`、`::test_poller_emits_left_after_host_left_timeout`、`::test_poller_does_not_re_emit_seen_for_known_mac` |

### `link-health`

| Requirement | 测试 |
|---|---|
| 网关 ICMP，WAN 走 TCP/53 | `test_latency.py::test_ping_once_records_rtt`、`::test_parse_ping_time_ms_decimal`、`::test_parse_ping_time_ms_integer`（ICMP）；`::test_tcp_probe_records_rtt_on_successful_connect`、`::test_tcp_probe_loss_on_timeout`、`::test_tcp_probe_loss_on_connection_refused`（TCP） |
| 60s 滚动窗口、单调时钟剪枝 | `test_latency.py::test_aggregate_yields_median_loss_and_jitter`、`::test_aggregate_window_actually_drops_old_samples`、`::test_aggregate_loss_pct_in_zero_to_hundred_range`、`::test_aggregate_empty_returns_none_fields` |
| 网络切换 → probe 重置 | (gap — `NetworkChangeEvent` 已透出；reset 行为通过 DNS-refresh 测试 `test_dns_refresh_runs_on_cadence` 间接观察) |
| Loss-burst + latency-spike 事件 | `test_latency.py::test_detect_latency_spike_requires_both_thresholds`、`::test_detect_loss_burst_three_of_last_five`、`::test_detect_loss_burst_one_loss_does_not_fire` |
| WAN-only 故障与全断区分 | `test_latency.py::test_wan_skipped_reason_dns_eq_gateway`、`::test_wan_skipped_reason_no_dns` |

### `macos-helper`

| Requirement | 测试 |
|---|---|
| Helper 是 `.app`，cdhash 锚 TCC 授权 | (人工 — bundle 构建路径；用户安装时验证) |
| Helper 暴露离散子命令为唯一集成点 | `test_helper.py::test_has_ble_scan_subcommand_true_when_help_lists_it`、`::test_has_ble_scan_subcommand_false_for_pre_0_5_helper`、`::test_has_bluetooth_permission_true_on_zero_exit`、`::test_has_bluetooth_permission_false_on_unauthorized` |
| Wi-Fi 扫描 JSON 带显式 `schema` 整数 | `test_helper.py::test_scan_v2_returns_networks_and_iface_meta`、`::test_scan_v1_iface_string_yields_empty_meta`、`::test_scan_v3_parses_bss_load_and_station_count`、`::test_scan_v3_parses_802_11r_capability_flag` |
| BLE 扫描每条广播一行 JSON | `test_ble.py::test_malformed_line_skipped_subsequent_parsed`、`::test_mixed_stream_routes_each_line_to_correct_bucket` |
| 广播对象透传 CoreBluetooth 字段 | `test_ble.py::test_schema_4_raw_passthrough_fields_populate` |
| 已连接快照来自 IOBluetoothDevice（不是 CoreBluetooth） | `test_ble.py::test_connected_line_routes_to_connected_dict_only`、`::test_ble_scan_update_propagates_connected_through_poller` |
| Python 端可自动发现 helper | `test_helper.py::test_find_helper_env_override_wins`、`::test_find_helper_env_override_can_point_at_binary`、`::test_find_helper_returns_none_when_nothing_present`、`::test_bundle_path_extracts_app_dir`、`::test_bundle_path_none_for_loose_binary` |
| `find_helper()` 也能发现一行 installer 安装到 `~/Library/Application Support/diting/diting-tianer.app` 的 bundle；in-repo 开发构建优先级仍最高 | `test_helper.py::test_find_helper_picks_up_application_support_bundle`、`::test_find_helper_repo_dev_build_shadows_application_support` |
| TCC 拒绝时 helper exit 3 + stderr "bluetooth unauthorized" | `test_ble.py::test_permission_denied_via_subprocess_exit_code`、`test_helper.py::test_has_bluetooth_permission_false_on_unauthorized` |
| Helper bundle 用 diting logo 作为 AppIcon（Info.plist 声明 `CFBundleIconFile=AppIcon`，iconset 全套尺寸入库） | `test_helper.py::test_helper_bundle_declares_appicon_and_ships_iconset` |
| 安装期 helper 按定位 → 蓝牙 → 通知顺序请求权限（`HelperAppDelegate` 状态机） | （人工 — 构建后运行 `open helper/diting-tianer.app`，观察状态窗口上每次只显示一个 TCC 弹窗） |
| Helper 提供 `notify --title T --body B` 子命令，通过 `UNUserNotificationCenter` 以 bundle 身份发通知 | （人工 — `helper/diting-tianer.app/Contents/MacOS/diting-tianer notify --title test --body hi` 弹出带 diting logo 的横幅） |
| Helper 语言兜底走 `Bundle.preferredLocalizations.first`（不再走 `Locale.preferredLanguages.first`），与 macOS 挑 `.lproj` 的源头一致 | （review-enforced — `detectHelperLang` 的 Swift 代码） |
| `associate` 子命令：JSON 响应解析覆盖每一种 exit code / payload 组合（`ok=true`、`enterprise_unsupported`、`cancelled`、`auth_failed`、`ssid_not_found`、`unknown`），映射到 `AssociateResult` 数据类 | `test_helper_associate.py::test_associate_ok_zero_exit`、`::test_associate_ok_with_keychain_saved`、`::test_associate_enterprise_exits_5`、`::test_associate_cancelled_exits_6`、`::test_associate_auth_failed_exits_7`、`::test_associate_ssid_not_found_exits_8`、`::test_associate_malformed_json_falls_back_to_unknown`、`::test_associate_subprocess_oserror_returns_unknown`、`::test_associate_timeout_returns_unknown` |
| `associate` 拒绝 argv 上的 `--password`，exit 64（安全护栏）；密码只走 stdin | （人工 — Swift 端 `runAssociateAndExit` 的护栏；review-enforced） |
| `associate` 不调 `iface.disassociate()`，把 L2 断开窗口压到最小（沿用 `force_reroam` 的同一道理） | （review-enforced — Swift 中 `runAssociateAndExit` 仅调用 `associate(toNetwork:password:error:)`） |
| 无 Keychain 时弹原生 AppKit 密码 sheet；`NSSecureTextField` 由 helper bundle 渲染 | （人工 — `/tui-audit` 真机回归；首次加入网络场景） |
| 勾上"记住密码"后通过 `SecItemAdd` 把密码写到 login keychain 的 `com.chenchaoyi.diting.tianer` 服务命名空间，附 `SecAccessControlCreateWithFlags(..., .userPresence, ...)` ACL；回写失败不影响 join 本身成功 | （人工 — `/tui-audit` 真机回归；用 Keychain Access.app 验证条目的 Access Control 页要求 user-presence） |
| 读缓存路径：`SecItemCopyMatching` 在 diting 服务命名空间内查询发生在 `associate(...password:)` 之前；命中时直接调用 `associate(...password: <recovered>)`，**不再**对安全网络做一次 `associate(...password: nil)` 兜底 | （review-enforced — `main.swift` 中 `proceed(net:iface:)` 与 `attemptKeychainRead` 的实现） |
| 不查 `kSecAttrService = "AirPort"`（System keychain）—— 这条路在 PR #75 已确认不可用（每次读都弹 admin 密码，没有指纹路径） | `grep '"AirPort"' helper/Sources/diting-tianer/main.swift` 应只剩 `attemptKeychainWrite` 注释中说明"为什么不写到这里"的那一处 |
| 同一已保存 SSID 第二次按 `j` 时，弹的是 Touch ID / 登录密码框（**不是** admin 密码），通过认证后无感关联 | （人工 — `/tui-audit` 真机回归；首次加入、关闭并重开详情、再按 `j`） |
| 取消 Touch ID / 登录密码框时，helper 响应 JSON 携带 `keychain_read: "denied"`，缓存条目**不**被删除，流程跌落到 AppKit 密码 sheet | （人工 — `/tui-audit` 真机回归；取消系统弹框后观察密码 sheet 出现） |
| 缓存密码过期：associate 报 `auth_failed`，密码 sheet 弹出，重新提交时 `SecItemAdd` 返回 `errSecDuplicateItem`，`SecItemUpdate` 仅写 `kSecValueData`，保留原始 `.userPresence` ACL，下一次读仍只弹一次 Touch ID 而非重新授权 | （人工 — `/tui-audit` 真机回归；在 AP 处轮换密码后按 `j`；后续 join 应只弹一次 Touch ID） |
| `kSecUseOperationPrompt` 走 locale 派发（按 `LANG` / `LC_ALL` 决定 EN/ZH）；helper 侧文案为 `diting wants to join Wi-Fi "<SSID>"` / `diting 想要连接 Wi-Fi "<SSID>"` | （review-enforced — Swift 中 `keychainReadPrompt(ssid:)`；注意 macOS 部分版本可能仍按系统 locale 渲染对话框） |

### `mdns-scanning`

| Requirement | 测试 |
|---|---|
| `BonjourPoller` 只订阅白名单内的服务类型，绝不订阅 meta 类型 | `test_mdns.py::test_service_category_known_type_returns_friendly_name`、`::test_service_category_unknown_type_returns_none`、`::test_poller_subscribes_only_to_curated_list` |
| `BonjourDevice` 携带广播解析后的所有字段（service_type、name、host、port、addresses、txt、vendor、category、first/last_seen） | `test_mdns.py::test_poller_emits_snapshot_after_first_announce`、`::test_txt_decode_drops_non_utf8_values` |
| 厂商解析走 5 步链（TXT vendor → OUI → 主机名模式 → 服务类型 hint → 放弃） | `test_mdns.py::test_resolve_vendor_txt_field_wins`、`::test_resolve_vendor_hostname_pattern_falls_through_to_apple`、`::test_resolve_vendor_service_hint_catches_chromecast`、`::test_resolve_vendor_all_steps_abstain_returns_none` |
| 状态表在 `remove_service` 回调时清理，并以 TTL 兜底 | `test_mdns.py::test_poller_removes_on_remove_service_callback`、`::test_poller_ttl_fallback_when_no_remove_observed` |
| 缓存活性保活：每次 tick 时，state 里那些 service-instance 名仍在 `zc.cache` 中存活（有任一未过期记录）的条目都会被刷新 `last_seen=now`，避免 HomePod 这种「info 不变 → 不触发 update_service → 60 s 后被 TTL 误删」的陷阱 | `test_mdns.py::test_poller_cache_refresh_bumps_last_seen_for_alive_entry`、`::test_poller_cache_refresh_skips_when_only_expired_records`、`::test_poller_cache_refresh_skips_when_no_records` |
| TTL 兜底默认值从 60 s 上调到 300 s | `test_mdns.py::test_poller_ttl_default_is_five_minutes` |
| 每 30 s 对每个 state 条目发起一次主动 re-probe（fire-and-forget），让那些 announce TTL < 300 s 的设备记录不会从 zeroconf 缓存里老化掉；任何卡住的 probe 不允许阻塞 snapshot 输出 | `test_mdns.py::test_poller_active_probe_scheduled_per_state_entry_at_cadence`、`::test_poller_active_probe_does_not_block_snapshot_yield`、`::test_poller_active_probe_default_cadence_is_thirty_seconds` |
| `BonjourPanel` 渲染 vendor / name / services / age / id 列（无 RSSI / 信号条 / connected 分割） | `test_tui_smoke.py::test_view_toggle_cycles_wifi_ble_mdns_lan_wifi`、`tui_snapshot.py`（explore 模式真机回归） |
| 诊断面板在 mDNS 视图下渲染 Bonjour 侧汇总 | `test_tui_smoke.py::test_view_toggle_cycles_wifi_ble_mdns_lan_wifi` |
| `BonjourPoller.stop()` 会清理 zeroconf 后台线程 | `test_mdns.py::test_poller_stop_joins_background_thread` |
| `BonjourDevice.vendor_trace` 记录解析链中生效的那一步（`txt-vendor` / `oui` / `hostname-pattern` / `service-type-hint`；abstain 时两者都是 None） | `test_mdns.py::test_resolve_vendor_with_trace_records_txt_step`、`::test_resolve_vendor_with_trace_records_oui_step`、`::test_resolve_vendor_with_trace_records_hostname_step`、`::test_resolve_vendor_with_trace_records_service_hint_step`、`::test_resolve_vendor_with_trace_abstain_returns_none_pair` |
| `zeroconf` 懒加载——只要用户没离开 Wi-Fi 视图就不 import | `test_tui_smoke.py::test_app_constructs_bonjour_panel_lazily` |
| wifi → BLE 这一步就开始预热 Bonjour，使得第二次按 `n`（BLE → mDNS）不再卡顿 | `test_tui_smoke.py::test_bonjour_prewarms_on_first_wifi_to_ble_switch` |
| Bonjour 初始化跑在 worker 线程上（`asyncio.to_thread`），import 与 `Zeroconf()` socket 都不阻塞事件循环 | `test_mdns.py::test_start_browser_runs_on_worker_thread`, `test_tui_smoke.py::test_bonjour_prewarms_on_first_wifi_to_ble_switch` |
| consumer 任务异常退出时会清掉 `_mdns_poller`，下一次按 `n` 能重建 | `test_tui_smoke.py::test_bonjour_consumer_task_resets_poller_on_unexpected_error` |
| `BonjourPoller` 在 `add_service`（及 cache-warmup race 的 `update_service`）发 `BonjourServiceSeenEvent`；在 `remove_service` 与 TTL backstop 都发 `BonjourServiceLeftEvent`；active probe 不会重发 seen | `test_mdns.py::test_poller_emits_seen_on_add_service`、`::test_poller_emits_left_on_remove_service`、`::test_poller_emits_left_on_ttl_backstop`、`::test_poller_active_probe_refresh_does_not_re_emit_seen` |
| `BonjourPanel` 支持 `by-host` 排序模式，把同一 host 的多个服务折叠成一列逗号串；`s` 在 `service` → `by-host` → `service` 之间循环 | `test_tui_helpers.py::test_bonjour_panel_by_host_mode_folds_services_alphabetically`、`::test_bonjour_panel_s_key_cycles_modes`、`::test_bonjour_panel_by_host_truncates_long_services_with_ellipsis`；`tui_snapshot.py::bonjour_by_host_mode`（回归） |
| mDNS "Top vendors" 诊断行的未知厂商桶渲染为 `(unknown) N`，不再写成 `? N` | `test_tui_helpers.py::test_mdns_diagnostics_top_vendors_uses_unknown_label` |

### `roam-detection`

| Requirement | 测试 |
|---|---|
| 0–100 链路评分附理由 | `test_tui_helpers.py::test_link_score_rewards_stronger_cleaner_candidate` |
| 同名 SSID 候选必须 ≥ +10 dB 才浮出 | `test_tui_helpers.py::test_best_same_ssid_candidate_requires_meaningful_delta` |
| 浮出的候选带评分 + 按 c 提示 | `test_tui_helpers.py::test_score_line_reports_better_same_ssid_candidate` |
| 按 c 切换 Wi-Fi 关再开 | (人工 — `force_reroam()` 是 backend 特定的) |
| `_health_line` 与 `_link_score` 词汇一致 | (review-enforced — 约定；这条要拦的 bug 之前出过一次) |
| `WiFiPoller` 在每次 BSSID 切换观察到的 `Connection.ssid` 上填出 `previous_ssid` / `new_ssid` | `test_poller.py::test_roam_event_fills_ssid_from_connection_updates` |

### `tui-shell`

| Requirement | 测试 |
|---|---|
| 四个垂直堆叠面板，固定顺序；第三槽四态轮转 wifi/ble/mdns/lan | `test_tui_smoke.py::test_app_boots_and_quits`（App composes；面板存在隐含验证）、`::test_view_toggle_cycles_wifi_ble_mdns_lan_wifi` |
| 第三槽面板 border_title 始终显示四视图标签页，详情内容移到 border_subtitle | `test_tui_helpers.py::test_view_tabs_border_title_lists_all_four_views`、`::test_view_display_name_maps_internal_tokens_to_user_names`；`test_tui_smoke.py::test_panel_border_title_carries_tab_indicator` |
| LAN 视图在首次 `LANInventoryUpdate` 落地前渲染 `(正在扫描子网…)` 占位行；落地后渲染行表 | `test_tui_helpers.py::test_lan_panel_renders_sweeping_placeholder_before_first_snapshot`、`::test_lan_panel_renders_rows_after_first_snapshot`；`tui_snapshot.py::lan_view`（regression-only） |
| LAN 面板把 `is_self` 用 `★` 钉到顶，然后 `is_gateway` 同样带 `★`，余下按 IP 升序 | `test_tui_helpers.py::test_lan_panel_renders_self_and_gateway_pinned_to_top`、`::test_lan_panel_sorts_remaining_rows_by_ip_ascending` |
| LAN 面板对本地管理 MAC 行标 `(随机 MAC)` 替代厂商 | `test_tui_helpers.py::test_lan_panel_marks_random_mac_with_label` |
| LAN Diagnostics 摘要行带 hosts / named / 厂商未知计数 + 子网（被截断时带 `· 截自 /N` 注解）+ `上次扫描` 相对时间 | `test_tui_helpers.py::test_lan_diagnostics_renders_full_summary_line`、`::test_lan_diagnostics_annotates_capped_subnet_when_netmask_wider`、`::test_lan_diagnostics_omits_capped_annotation_when_full_subnet_swept` |
| LANDetailScreen 模态渲染 Identity / Network / Bonjour services / Activity 段；关键 `Esc` / `i` / `q` | `test_tui_helpers.py::test_lan_detail_modal_renders_all_sections` |
| LANDetailScreen Network 段在 `last_rtt_ms` 已知时新增 Latency 行；未知时该行省略 | `test_tui_helpers.py::test_lan_detail_modal_renders_latency_row_when_rtt_known`、`::test_lan_detail_modal_omits_latency_row_when_rtt_unknown` |
| LANDetailScreen Network 段始终渲染 Reachable 行：`此次扫描` / 相对时间 / `从未` | `test_tui_helpers.py::test_lan_detail_modal_renders_reachable_row_this_sweep`、`::test_lan_detail_modal_renders_reachable_row_with_relative_time_when_older`、`::test_lan_detail_modal_renders_never_when_never_reachable` |
| LANDetailScreen Bonjour services 段始终渲染；为空时显示 `（无 Bonjour 服务）` 占位 | `test_tui_helpers.py::test_lan_detail_modal_renders_bonjour_empty_state_when_no_services`、`::test_lan_detail_modal_renders_bonjour_services_when_present` |
| EventsScreen 过滤循环改为八桶：`all` / `roam` / `rf_stir` / `latency` / `link_state` / `ble` / `bonjour` / `lan`（按键 `0`-`7`）；HelpScreen 列出全部八个 | `test_tui_helpers.py::test_events_screen_filter_cycle_has_eight_buckets`、`::test_events_screen_filter_keys_map_to_buckets_in_order`；HelpScreen 文本 review-enforced |
| **v1.7.2** —— EventsScreen 弹窗把连续的 `BLEDeviceSeenEvent`（`(vendor, name_label)` 元组相同）折叠为一行带 `×N` 的群组；`name_label` 先走轮换标识守卫，所以不同的临时标识可以被折叠到同一 `(rotating ID)` 群组；遇到非 BLE 事件 或 `(vendor, name_label)` 变化即终止当前群组；过滤桶在折叠之前生效；磁盘上的 JSONL 日志不受影响 | `test_tui_helpers.py::test_events_screen_collapses_three_consecutive_identical_ble_seens`、`::test_events_screen_does_not_collapse_across_vendor_change`、`::test_events_screen_non_ble_event_breaks_the_grouping_run`、`::test_events_screen_collapses_rotating_id_label_across_different_identifiers`、`::test_events_screen_grouped_row_renders_arrow_to_latest_timestamp`、`::test_events_screen_jsonl_log_untouched_by_modal_grouping`、`::test_events_screen_filter_then_group_order_is_filter_first` |
| EventsPanel 渲染七种新事件类型，前缀标签 `[BLE]` / `[BJ]` / `[LAN]` 与每种事件的格式 | `test_tui_helpers.py::test_events_panel_renders_ble_device_seen_line`、`::test_events_panel_renders_ble_device_left_line_with_duration`、`::test_events_panel_renders_bonjour_service_seen_line`、`::test_events_panel_renders_bonjour_service_left_line_with_duration`、`::test_events_panel_renders_lan_host_seen_line`、`::test_events_panel_renders_lan_host_left_line_with_duration`、`::test_events_panel_renders_lan_dhcp_rotation_line` |
| **events-cascade-census-fold** —— `[BLE]` seen/left 标签走 BLE 列表的 name 级联（共享 resolver：helper name → `(rotating ID)` → `device_type` → `device_class` → 占位符）；占位符仅在 vendor+name+device_type+device_class+service_categories 全空时为 `(anonymous)`（与 `is_silent_device` 一致），否则为 `(unknown)` | `test_tui_helpers.py::test_format_ble_seen_uses_helper_name`、`::test_format_ble_seen_falls_back_to_device_type`、`::test_format_ble_seen_falls_back_to_device_class`、`::test_format_ble_seen_unknown_when_vendor_only`、`::test_format_ble_seen_anonymous_only_when_truly_silent`、`::test_format_ble_left_uses_cascade` |
| **events-cascade-census-fold** —— EventsScreen 把每段连续的 `at_launch=True` BLE seen 折叠成一行可选中的汇总 `session start · N devices already present (vendor ×count …)`（top-3 厂商分布 + 溢出）；Enter/`→` 切换展开/收起（默认收起）；`at_launch=False` 的 seen、所有 left、非 BLE 事件照常逐条渲染；折叠遵守 `[5] BLE` 过滤；JSONL 日志不受影响 | `test_tui_helpers.py::test_events_screen_folds_at_launch_census_into_summary_row`、`::test_events_screen_census_summary_vendor_breakdown_top3`、`::test_events_screen_expand_collapse_census_summary`、`::test_events_screen_mid_session_seen_not_folded`、`::test_events_screen_census_fold_respects_ble_filter`、`::test_events_screen_census_single_device_not_folded` |
| Diagnostics 内容跟随激活视图 | `test_tui_smoke.py::test_toggle_view_swaps_third_panel`、`::test_view_toggle_cycles_wifi_ble_mdns_lan_wifi`、`::test_diagnostics_renders_link_line_when_latency_data_available` |
| 模态压栈、Esc/同字母关 | `test_tui_smoke.py::test_help_modal_open_and_close`、`::test_help_modal_question_mark_to_close`、`::test_help_modal_renders_through_pilot_query`、`::test_pressing_h_is_a_no_op`、`::test_events_modal_open_and_close`；`tui_snapshot.py::events_modal`、`::help_modal`、`::basics_modal`、`::ble_detail_decoded`（regression） |
| Footer 是单一 GroupedFooter 三段 | (gap — 没有 footer 分组的单元测试；regression 捕获里可见) |
| 隐藏 binding 为高级用户存在 | `test_tui_smoke.py::test_pause_and_resume`、`::test_force_rescan_does_not_crash`、`::test_cycle_sort_modes`（绑定能触发）；footer 不显示隐藏 binding 是 review-enforced |
| Header 显示 title + 时钟；subtitle 反映实时状态 | `test_tui_smoke.py::test_brand_header_carries_live_title_and_subtitle` |
| 品牌雷达 mark（`docs/design/diting-design/assets/logo-mark.svg`）以 Unicode 半格字符在 header 中以品牌橙渲染 | `test_tui_smoke.py::test_brand_header_renders_logo_mark`；`tui_snapshot.py::wifi_main_en`（regression 捕获半格字符上 `fill: #fea62b` 的品牌橙样式） |
| App title 固定为 `diting v<版本>`（取自 importlib.metadata），运行版本号一眼可见 | `test_tui_smoke.py::test_app_title_carries_version` |
| Wi-Fi 事件行（漫游、RF 扰动）展示相关 SSID：previous_ssid == new_ssid 时单段 `SSID: <名>`；不同时 `SSID: <前> → <后>`；两侧均为 `None` 或 `""`（隐藏 SSID）时整段省略 | `test_tui_helpers.py::test_format_roam_event_includes_ssid_when_same_on_both_sides`、`::test_format_roam_event_renders_ssid_transition_when_different`、`::test_format_roam_event_omits_ssid_segment_when_both_none`、`::test_format_roam_event_omits_ssid_segment_for_hidden_ssid`、`::test_format_rf_stir_event_includes_ssid_when_present`、`::test_format_rf_stir_event_omits_ssid_segment_when_none` |
| 所有 list-style 视图面板共享同一套行选中 + 查看手势（`up` / `down`、`i` / `enter`、鼠标点击即查看；Esc / `i` / `q` 关 modal 不动选择）；如需偏离该手势必须改本 Requirement | `test_tui_smoke.py::test_wifi_inspect_opens_modal_on_first_press`、`::test_bonjour_inspect_opens_modal_on_first_press`（与既有的 BLE 覆盖 `tui_snapshot.py::ble_detail_decoded` 并列） |

### `wifi-detail-modal`

| Requirement | 测试 |
|---|---|
| Wi-Fi 行按 BSSID 选中；BSSID 被 TCC 屏蔽时回退到 `(ssid, channel)` 合成 key | `test_tui_smoke.py::test_wifi_selection_keyed_by_bssid_survives_resort`、`::test_wifi_selection_clears_when_target_drops_out`、`test_tui_helpers.py::test_scan_row_key_uses_bssid_when_available`、`::test_scan_row_key_falls_back_to_ssid_and_channel`、`::test_scan_row_key_handles_hidden_ssid` |
| 键盘 `up` / `down` / `enter` / `i` priority binding（Wi-Fi 视图外 no-op） | `test_tui_smoke.py::test_wifi_inspect_opens_modal_on_first_press` |
| 鼠标点击 → 一手选中+打开 modal | （人工；鼠标路径与键盘 `i` 共用 `_wifi_set_selected(inspect=True)` 入口） |
| Modal 渲染每个 `ScanResult` 字段，分成 Identity / Radio / Signal / Beacon IE / Activity 五段 | `test_tui_helpers.py::test_wifi_detail_renders_identity_radio_signal_activity_sections`、`::test_wifi_detail_renders_beacon_ie_when_present`、`::test_wifi_detail_omits_beacon_ie_when_all_fields_absent` |
| Signal history 段在 EnvironmentMonitor 有 ≥ 2 个 RSSI 样本时渲染 sparkline + σ 基线；否则省略 | `test_tui_helpers.py::test_wifi_detail_signal_history_omitted_when_no_env_monitor`、`::test_wifi_detail_signal_history_omitted_when_under_two_samples`、`::test_wifi_detail_signal_history_renders_sparkline_and_sigma` |
| Same physical AP 段通过 `NetworkInventory.is_same_ap` 列出同 AP 的兄弟无线电；只有自身一个 BSSID 时省略 | `test_tui_helpers.py::test_wifi_detail_siblings_omitted_when_singleton`、`::test_wifi_detail_siblings_renders_when_inv_groups_radios` |
| Roam history 段按 BSSID 过滤事件环，按时间倒序最多 10 条；无匹配事件时省略 | `test_tui_helpers.py::test_wifi_detail_roam_history_omitted_when_ring_empty`、`::test_wifi_detail_roam_history_renders_matching_events_newest_first` |
| Recommendation 段仅在被查看的行就是当前关联 BSSID 且 `_best_same_ssid_candidate` 找到更强候选时渲染 | `test_tui_helpers.py::test_wifi_detail_recommendation_omitted_when_not_associated`、`::test_wifi_detail_recommendation_renders_for_associated_row_with_better_candidate`、`::test_wifi_detail_recommendation_omitted_when_no_clearly_better` |
| BSSID 被 TCC 屏蔽时给出可读 hint 而不是静默 | `test_tui_helpers.py::test_wifi_detail_redacted_bssid_renders_tcc_hint_and_omits_vendor` |
| AP 名只来自 `aps.yaml`；无匹配时不出现 | `test_tui_helpers.py::test_wifi_detail_renders_ap_name_when_inventory_matches`、`::test_wifi_detail_omits_ap_name_row_when_inventory_misses` |
| Esc / `i` / `q` 关闭 modal 不动选择 | （review-enforced；binding 是声明式的） |
| detail modal 上 `j` 键打开 `JoinConfirmScreen`；binding 在 footer 文案中体现 | `test_tui_smoke.py::test_wifi_detail_j_opens_join_confirm`、`::test_wifi_detail_footer_documents_j_binding` |
| `JoinConfirmScreen` 每次都渲染"会断开窗口 ~2–5 秒、TCP 连接会被重置"的提示，默认焦点放在取消按钮 | `test_tui_smoke.py::test_join_confirm_renders_gap_warning`、`::test_join_confirm_default_focus_is_cancel` |
| 取消确认对话不会触发后端 `associate` 调用 | `test_tui_smoke.py::test_join_confirm_cancel_does_not_call_backend` |
| 确认后通过 worker 派发 `Backend.associate(ssid, bssid)`；按每种结果（`ok` / `auth_failed` / `cancelled` / `enterprise_unsupported` / `ssid_not_found` / `unknown`）发对应 severity 的 `notify()` | `test_tui_smoke.py::test_join_confirm_dispatches_associate_on_yes`、`::test_join_notify_severity_per_outcome` |
| `(joining…)` 标注：确认后到 ① 下一次 poll 命中目标 SSID、② helper 报失败、③ 10 秒超时 这三者最早一个出现前持续显示 | `test_tui_helpers.py::test_joining_annotation_renders_for_pending_ssid`、`::test_joining_annotation_clears_on_connection_match`、`::test_joining_annotation_clears_on_failure_event`、`::test_joining_annotation_clears_after_deadline` |
| 企业 / 802.1X 网络：footer 文案变为"`j`：企业网请用系统 Wi-Fi 菜单加入"；按 `j` 只发 notify、不弹确认对话 | `test_tui_smoke.py::test_wifi_detail_enterprise_footer_hint`、`::test_wifi_detail_enterprise_j_press_emits_notify_and_no_confirm` |

### `wifi-scanning`

| Requirement | 测试 |
|---|---|
| 扫描行带 RSSI / 信道 / 频段 / 加密 / BSSID | `test_helper.py::test_scan_v2_returns_networks_and_iface_meta`、`::test_scan_lowercases_bssid`、`::test_scan_zero_noise_and_zero_rssi_become_none` |
| 遮蔽扫描显示 `(redacted)` 占位符，不沉默 | `tui_snapshot.py::wifi_redacted`（regression-only）；`test_helper.py::test_scan_redacted_row_keeps_bssid_none`（数据通路） |
| Beacon IE 字段可选、可加 | `test_helper.py::test_scan_v2_keeps_ie_fields_none`、`::test_scan_v3_parses_bss_load_and_station_count`、`::test_scan_v3_parses_802_11r_capability_flag`、`::test_scan_v3_rejects_malformed_ie_values` |
| 尊重 CoreWLAN 限流（≥ 7s） | (gap — poller cadence 是配置项，没单测) |
| 哨兵 RSSI 行在到 panel 之前过滤 | `test_ble.py::test_rssi_unavailable_sentinel_filtered`、`::test_rssi_zero_or_positive_dbm_treated_as_invalid`（BLE 侧；`test_helper.py::test_scan_zero_noise_and_zero_rssi_become_none` Wi-Fi 侧） |
| CoreWLAN 漏掉的当前 BSSID 由 poller 合并进结果 | `test_tui_helpers.py::test_merge_current_prepends_when_scan_omits_associated_ap`、`::test_merge_current_replaces_when_scan_already_has_ap`、`::test_merge_current_no_op_when_disconnected`、`::test_merge_current_no_op_when_connection_has_no_bssid`、`::test_merge_current_case_insensitive_match` |
| 扫描结果按 BSSID 去重，相同 BSSID 多次出现时保留最强 RSSI 的行 | `test_helper.py::test_scan_dedup_by_bssid_keeps_strongest_rssi`、`::test_scan_dedup_preserves_insertion_order`、`::test_scan_dedup_skips_none_bssid_rows` |
| Tx Rate 空闲缓存：当 `transmitRate()` 返回 0 且仍在同一 AP 时回填上一次非零值 | `test_macos_backend.py::test_tx_rate_idle_cache_substitutes_on_zero_same_ap`、`::test_tx_rate_idle_cache_clears_on_bssid_change`、`::test_tx_rate_idle_flag_false_on_first_zero_with_no_history` |
| Connection 面板在 `tx_rate_idle=True` 时渲染 `（空闲）` 注解 | `test_tui_helpers.py::test_connection_panel_renders_tx_idle_annotation`、`::test_connection_panel_no_idle_annotation_when_flag_false` |
| Connection 面板在 `tx_rate_mbps > max_link_speed_mbps` 时隐藏 `Tx / Max` 行的 Max 半段（macOS 26 上 CoreWLAN 的 `maximumLinkSpeed()` 偶尔会返回过期 / 偏低的值；两个数都展示就成自相矛盾） | `test_tui_helpers.py::test_connection_panel_hides_max_when_tx_exceeds_it`、`::test_connection_panel_shows_both_when_max_ge_tx` |

---

## 3. 模块：`diting.network`

把 BSSID 解析为物理 AP 身份。这个模块出过两个真实生产 bug（同 OUI
内 prefix5 撞车；跨 OUI VAP 分配），所以匹配规则承担最重的测试权重。

**覆盖目标：**

- [x] 主规则 —— 前 5 个 octet 匹配 + 最后字节邻近度窗口
- [x] 次规则 —— octets 2..5 匹配 + 同窗口
- [x] 窗口阈值 8（不会跨距离过远的 AP 误命中）
- [x] `radio_overrides` 优先级
- [x] `is_same_ap` 在 OUI 变体之间、规则层级之间的对称性
- [x] `cluster_label` 的芯片位分组
- [x] `band_label` 的 channel→band 映射（2.4 / 5 / 未知）
- [x] `format_bssid` 在已知 / 未知 / None 别名下的渲染
- [x] `load_inventory` YAML 正常路径 + 异常路径

### 测试用例 — `tests/test_network.py`

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_resolve_primary_rule[...]`（10 行参数化） | 5 台用户 AP（4× AX51-E，1× AX60_2）的 2.4 GHz 无线电（mgmt + 1）和 5 GHz 无线电（mgmt + 4）都能解析到正确的 AP 名。 | 主规则在用户 H3C 部署上的完整证明。 |
| `test_resolve_three_aps_in_one_oui_do_not_collapse` | 三台 AP 共享 `40:fe:95:8a:3c:..` 前缀，仅最后 mgmt 字节不同（07 / 15 / 54）。每台 AP 的无线电都解析到*它自己*的名字，而不是全部回到第一台。 | 修复 prefix5 单独匹配整段 OUI、`resolve` 总返回列表第一项的 bug 的回归 —— 该 bug 把 B2 / 3F 无线电误标成 B1。 |
| `test_resolve_outside_window_returns_none` | 最后字节为 `0x40`，远在任意 mgmt MAC 的 +8 窗口外的 BSSID，**不**会被 prefix5 偶然相同的某台 AP 命中。 | 窗口阈值阻止主规则把无关 BSSID 拉进来。 |
| `test_resolve_secondary_rule_cross_oui[...]`（5 行参数化） | H3C 「内部」SSID 在 `44:fe:95:..`，但芯片序号位（位置 2..5）与 `40:fe:95:..` mgmt MAC 一致，所有变体都能解析。 | 次规则的证明。没有它，用户截图里的 `H3C_89C7DF_WIFI5` 会显示成陌生 AP。 |
| `test_resolve_unrelated_returns_none`（5 行参数化） | 邻居 AP（`82:48:3b:..`、`c2:91:7c:..` 等）以及 `None` 都不会命中清单条目。 | 防误命中 —— 邻居不能被显示成自家 AP。 |
| `test_radio_overrides_win_over_rule_match` | 一个本来会被主规则命中的 BSSID，被 `radio_overrides` 中的显式条目覆盖。 | 文档化 escape hatch 的优先级。对随机化无线电 MAC 的厂商至关重要。 |
| `test_radio_overrides_case_insensitive` | 小写 key 的 override 能命中大写 BSSID 查询。 | YAML 编辑器和厂商文档大小写混用，查询不应敏感。 |
| `test_is_same_ap_within_inventory` | 解析到同一 AP 名的两个 BSSID 返回 True；解析到不同 AP 名返回 False。 | 驱动漫游分类 —— 同 AP 切频段还是跨 AP 漫游。 |
| `test_is_same_ap_cross_oui_within_inventory` | 一个 40: BSSID 与一个 44: BSSID 解析到同一 AP，被认作同一 AP。 | 专门测试频段切换分类在 H3C 跨 OUI 布局下仍然成立。 |
| `test_is_same_ap_neither_in_inventory_falls_back_to_prefix` | 双方都不在清单里时，回落到 prefix5 / 中段 4 字节聚簇。 | 让漫游分类在没配 `aps.yaml` 的全新安装上也能工作。 |
| `test_is_same_ap_mismatch_when_one_resolves` | 即便前缀相同，一方解析到另一方解析不到，仍判为**不同** AP。 | 防止未加别名的邻居因为芯片前缀偶然一致就被合并到已知 AP。 |
| `test_band_label[...]`（9 行参数化） | 信道 1、6、14 → 2.4G；36、157、177 → 5G；15、200、None → None。 | 信道→频段映射的边界覆盖。驱动 `band` 列表头。 |
| `test_cluster_label_groups_chip` | 5 个跨 40: / 44: 前缀但共享 octets 3..5 的 BSSID 折叠到同一 `?XX:YY:ZZ` 标签。 | 自动发现把同芯片所有无线电分到一组，无需清单。 |
| `test_cluster_label_separates_unrelated` | 三台不同物理邻居 AP 各自获得独立聚簇标签。 | 防止「邻居全部看起来像同一 AP」。 |
| `test_cluster_label_none_or_malformed` | None → `?`；非 MAC 字符串 → `?`。 | 防御性：函数永不抛异常。 |
| `test_format_bssid_known_with_band` | 命中清单的 BSSID 渲染成 `<AP-name> (<band>) (<bssid>)`。 | Connection 面板显示的完整身份字符串。 |
| `test_format_bssid_unknown_passthrough` | 未命中别名的 BSSID 直接渲染为原始 MAC，不附加 `?` 前缀。 | 在用户只看到一台 AP 的位置避免出现混淆。 |
| `test_format_bssid_none` | None 渲染为字面值 `n/a`。 | 已断开或完全被遮蔽的状态。 |
| `test_load_inventory_missing_file_returns_empty` | `load_inventory(<missing>)` 返回空清单，而不是异常。 | 首次运行的 UX：没有 `aps.yaml` 应当友好。 |
| `test_load_inventory_well_formed` | 正确的 YAML（含 `aps:` 与 `radio_overrides:`）能 round-trip 到正确结构。 | 文档化 schema 的正常路径证明。 |
| `test_load_inventory_missing_keys_raises` | 只有 `name` 没有 `mgmt_mac` 的 AP 条目抛 `ValueError`。 | 编辑笔误必须显式失败，不能静默生成半配置清单。 |
| `test_load_inventory_top_level_must_be_mapping` | 顶层是 YAML 列表会抛 `ValueError`。 | 同样的「显式失败」契约。 |

---

## 4. 模块：`diting._helper`

承担与 Swift sidecar 的子进程协议。Wire format 向前兼容（helper 的
`schema` 字段），所以同时测 v1（`interface` 是字符串）与 v2（`interface`
是字典）两种形态。

**覆盖目标：**

- [x] JSON schema v1 ↔ v2 兼容
- [x] 身份字段隐藏处理（None vs 已填）
- [x] CWNetwork「0 表示无测量」哨兵的归一化
- [x] BSSID 大小写归一化
- [x] 健壮性：JSON 损坏、非零退出、超时
- [x] `has_permission` 启发式（任意一行 BSSID 已填即为已授权）
- [x] `bundle_path` 从二进制路径中提取
- [x] `find_helper` 搜索顺序对 `DITING_HELPER` 的尊重

### 测试用例 — `tests/test_helper.py`

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_scan_v2_returns_networks_and_iface_meta` | Schema v2 payload（interface 字典含 country / hardware）解析为 ScanResult 列表与非空 meta 字典。 | 当前 helper 输出的主用例。 |
| `test_scan_v1_iface_string_yields_empty_meta` | Schema v1 payload（interface 是普通字符串）网络解析正确，meta 字典为空而不是崩溃。 | 与 v2 schema 之前构建的旧 helper 兼容。运行 `uv run diting` 升级后旧的 `/Applications/diting-tianer.app` 仍能用。 |
| `test_scan_zero_noise_and_zero_rssi_become_none` | helper 输出的 noise / RSSI 为 `0` 在 Python 侧归一化为 `None`。 | CoreWLAN 用 `0` 表示「无测量」；原样透传会让面板显示「0 dBm」（看起来像满信号）。 |
| `test_scan_lowercases_bssid` | JSON 里的大写 BSSID 在 `ScanResult.bssid` 里变小写。 | 清单查询大小写不敏感的前提是数据在入口处归一化。 |
| `test_scan_redacted_row_keeps_bssid_none` | 缺 `ssid` / `bssid` 字段（helper 没拿到「定位」授权）的网络条目，ScanResult 两字段都是 None，其他字段保留。 | 没授权时 RSSI / 信道仍能透传；面板的「(redacted)」标签依赖这一形态。 |
| `test_scan_malformed_json_returns_empty` | stdout 是垃圾字符 → `([], {})`。 | helper 异常不能让 TUI 崩溃。 |
| `test_scan_nonzero_exit_returns_empty` | 非零退出码 → `([], {})`。 | 同上。Backend 会回落到直接 CoreWLAN。 |
| `test_scan_subprocess_timeout_returns_empty` | `subprocess.TimeoutExpired` → `([], {})`。 | 卡住的 helper 不能无限阻塞轮询。 |
| `test_has_permission_true_when_any_bssid_populated` | 至少一行 BSSID 已填 → `True`。 | 自动启动流程里的 liveness 探测。 |
| `test_has_permission_false_when_all_redacted` | 每行 BSSID 都是 None → `False`。 | 驱动首次启动时弹授权流程。 |
| `test_has_permission_false_on_subprocess_error` | OSError（helper 二进制不存在 / 不可执行）→ `False`。 | 防御性：未授权与 helper 缺失在此处不可区分。 |
| `test_bundle_path_extracts_app_dir` | 给定 `<bundle>.app/Contents/MacOS/binary` 内的路径，`bundle_path` 返回 `.app` 目录。 | 让自动启动流程仅凭找到的二进制就能 `open` 该 bundle（触发系统授权弹窗）。 |
| `test_bundle_path_none_for_loose_binary` | 不在任何 `.app` 内的二进制返回 None。 | 对限制如实告知 —— 没有 bundle 就没有 UI 可以触发。 |
| `test_find_helper_env_override_wins` | `DITING_HELPER` 指向 bundle 的 path 胜过任何标准安装位置。 | 文档化的覆盖优先级。 |
| `test_find_helper_env_override_can_point_at_binary` | 环境变量也可以直接指向可执行文件，而不只是 bundle。 | 开发循环便利。 |
| `test_find_helper_returns_none_when_nothing_present` | 环境变量指向不存在的路径 + `HOME` 重定向走 → `None`。 | 自动启动会 fall through 到构建路径。 |

---

## 5. 模块：`diting.tui`（helpers）

附近 AP 面板使用的纯数据变换。TUI 装配本身由第 6 节的冒烟测试覆盖。

**覆盖目标：**

- [x] `_merge_current` 在扫描漏掉当前 AP 时自动合成
- [x] `_merge_current` 在扫描已包含当前 AP 时替换，并保留
      Connection 侧权威值
- [x] `_merge_current` 在断开或 BSSID 未知时为 no-op
- [x] `_group_by_ap` 既能聚簇清单匹配，也能聚簇跨 OUI 变体
- [x] `_group_by_ap` 把用户当前所在的组浮到第 0 位
- [x] `_group_by_ap` 其余按最佳 RSSI 降序
- [x] `_group_by_ap` 组内按 RSSI 降序
- [x] `_group_by_ap` 把未加别名的行折叠到 cluster_label 下

### 测试用例 — `tests/test_tui_helpers.py`

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_merge_current_prepends_when_scan_omits_associated_ap` | CoreWLAN 扫描返回的是其他 AP 的行；当前 AP 作为 Connection 派生的合成行被前置插入。 | 最常见的生产场景 —— macOS 经常把已关联 AP 从扫描输出中漏掉。用户必须始终看到自己的行。 |
| `test_merge_current_replaces_when_scan_already_has_ap` | 扫描已经包含当前 AP，但 RSSI / 信道是旧值；合并后该 BSSID 只出现一次，并使用 Connection 侧的值。 | 避免面板对同一 BSSID 显示「ch 161 / -80」而 Connection 显示「ch 157 / -50」 —— DFS 跳频会让两份快照不同步。 |
| `test_merge_current_no_op_when_disconnected` | Connection 是 `None`；扫描列表原样返回。 | 已断开的状态不应该合成出一行幻影行。 |
| `test_merge_current_no_op_when_connection_has_no_bssid` | Connection 的 `bssid=None`（被完全遮蔽且无 helper）；扫描列表原样返回。 | 没有去重 key 时不能合成。 |
| `test_merge_current_case_insensitive_match` | Connection BSSID 小写、扫描 BSSID 大写 —— 去重仍然命中。 | 扫描有时来自 CoreWLAN 是大写，而 Connection 路径归一化为小写。 |
| `test_group_by_ap_clusters_inventory_matches` | 三个都解析到同一 AP 的 BSSID（含一个 44:* 跨 OUI 变体）形成一个三行的组。 | 证明分组使用与 UI 其他地方相同的 `resolve()` 路径。 |
| `test_group_by_ap_separates_distinct_aps` | 来自两台 AP 的两个 BSSID 进入两个组。 | sanity 检查。 |
| `test_group_by_ap_floats_current_to_first` | 一台弱信号 (-80) 的当前 AP 排在强邻居 (-30) 上方。 | 用户自己的 AP 必须能一眼找到，无视信号。 |
| `test_group_by_ap_otherwise_sorts_by_best_rssi` | 没有当前 AP 时，组按各自最强成员排序。 | 默认阅读顺序 = 「附近且强」。 |
| `test_group_by_ap_within_group_sorts_by_rssi_desc` | 同一 AP 桶内行强信号在前。 | 让用户能找到通向那台 AP 的最佳无线电。 |
| `test_group_by_ap_unaliased_uses_cluster_label` | 共享 octets 3..5 的两个 BSSID（如带两个 BSSID 的邻居）折叠到同一 `?XX:YY:ZZ` 聚簇 —— 该 key 以 `?` 开头，渲染时会用 dim 样式。 | 无清单分组 + 渲染样式契约。 |
| `test_group_by_ap_empty_input` | 空输入 → 空组列表。 | 防御性。 |

#### BLE 诊断辅助函数

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_ble_visible_line_counts_total_connectable_anonymous` | Visible BLE 行报告设备总数、可连接数、匿名数（无厂商 + 无名字）。 | 驱动 BLE 诊断面板的第一行。 |
| `test_ble_vendors_line_top_four_plus_unknown` | Vendors 行显示头四个厂商（按头数）外加 `? N` 尾巴标无厂商设备。 | 压缩长尾的同时不丢未知设备。 |
| `test_ble_categories_line_groups_by_service_category` | 多服务设备（Apple Watch 同时跑 HID 和心率）每个桶只计一次；无类别设备汇入「N 其他」。 | Categories 行必须如实反映人口分布。 |
| `test_ble_categories_line_includes_deep_id_types` | Categories 行把 schema-3 的 `type`（iBeacon、AirTag …）和 `device_class`（iPhone …）和 service-UUID 类别一起统计。 | iBeacon 不广告 service UUID；不算它就永远体现不出来。 |
| `test_ble_closest_line_picks_strongest_rssi` | Closest 行用名字 + 厂商标出 RSSI 最强的设备。 | 最快回答「我旁边有什么」。 |
| `test_ble_closest_line_falls_back_to_anonymous_label` | 最强设备没名字也没厂商时，行仍显示 RSSI，并贴 `(anonymous)` 标签。 | 对不知道的事情诚实，但不丢这一行。 |
| `test_ble_diagnostic_lines_returns_four_rows` | 不带 connected 时分发器返回 4 行。 | 布局不变量 —— 面板 min-height 按 4 行算；多一行就挤掉别的。 |
| `test_ble_diagnostic_lines_adds_connected_row_when_present` | 给 `connected` 非空时追加第五行总结已连接外设。 | v0.6.0 规范的「仅当有已连接外设时显示第五行」规则。 |
| `test_ble_label_summary_prefers_type_over_service_category` | 带 `type="AirTag"` 与 service `FD5A` 的设备显示为 `AirTag · Find My`。 | 「这是什么」标签领头；类别给上下文。 |
| `test_ble_label_summary_falls_back_to_service_category_when_no_type` | 无 type / device_class → 标签就是 service-UUID 类别。 | 非 Tier-1 设备的 v0.5.0 行为保持。 |
| `test_ble_label_summary_uses_device_class_when_no_type` | Apple Nearby Info 只给 `device_class`；摘要拿出 `iPhone` / `Mac` / `Apple Watch`。 | 替换 v0.5.0「Apple, Inc.（匿名）」体验。 |
| `test_ble_connected_line_counts_peripherals_and_categories` | Connected 诊断行报外设总数 + 每类别细分。 | 驱动「已连接  3 个外设 · 2 音频 · 1 HID」渲染。 |

---

## 5b. 模块：`diting.ble`

异步 BLE 扫描层。承担 JSONL 行解析、滚动设备表 TTL、轮换 UUID 模糊
合并、厂商查找、服务类别推断。Swift 辅助子进程通过 `BLEPoller(_spawn=...)`
测试钩子在 spawn 边界被 mock，套件在没有蓝牙硬件的 Linux CI runner
（以及没授权 helper 的 macOS runner）上都能跑。

**覆盖目标：**

- [x] JSONL 行解析 —— 每个广告字段都能正确填充 BLEDevice；后续广告
      会保留 `first_seen` 并自增 `ad_count`。
- [x] 厂商查找 —— Apple 公司 ID 能解析；未知 / None 输入友好处理。
- [x] 打包好的厂商 JSON 至少包含 Apple 一条 —— 防止 `make update-vendors`
      把文件写崩。
- [x] 服务类别推断 —— 已知 16-bit UUID 映射到可读名字；长格式
      （128-bit）能归一化；未知 UUID 原样透传。
- [x] 衰减 / TTL —— 超过 ttl_s 没看到的设备从快照里掉出去；ttl_s
      之内的保留。
- [x] 模糊合并 —— `(vendor_id, name)` 一致且 RSSI 在 ±10 dB 内折叠
      成一行，`ad_count` 求和、`merged_count` 记录数量；窗外条目
      保持独立；完全匿名（厂商和名字都为空）的设备永不合并。
- [x] 快照按 RSSI 降序排序。
- [x] 权限被拒绝 —— 既支持 JSON 错误行，也支持子进程退出码 3 ——
      都能干净地把 `permission_state` 翻成 `"denied"`。
- [x] 子进程崩溃 —— 不抛异常；后续快照保持稳定。
- [x] helper 二进制不存在 —— 状态翻成 `"unavailable"`，快照继续发出。
- [x] JSON 行损坏 —— 静默跳过；后续合法行正常解析。

### 测试用例 — `tests/test_ble.py`

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_parse_advertisement_populates_all_fields` | 一条合法 JSONL 事件能产出 BLEDevice，每字段填充正确，identifier 转小写。 | 主解析器证明 —— helper 输出的 wire format。 |
| `test_parse_subsequent_advertisement_carries_history` | 同一 identifier 的后续广告保留 `first_seen` 并自增 `ad_count`，`last_seen` 推进。 | 广告速率 / 持续时间驱动面板的「X 秒前」列与合并启发式稳定性。 |
| `test_lookup_vendor_known_company_id` | Apple 公司 ID 解析为 "Apple, Inc."。 | 最常见 BLE 厂商的 sanity 检查。 |
| `test_lookup_vendor_unknown_returns_none` | 未分配的公司 ID 返回 None。 | 让 renderer 回落到原始 ID 让用户自查。 |
| `test_lookup_vendor_none_input_returns_none` | 「无 manufacturer data」（最常见 BLE 状态）静默处理。 | 防御性 —— 函数永不抛异常。 |
| `test_load_vendors_ships_apple_id` | 打包的 JSON 包含 76 → "Apple, Inc."。 | 防止 `make update-vendors` 写出空 / 错误文件。 |
| `test_service_category_heart_rate` | `180D` → `"Heart Rate"`。 | 规范要求的类别映射。 |
| `test_service_category_hid` | `1812` → `"HID"`。 | 规范要求的类别映射。 |
| `test_service_category_unknown_passthrough` | 未知 UUID 原样返回。 | 对不知道的事情如实告知。 |
| `test_service_category_long_form_normalised` | `180D` 的 128-bit Bluetooth SIG 基础格式也能解析为 `"Heart Rate"`。 | macOS 两种格式都可能给，查找必须都命中。 |
| `test_expire_drops_unseen_devices` | `last_seen` 早于 `ttl_s` 的设备从快照里删除。 | 让面板不再囤积已经走掉的旧行。 |
| `test_expire_keeps_recent_devices` | `ttl_s` 之内看到的设备保留。 | 边界 sanity —— 只在过期时丢弃。 |
| `test_merge_folds_same_vendor_and_name_within_rssi_window` | 两条 `(vendor_id, name)` 一致、RSSI 在 ±10 dB 内的条目合并成一行；`ad_count` 求和，`merged_count = 2`。 | 模糊合并的主证明 —— 驱动 (合并 N) 徽章。 |
| `test_merge_keeps_distant_rssi_separate` | 标识相同但 RSSI 相差 > 10 dB 的两条保持独立。 | 极可能是不同房间的不同物理设备；合并就成了说谎。 |
| `test_merge_does_not_combine_anonymous_devices` | 厂商和名字都为空的设备永不合并。 | 否则会把附近所有匿名信标全部合到一起 —— 规范要求「绝不静默回退」。 |
| `test_merge_sorts_by_rssi_descending` | 合并后的列表按信号强度排序。 | 最近的设备永远在面板顶部。 |
| `test_permission_denied_line_surfaces_state` | 含 "unauthorized" 的 JSON 错误行让 `update_from_line` 返回 `"permission_denied"`。 | 驱动 BLE 面板「(需要蓝牙权限)」占位。 |
| `test_permission_denied_via_subprocess_exit_code` | helper 以退出码 3 结束 —— poller 把 `permission_state` 翻成 `"denied"`。 | 不论 helper 走哪条信号通道都得到一致结果。 |
| `test_subprocess_crash_does_not_raise` | helper 中途被 SIGKILL（137）后 poller 安静下来 —— 后续快照空，不抛异常。 | 系统蓝牙重启时的 SIGKILL 不能拖垮 TUI。 |
| `test_helper_binary_missing_marks_unavailable` | spawn 时抛 OSError 让状态翻成 `"unavailable"`；快照继续发。 | 首次启动、helper 还没构建 / 授权时的情形。 |
| `test_malformed_line_skipped_subsequent_parsed` | 垃圾行被跳过；下一条合法行能正常解析。 | helper 行损坏（编码异常、半截写入）不能卡死解析器。 |
| `test_line_without_id_field_skipped` | 缺 `id` 的 JSON 对象被跳过，不会抛异常。 | 防御 helper schema 漂移。 |
| `test_detect_ibeacon_from_apple_manufacturer_payload` | 以 `4c0002...` 起头的 Apple 厂商载荷通过 `detect_advertisement` 解析为 `type="iBeacon"`。 | 最常见 BLE 格式的 Tier-1 deep-ID。 |
| `test_detect_airtag_apple_type_0x12_with_find_my_service` | Apple 类型 `0x12` 带 owner-paired 长度的载荷被标为 `AirTag`；Find My service 进一步确认。 | 替换 v0.5.0 「Apple, Inc.（匿名）Find My」墙为可操作标签。 |
| `test_detect_find_my_target_short_payload` | 没有 AirTag 长度签名的短 Find My 广播（lost-mode 信标）退化为 `Find My target`。 | 识别格式但对子类型保持诚实。 |
| `test_detect_eddystone_url_from_helper_supplied_type` | 一行 schema-3 JSON 带 `type="Eddystone-URL"` 通过 `update_from_line` 传到 `BLEDevice.type`。 | helper 端通过 service-data 字节做检测；Python 端只负责传播。 |
| `test_detect_eddystone_generic_from_service_uuid_only` | 没有帧字节时，`service_uuids=["FEAA"]` 回落到通用 `Eddystone` 标签。 | 兼容路径；0.6.0 之后的 helper 会更细化。 |
| `test_detect_tile_from_feed_service_uuid` | Tile 信标广播 `FEED` 或 `FEEC` 解析为 `type="Tile"`。 | Tier-1 规范类别。 |
| `test_detect_smarttag_samsung_company_id_disambiguates_fd5a` | 仅 `FD5A` 有歧义（Apple Find My vs Samsung SmartTag）；Samsung 公司 ID `0x0075` 翻转为 SmartTag。 | 规范明确要求的去歧规则。 |
| `test_detect_swift_pair_microsoft_company_id_plus_leading_byte` | Microsoft 公司 ID `0x0006` + 首字节 `0x03` → `Swift Pair`。 | Tier-1 规范类别。 |
| `test_apple_nearby_info_device_class[iPhone,iPad,Mac,Apple TV,HomePod,Apple Watch]`（6 行参数化） | Apple 类型 `0x10`（Nearby Info）action 字节高 4 位映射到六种设备类别。 | 来自 `furiousMAC/continuity` 的逆向；回答「这台 Apple 设备是什么」。 |
| `test_connected_line_routes_to_connected_dict_only` | `{"connected": true, ...}` 行进入 connected dict，绝不进 advertising dict。 | 两段面板布局的洁净；混流会破坏布局。 |
| `test_connected_entries_skip_advertising_ttl` | `expire_devices` 只看 advertising dict；connected 条目不受时间影响。 | 不同来源不同生命周期。 |
| `test_connected_snapshot_sentinel_prunes_disappeared_entries` | 带新 `ids` 列表的 `connected_snapshot` 剪掉已不再连接的条目。 | 用户刚关掉的外设不能在面板里残留。 |
| `test_schema_2_json_back_compat_type_and_device_class_default_none` | schema-2 的 JSON 行（无 `type` / `device_class`）正常解析，两个字段默认 `None`。 | 刚升级 TUI 但还没重建 helper bundle 的状态保持可用。 |
| `test_mixed_stream_routes_each_line_to_correct_bucket` | advertising 与 connected 混流时，每行按到达顺序独立路由。 | helper 真实输出节奏下的路由正确性。 |
| `test_ble_scan_update_propagates_connected_through_poller` | poller 的快照循环输出的 `BLEScanUpdate.connected` 反映运行中的 connected dict。 | BLEPanel 读取此字段渲染 Connected 段。 |

---

## 5c. 模块：`diting.latency`

延迟探针轮询器。覆盖 ICMP 输出解析、尖峰 / 丢包风暴检测、滚动窗口
聚合，以及来自真实网络（家用 / 企业 / Cloudflare DoH /
多解析器 / 无 DNS / 空列表 / 数据畸形）的七种 DNS 自动检测形态。
所有 subprocess 调用与 SCDynamicStore 读取都在模块缝处 mock。

**覆盖目标：**

- [x] `_parse_ping_time_ms` 小数 / 整数 / `time<1.0` / 缺失
- [x] `LatencyPoller._ping_once` 成功记录 rtt
- [x] `_ping_once` 非零退出 / 没有 `time=` / subprocess 错误均记为
      丢失
- [x] `aggregate` 中位数 / 丢包% / MAD 抖动
- [x] `aggregate` 空窗口返回 None
- [x] `detect_latency_spike` 同时满足两阈值（200 ms 且超过中位数 5
      倍）
- [x] `detect_loss_burst` 5 中 3 规则
- [x] `LatencyPoller.stop`
- [x] DNS 自动检测：典型家用（DNS == 网关 → None）
- [x] DNS 自动检测：企业内网解析器
- [x] DNS 自动检测：Cloudflare DoH
- [x] DNS 自动检测：多解析器 + 网关排首位
- [x] DNS 自动检测：SCDynamicStore 返回 None
- [x] DNS 自动检测：ServerAddresses 为空
- [x] DNS 自动检测：数据畸形（None / int / object 条目）
- [x] `DITING_LATENCY_WAN_TARGET` 环境变量优先于自动检测
- [x] DNS 刷新节奏（注入时钟，不睡真表）
- [x] 显式 `wan_ip=` 完全禁用刷新
- [x] `wan_skipped_reason` 区分 `no_dns` 与 `dns_eq_gateway`
- [x] `_scutil_dns_fallback` 解析 resolver-#1 nameserver，遇到 #2
      停止

### 测试用例 — `tests/test_latency.py`

按上面每行一项，共 27 项。

---

## 5d. 模块：`diting.environment`

RF 扰动检测器。所有测试用确定时间戳的 RSSI 序列，让滚动窗口数学
完全可重现。

**覆盖目标：**

- [x] σ 越界触发 `RFStirEvent`
- [x] σ 没越界保持安静
- [x] 模式自动分类（co_located / spatial_channel / ignored）
- [x] 冗余融合：两个 co_located AP 同时跳变 → high
- [x] 单 AP 的 co_located 跳变 → medium
- [x] spatial-channel 事件标签为 AP 在 inventory 里的名字
- [x] 校准基线覆盖自适应
- [x] `baseline_summary()` 形态
- [x] -85 dBm 以下的 AP 不参与 σ 计算
- [x] `aggregate_sigma` 标签 `active` / `quiet` / `stable`
- [x] `write_calibration` / `load_calibration` 往返
- [x] `load_calibration` 找不到文件返回 `{}`

### 测试用例 — `tests/test_environment.py`

按上面每行一项，共 13 项。

---

## 6. TUI 冒烟

通过 Textual 的 `run_test` pilot 做端到端。fake backend 保证测试在
没有 Wi-Fi 的 CI runner 上和真 Mac 上行为一致。

**覆盖目标：**

- [x] App 能干净地 compose / unmount
- [x] 每个绑定（`q` / `p` / `r` / `s` / `c` / `?` / `n`）都不会抛异常；`h` 被特意置空（no-op）
- [x] Help 模态能通过 Esc 与再次按 `h` 关闭
- [x] Help 模态确实进入了 screen stack
- [x] `scan_interval` 构造参数能贯穿到 poller
- [x] `n` 在 Wi-Fi 扫描与 BLE 视图之间切换第三块面板；两个 widget
      始终 mount，只翻 `display`

### 测试用例 — `tests/test_tui_smoke.py`

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_app_boots_and_quits` | compose、mount、渲染一次、按 `q`、退出。 | App 已接好的最小证明 —— 防止单元测试抓不到的导入期 / mount 期错误。 |
| `test_pause_and_resume` | 连按两次 `p`。 | 暂停状态变化不会让恢复后的渲染崩溃。 |
| `test_force_rescan_does_not_crash` | 按 `r`。 | poller 的 `force_rescan` 路径能跑通。 |
| `test_cycle_sort_modes` | 连按两次 `s`。 | 两种排序都能渲染完成。与第 5 节 `_group_by_ap` 互相印证。 |
| `test_help_modal_open_and_close` | 按 `?`，再按 Esc。 | 回归 —— 早期版本曾在 Rich style 中误用 `bold $accent`（Textual CSS 变量），首次显示就崩。 |
| `test_help_modal_question_mark_to_close` | 按 `?` 打开，再按 `?` 关闭。 | 模态内的便利绑定。 |
| `test_help_modal_renders_through_pilot_query` | 打开模态后通过 `app.screen_stack` 断言恰好一个 HelpScreen 在栈上；关闭后断言为 0。 | 防止「绑定回调跑了但 widget 没真正 mount」的回归。 |
| `test_pressing_h_is_a_no_op` | 按 `h`，断言屏栈仍在主视图上。 | 锁住 `h` → `?` 的重绑；`h` 留给将来的视图内快捷键。 |
| `test_custom_scan_interval_threads_through` | 构造 `DitingApp(..., scan_interval=4.5)` 后检查 `app._poller._scan_interval`。 | `DITING_SCAN_INTERVAL` 环境变量最终落到这里；如果 kwarg 路径静默丢值，没人会发现。 |
| `test_toggle_view_swaps_third_panel` | 按 `n` 从 Wi-Fi 扫描视图切到 BLE 视图，再按一次切回。同时断言两个面板的 `display` 标志与 `app._view_mode`。 | 锁定规范的「原地切换」行为 —— 任一面板都不 unmount，两侧消费者状态都能在切换中保留。 |
| `test_ble_panel_renders_both_connected_and_advertising_sections` | 灌入 `_latest_ble`（advertising）与 `_latest_ble_connected`（connected），按 `n`，断言 BLEPanel 主体里同时出现 `Connected (1)` 与 `Advertising (1)` 两段标题以及各一行设备。 | v0.6.0 两段渲染的端到端证明 —— 这里坏掉就破坏了规范的第二个问题（「现在到底连着什么」）的答案。 |
| `test_events_modal_open_and_close` | 按 `m` 打开 EventsScreen，按 Esc 关闭。 | 锁定 v0.7.0 的模态绑定，方式与 `test_help_modal_open_and_close` 锁定 `h` 帮助绑定一致。 |
| `test_diagnostics_renders_link_line_when_latency_data_available` | 构造延迟聚合 + 一个环境元组，调用 `panel.update_environment(..., link=, env=)`，确认渲染主体里出现 `Link`、`gw 14 ms`、`Environment`、`stable`。 | 诊断面板必须能接住新元组而不是默默丢弃 —— 这是消费者与渲染器之间的 v0.7.0 契约守门员。 |
| `test_unified_events_panel_renders_roam_and_stir_interleaved` | 把一个 `RoamEvent` 与一个 `RFStirEvent` 推进统一面板；断言渲染输出里同时出现 `[ROAM]` 和 `[STIR]` 前缀加上 location 标签。 | 「漫游日志」改名为「事件」之所以可以，是因为两种事件类型都能透过同一个 widget 正确渲染。 |

---

## 7. 运行

```bash
uv run pytest                            # 全套
uv run pytest tests/test_network.py      # 单模块
uv run pytest -k "merge_current"         # 名字子串过滤
uv run pytest -v                         # 每条用例一行 PASSED
uv run pytest -x                         # 首个失败即停
uv run pytest --tb=long                  # 完整 traceback
uv run pytest --collect-only -q          # 只列用例不跑
```

CI 在 macos-latest × Python 3.11 / 3.12 / 3.13 上对每次 push 与 PR
跑 `uv run pytest`。见
[`.github/workflows/test.yml`](../../.github/workflows/test.yml)。

---

## 8. 新增测试

迭代 diting 的工作流：

1. **先改本文档。** 在合适的模块小节里加新行。用平实语言描述场景，
   并解释为什么重要（修了什么 bug？维护什么 UX 不变量？与哪个模块的
   契约？）。
2. **翻译成代码。** 在对应的 `tests/test_*.py` 文件里以同名 + 同
   docstring 实现。
3. **本地跑。** push 之前 `uv run pytest` 必须全绿。
4. **CI 跑同一份。** 推送 + 开 PR 会触发 `tests` workflow。

行为变更时：

1. 找出本文档中被该变更失效的行。
2. 更新行的「场景」/「为什么重要」以反映新行为。
3. 改测试代码。
4. 如果该变更修了一个新 bug，新增一行「regression」并附 bug 一句话
   描述。

删除 / 合并测试时：

- 在同一个 commit 里删除文档中的对应行。本文档存在的主要价值就是
  防止测试用例与文档的漂移。

---

## 9. 后续 / 推迟项

记录在此免得遗忘：

- **Live CoreWLAN 集成测试**，真正在真 Mac 上调
  `MacOSWiFiBackend.get_connection()` —— 用 `--live` 标志 gating，
  CI 跳过、开发者发版前手动 `uv run pytest --live`。
- **SCDynamicStore 解析器测试**，附带一份捕获的 bplist fixture
  （base64 编码，~5 KB），让 `_dynamic_store.py` 的信道 / BSSID
  抽取逻辑有回归网。
- **Helper Swift 冒烟**：在 CI 里跑 `swift build` + `bundle/MacOS/binary
  scan`，至少断言能输出一份空形状的 JSON 文档。
- **TUI 视觉快照**（Textual SVG 或文本）基于已知 fake backend ——
  渲染层重构时有用。
- **基于属性的测试**测 `_group_by_ap` 的不变量（对扫描顺序的
  associativity，无视 RSSI 把当前 AP 顶到第一）。

这些等到维护成本被实际缺口压下去再做。
