<sub>[English](../../tests/TESTING.md) · **中文**</sub>

# 测试设计

本文档是 wifiscope 的 **canonical 测试计划**，与测试代码一起放在
`tests/` 目录。它描述测什么、为什么测，以及作为自动化用例的具体场景。
该目录的测试**必须与本文档保持一致** —— 调整 / 新增场景请先改这份
文档，再翻译成 Python 代码。

评审 PR 时请先读它；代码应当与文档一一对应。

---

## 1. 范围

### 在范围内

- **决定 wifiscope 显示什么的纯逻辑变换**：AP 解析、信号频段标签、
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
| 单元 | `tests/test_network.py`、`test_helper.py`、`test_tui_helpers.py`、`test_ble.py`、`test_i18n.py` | 每个纯函数在其全部输入空间内表现符合规约，包括来自真实 bug 的回归用例。 |
| 冒烟 | `tests/test_tui_smoke.py` | Textual App 能被 compose、mount、走完每个绑定（含新增的 `n` 视图切换）、unmount，全程不抛异常。使用一个返回确定数据的 `_FakeBackend`。 |

---

## 3. 模块：`wifiscope.network`

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

## 4. 模块：`wifiscope._helper`

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
- [x] `find_helper` 搜索顺序对 `WIFISCOPE_HELPER` 的尊重

### 测试用例 — `tests/test_helper.py`

| 测试 | 场景 | 为什么重要 |
|---|---|---|
| `test_scan_v2_returns_networks_and_iface_meta` | Schema v2 payload（interface 字典含 country / hardware）解析为 ScanResult 列表与非空 meta 字典。 | 当前 helper 输出的主用例。 |
| `test_scan_v1_iface_string_yields_empty_meta` | Schema v1 payload（interface 是普通字符串）网络解析正确，meta 字典为空而不是崩溃。 | 与 v2 schema 之前构建的旧 helper 兼容。运行 `uv run wifiscope` 升级后旧的 `/Applications/wifiscope-helper.app` 仍能用。 |
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
| `test_find_helper_env_override_wins` | `WIFISCOPE_HELPER` 指向 bundle 的 path 胜过任何标准安装位置。 | 文档化的覆盖优先级。 |
| `test_find_helper_env_override_can_point_at_binary` | 环境变量也可以直接指向可执行文件，而不只是 bundle。 | 开发循环便利。 |
| `test_find_helper_returns_none_when_nothing_present` | 环境变量指向不存在的路径 + `HOME` 重定向走 → `None`。 | 自动启动会 fall through 到构建路径。 |

---

## 5. 模块：`wifiscope.tui`（helpers）

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

---

## 5b. 模块：`wifiscope.ble`

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

---

## 6. TUI 冒烟

通过 Textual 的 `run_test` pilot 做端到端。fake backend 保证测试在
没有 Wi-Fi 的 CI runner 上和真 Mac 上行为一致。

**覆盖目标：**

- [x] App 能干净地 compose / unmount
- [x] 每个绑定（`q` / `p` / `r` / `s` / `c` / `h` / `n`）都不会抛异常
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
| `test_help_modal_open_and_close` | 按 `h`，再按 Esc。 | 回归 —— 早期版本曾在 Rich style 中误用 `bold $accent`（Textual CSS 变量），首次显示就崩。 |
| `test_help_modal_h_to_close` | 按 `h` 打开，再按 `h` 关闭。 | 模态内的便利绑定。 |
| `test_help_modal_renders_through_pilot_query` | 打开模态后通过 `app.screen_stack` 断言恰好一个 HelpScreen 在栈上；关闭后断言为 0。 | 防止「绑定回调跑了但 widget 没真正 mount」的回归。 |
| `test_custom_scan_interval_threads_through` | 构造 `WifiScopeApp(..., scan_interval=4.5)` 后检查 `app._poller._scan_interval`。 | `WIFISCOPE_SCAN_INTERVAL` 环境变量最终落到这里；如果 kwarg 路径静默丢值，没人会发现。 |
| `test_toggle_view_swaps_third_panel` | 按 `n` 从 Wi-Fi 扫描视图切到 BLE 视图，再按一次切回。同时断言两个面板的 `display` 标志与 `app._view_mode`。 | 锁定规范的「原地切换」行为 —— 任一面板都不 unmount，两侧消费者状态都能在切换中保留。 |

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

迭代 wifiscope 的工作流：

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
