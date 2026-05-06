<sub>[English](../../CHANGELOG.md) · **中文**</sub>

# 版本变更记录

记录 wifiscope 的所有可见变更。格式参考
[Keep a Changelog](https://keepachangelog.com/)，版本号遵循
[Semantic Versioning](https://semver.org/)。`v0.x` 阶段允许破坏性的次要
行为变更。

## [Unreleased]

_暂无未发布的变更。_

## [0.4.0] — 2026-05-06

「也讲中文」版本。

### 新增
- **简体中文界面**。所有面板标题、底部提示、状态信息、诊断行、
  漫游日志标签、Help 模态各小节、Wi-Fi 基础知识模态条目都配了
  自然流畅的中文翻译，不是逐字直译。行业缩写（SSID / BSSID / RSSI /
  dBm / SNR / WPA2 / OPEN / ENT / MCS / NSS / Tx / Max）按设计在两种
  语言中都保留英文。
- **启动时一次性确定语言。** 新增 `--lang en|zh` CLI 参数和
  `WIFISCOPE_LANG` 环境变量；都不传时，wifiscope 会根据
  `LC_ALL` / `LC_MESSAGES` / `LANG` 自动嗅探（`zh_*` → 中文，其余 →
  英文）。
- **CJK 感知的列对齐。** 新增 `wifiscope.i18n.pad_cells` 与
  `fit_cells`，基于 `rich.cells.cell_len`，让 `1F-书房` 这类中文
  AP 名以及 `频段` 这类翻译表头按每个汉字 2 列处理，而不是按字节
  ljust。Connection 面板的标签与附近 BSSID 表头 / 单元格都改走
  这套工具。
- **每份文档的中文镜像** 放在 `docs/zh/` 下：`README.md`、
  `CHANGELOG.md`、`TESTING.md`、`HELPER.md`。每份英文原稿顶部都加了
  `English · 中文` 切换链接，中文版反向链回。
- **中文版预览 SVG** 位于 `docs/preview.zh.svg`，与英文版
  `preview.svg` 来自同一份 fake backend。重生成：
  `WIFISCOPE_LANG=zh uv run python docs/_capture_preview.py`。

### 变更
- **AP 别名文件默认路径** 从 `~/.config/wifiscope/aps.yaml` 改成
  `./aps.yaml`（相对当前目录解析）。对已经在 XDG 路径下配置过文件的
  用户是 breaking change；`WIFISCOPE_INVENTORY` 仍可覆盖，所以
  `export WIFISCOPE_INVENTORY=~/.config/wifiscope/aps.yaml` 即可
  保持旧行为。理由：大多数场景是从 clone 的仓库目录直接跑 wifiscope，
  CWD 相对路径让 `aps.yaml` 与 `aps.example.yaml` 同目录，省掉
  `mkdir -p ~/.config/wifiscope` 的繁琐步骤。`aps.yaml` 已加入
  `.gitignore`，避免误提交网络拓扑信息。
- README 的 AP 配置一节重写为 **AP 别名（可选）**，说明管理 MAC 从
  哪来（路由器 / 控制器管理 UI），并明确给出「企业网直接跳过」的
  指引。
- Help 模态的「可调参数」小节在原有 scan / 清单 / helper 覆盖项之后
  列出了 `WIFISCOPE_LANG=en|zh`。
- README 的「配置」环境变量表里新增一行 `WIFISCOPE_LANG`。

### 新增（开发工作流）
- 仓库根目录新增 **Makefile**，提供 `test` / `test-all` / `preview`
  / `preview-en` / `preview-zh` / `helper` / `help` 几个目标，把
  双语维护工作流（"UI 改动 → 重新生成两份 preview SVG"）从「记
  环境变量」简化成一条命令。
- README 新增 "维护中英双语 UI / 文档" 小节，把英中双语在三个层面
  （文案、文档、预览 SVG）的同步规则固化下来。

## [0.3.0] — 2026-05-06

「让密集 Wi-Fi 扫描变得可读」版本。

### 新增

- **诊断面板**，包含可见 BSSID 总数、频段分布、本次扫描隐藏数、
  无密码 BSSID 数、2.4 GHz 宽带 BSSID 警告、区码分布、当前信道上
  其他 BSSID 数、最空信道建议、当前链路健康度，以及一个简易
  漫游评分。
- **同名 SSID 候选漫游评分。** 现在会把当前 BSSID 与同名候选
  比较，并解释按 `c` 是否能让 Mac 重新漫游。
- **Wi-Fi 基础知识模态**，按 `b` 打开，用通俗语言解释 SSID、BSSID、
  AP 主机、RSSI、噪声 / SNR、频段、信道、带宽、加密、漫游、
  漫游评分等概念。
- **可滚动的附近 BSSID 面板**，办公室密集扫描场景下也能滚到
  终端可视区之外。
- **扫描行的安全徽章**，包括醒目的 `OPEN` 标记。
- **从 macOS 辅助进程扫描结果中解码安全字段。**

### 变更

- 附近扫描行的术语统一改为 **BSSID**，替换原先 AP / network 的混用。
- 扫描列表的 `ch` 列改名为 `channel`，`band` 周围的间距加宽。
- 诊断面板的措辞区分 **本次扫描隐藏** 与可见 BSSID 总数 ——
  隐藏 SSID 的 beacon 在不同 CoreWLAN 扫描快照中会出现 / 消失。
- 当推荐信道在当前扫描样本里听不到 AP 时，最空信道提示会显示
  `(no AP heard)`。

## [0.2.0] — 2026-05-06

「macOS 扫描列表不再被遮蔽，工具开始成熟」版本。

### 新增

- **Swift 辅助 sidecar**，位于 `helper/`。一个迷你的 Cocoa `.app`，
  唯一职责是持有 macOS「定位服务」权限，让 Python TUI 能读取扫描
  列表里每个 BSSID 的真实 SSID 和 BSSID。`wifiscope` 在首次启动时
  自动构建并 `open` 它；用户点 Allow 后窗口会在 1.5 秒后自动关闭。
  后续启动直接进 TUI。
- **`c` 绑定**：通过关再开 Wi-Fi 断开重连。比
  `disassociate()` 更干净（后者在 802.1X 企业网络上不可靠）：
  off/on 的路径会触发完整 auto-join 并复用 Keychain 凭据。
- **`s` 绑定**：在「按 AP」（默认；每个 BSSID 折叠到所属物理 AP
  并附一行群摘要）与「按信号」（按 RSSI 平铺）之间切换。
- **`h` 绑定**：打开 HelpScreen 模态，文档化工具、各面板、所有
  绑定、清单格式、辅助进程。
- **AP 清单模型** 重构到 AP 级条目：`aps` 数组带 `name` + `mgmt_mac`，
  以及可选的 `radio_overrides` 映射。解析有两条规则：前 5 个 octet
  匹配 + 最后字节窗口（解决 H3C 控制器把相邻 AP 分到同一 OUI 段
  的情形）、octets 2..5 匹配（覆盖厂商把相邻 OUI 分给同芯片不同用途
  的情形，如 H3C `40:` 与 `44:`）。
- **自动发现的聚簇标签**（`?XX:YY:ZZ`）—— 即便没有清单文件，同芯片
  的所有无线电也会折叠在同一标签下。
- **Connection 面板**新增 MCS 索引、NSS、`This Mac`（网卡 MAC）、
  区码、IP / Router，以及 `Tx 与 Max` 的脚注。
- **每行信号条** 在附近 AP 面板，配色与 Connection 面板的绿 / 黄 /
  红一致。
- **扫描列表里合成当前 AP 行**：CoreWLAN 扫描忽略已关联 AP 时，
  顶部会显示用户自己的行（带 ★ 与反色背景）。
- **隐藏网络标记**：空 SSID 的 beacon 渲染为 `(hidden)`，不再是
  `(no SSID)`。
- **`WIFISCOPE_SCAN_INTERVAL` 环境变量**，覆盖默认 7 秒扫描间隔
  （最小 3）。
- **`tests/` 测试套件**，83 个用例（58 个函数，部分参数化），覆盖
  清单解析、辅助 JSON 解析、TUI 合并 / 分组工具，以及一次跑遍所有
  绑定的 headless 冒烟。[`tests/TESTING.md`](TESTING.md) 是 canonical
  测试计划 —— 每个自动化用例都在那份文档里有一行，改场景请先改文档。
- **GitHub Actions CI**：每次 push 与 PR 都在 macOS-latest 上跑
  pytest，覆盖 Python 3.11 / 3.12 / 3.13。
- **`CHANGELOG.md`**（本文件）以及 README 中的 CI / release / license
  徽章。
- **以用户为中心的 README**：开篇 hero 截图，问题陈述前置，技术设计
  说明放后面。logo 与确定性的 TUI 预览 SVG 在 `docs/`。

### 变更

- 扫描列表 `AP` 列改名为 `AP host`。原标题与右侧 `BSSID` 列含义
  混淆（`BSSID` 也是一个 AP 标识）；新标题明确指物理 AP 设备。
- 默认排序改为「按 AP」。在密集的企业扫描场景下，分组视图更可读。
- 默认扫描间隔上调到 7 秒。CoreWLAN 实测限流约 5 秒，低于这一值时
  每隔一次返回空扫描（面板会显示上次成功的列表，不可见，但纯属浪费）。
- 信道解析改读 SCDynamicStore 顶层 `CHANNEL` 字段（OS 视角下
  无线电的当前关联信道），不存在时再回落到 `CachedScanRecord.CHANNEL`。
  这修复了 wifiscope 显示的是无线电「扫描中跳频」目标，而 macOS 原生
  Wi-Fi 面板显示的是 AP 实际工作信道的不一致。

### 修复

- 三个共享 `40:fe:95:8a:3c:..` 前缀的 AP 之前会全部映射到清单第一项。
  最后字节邻近度规则解决了误识别。
- `(redacted)` 行视觉上与 `(hidden)` 以及空 SSID 的真实 AP 区分开。
- Connection 面板的 `Tx` 与 `Max` 不一致问题改成在脚注里解释，
  而不是隐藏。
- Footer 绑定提示不会再被 attribution bar 抢走。

### 删除

- 旧的 `aliases.yaml` 扁平 BSSID-to-name 格式。被上文的 AP 级清单
  取代；迁移说明在 README 与帮助页里。

## [0.1.0] — 2026-05-05

首个版本。仅支持 macOS 的 TUI，三面板（Connection、Nearby APs、
Roam log），通过扁平的 `aliases.yaml` 提供 AP 别名，借助
SCDynamicStore 旁路在 CoreWLAN 完全被「定位服务」拒绝的情况下也能
读到*当前*关联的真实 SSID 与 BSSID。本版扫描列表的标识仍被遮蔽；
v0.2 的辅助进程是真正的修复。

完整变更见
[v0.1.0 release notes](https://github.com/chenchaoyi/wifiscope/releases/tag/v0.1.0)。
