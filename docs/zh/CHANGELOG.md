<sub>[English](../../CHANGELOG.md) · **中文**</sub>

# 版本变更记录

记录 diting（之前叫 `wifiscope` —— 见 [Unreleased] 里的破坏性变更条目）
的所有可见变更。格式参考
[Keep a Changelog](https://keepachangelog.com/)，版本号遵循
[Semantic Versioning](https://semver.org/)。`v0.x` 阶段允许破坏性的次要
行为变更。

## [1.0.4] — 2026-05-13

用户反馈 macOS TCC 权限弹窗不一致：定位权限弹窗显示「谛听 · 天耳」
（中文显示名），蓝牙权限弹窗显示「diting-tianer.app」（裸 bundle
文件名）；而且两个弹窗的正文都永远是英文，中文用户看不到中文描
述。本质上 macOS 给不同类别的 TCC 弹窗取标题字段的来源不一样
（定位用 `CFBundleDisplayName`，蓝牙用 bundle URL filename），
弹窗正文则直接来自 usage description 字段。

### 修复
- **TCC 弹窗在各语言下保持一致**。Helper bundle 新增
  `Resources/en.lproj/InfoPlist.strings` 与
  `Resources/zh-Hans.lproj/InfoPlist.strings`，按当前 locale 提供
  `CFBundleDisplayName` / `CFBundleName` 以及三个 usage description
  字段（`NSLocationUsageDescription`、
  `NSLocationWhenInUseUsageDescription`、
  `NSBluetoothAlwaysUsageDescription`）。zh 用户现在在「定位」和
  「蓝牙」两个弹窗里都看到中文标题和中文正文。Info.plist 新增
  `CFBundleLocalizations` 列出两种语言，老版本 macOS 不自动扫
  lproj 目录也能找到对应翻译。`helper/build.sh` 已经把
  `Resources/*.lproj` 整棵树拷进打包好的 .app。
- **`Info.plist` 顶层 `CFBundleName` / `CFBundleDisplayName` 统一**。
  两个 key 现在都默认是 `diting · tianer`（英文兜底）；先前
  `CFBundleName` 是 `diting-tianer`，`CFBundleDisplayName` 是
  `谛听 · 天耳` —— 正是这种分裂导致了上面那种语言不一致的 TCC
  弹窗组合。

## [1.0.3] — 2026-05-13

第一个真正可被最终用户装出来的 release。装出来之后 `diting` 一直卡
在「需要以下权限：定位服务」，原因是 helper 的 `scan` 子命令即使在
用户点了 Allow 之后，依然返回被 TCC 屏蔽的 BSSID/SSID。同时修了两
个 helper 弹窗的小 UX 问题。

### 修复
- **install.sh 安装路径下 Wi-Fi 扫描真正解除 TCC 屏蔽**。两个并行的
  问题让 BSSID / SSID 都是 `null`：
  1. helper 的 `scan` 子命令继承了 terminal 父进程的 responsibility，
     tccd 把 Location 请求算到 Terminal 头上（Terminal 没有
     `NSLocationUsageDescription`），CWNetwork 直接静默屏蔽
     ssid / bssid。BLE 路径自 v0.5.0 起就用
     `responsibility_spawnattrs_setdisclaim` 重启自己来打断这条
     继承；`scan` 现在做同样的 hop。
  2. macOS 14.4+ / 26 要求**当前进程**在 `scanForNetworks` 调用
     的瞬间有活动的 `CLLocationManager`，bundle 的 TCC 授权只是必
     要条件不是充分条件。`scan` 子命令现在在调 CoreWLAN 之前先
     `CLLocationManager` + `startUpdatingLocation()`，跟 GUI bundle
     一直在做的同。
  代码里原来注释说 CoreLocation 比 CoreBluetooth「宽松」是错的——
  本地验证两个修复同时上之后，BSSID / SSID / Beacon IE 数据如期
  流出。

### 变更
- **helper 弹窗本地化**。`DITING_LANG=zh`（Python 启动器通过
  `open --env` 传过来）或 macOS 的 `Locale.preferredLanguages` 以
  `zh` 开头时，弹窗切到中文：标题改为「diting 天耳」，正文 / 状态
  行也都翻译过来。中文 locale 用户跑 install.sh 时弹的第一个窗也
  自动是中文。
- **弹窗自动关闭从 1.5 s 改到 4 s**。多位用户反馈「全部权限已授予」
  闪一下就消失，看不清；4 s 既够看完，又不至于让人觉得磨蹭。Python
  启动器的轮询不依赖窗口停留时长，授权一落地立刻被识别。

## [1.0.2] — 2026-05-13

第二个针对 v1.0.0 发布流水线的热修复。v1.0.1 解开了 Swift helper 构建
那一卡，分架构 tarball 那一步又卡在另外两个问题上：

1. `scripts/package_release.sh` 调 `tar` 时带了 GNU-only 标志
   （`--owner=0 --group=0 --numeric-owner`），macOS bsdtar 直接拒绝。
   我为 `--no-mac-metadata` 写的回退分支也带着这些 GNU 标志，所以
   tarball 那一步在托管 runner 上就死了。
2. PyInstaller 冻结后的 binary 首次运行就崩在
   `ImportError: attempted relative import with no known parent
   package`。PyInstaller 把 `cli.py` 当顶层脚本编译，丢掉了模块自身
   `from .x import y` 依赖的 `diting` 包上下文。

装了 v1.0.0 / v1.0.1 的最终用户应该装 v1.0.2 —— 那两个 tag 都没产出
可消费的发布产物。`install.sh` 默认解析最新 tag，所以 curl 一行会自
动取 v1.0.2。

### 修复
- **Tarball 在 macOS bsdtar 上能正常打**。从
  `scripts/package_release.sh` 里去掉 GNU-only 的
  `--owner=0 --group=0 --numeric-owner`，纯 `tar -czf` 哪里都能跑。
  原本想要的 tarball 可复现（uid/gid 头一致）只是 nice-to-have，
  不是关键 —— SHASUMS256.txt 的 SHA256 才是真正的完整性保证。
- **冻结 binary 保留包上下文**。新增
  `scripts/frozen_entry.py` stub，里面只 import `diting.cli:main`
  并调用；PyInstaller 现在编译这个 stub（外加 `--paths src`），
  而不是直接编译 `cli.py`。diting 包内部的相对 import 运行时能正
  常 resolve。

## [1.0.1] — 2026-05-13

v1.0.0 发布流水线的热修复。Swift helper 源码里一个函数调用参数列表的
尾随逗号是 Swift 6.1 才支持的语法，本机较新的 Xcode 接受，但托管
`macos-14` runner 上的旧 Swift 工具链拒绝。v1.0.0 的 release workflow
卡在 `Build Swift helper` 这一步，没产出 tarball，GitHub Release 上
没有 asset，curl-bash 一行就 404。

v1.0.0 没有可消费的发布产物；终端用户应该安装 v1.0.1。`install.sh`
默认解析最新 tag，所以 `curl … | bash` 会自动取 v1.0.1，不用加参数。

### 修复
- **Swift helper 在托管 CI runner 上能正常构建**。删掉
  `helper/Sources/diting-tianer/main.swift` 里 Find My / AirTag 检
  测分支的尾随逗号，helper 在 Swift 5.x 与 6.x 上都能编译。

## [1.0.0] — 2026-05-13

**「直接 diting 就能用」版**。安装门槛从「clone 仓库、装 uv、编 Swift
helper、跑 uv sync」降到一行 curl-bash —— 装出来的是自包含二进制 +
helper bundle，用户机器上不再需要 Python、`uv` 或 Xcode 命令行工具。
TUI 这一版也补齐最后一块拼图：三块列表面板（Wi-Fi / BLE / Bonjour）
共享同一套行选中手势，每块都有自己的详情 modal，按 ↑ / ↓ 时 modal 跟
着光标走，不用关再开。

### 新增
- **一行 installer**：`curl -fsSL
  https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh
  | bash`。识别架构（`darwin-arm64` / `darwin-x86_64`），从 GitHub
  Release 拉对应 tarball，校验 SHA256，解压到 `~/.local/share/diting/`，
  symlink `~/.local/bin/diting`，把 Swift helper 拷贝到
  `~/Library/Application Support/diting/`，剥离 quarantine xattr，
  `open -g` 一次触发 TCC 授权弹窗。`~/.local/bin` 不在 PATH 时按
  zsh / bash / fish 打印对应的 PATH 更新提示。`DITING_VERSION=vX.Y.Z`
  环境变量锁版本。
- **PyInstaller 发布流水线**。新 GitHub Actions workflow
  (`.github/workflows/release.yml`)，`v*` tag 推送触发；`macos-14`
  arm64 + `macos-13` x86_64 matrix 构建 helper、用 PyInstaller 冻结
  Python 解释器 + 依赖、打 tarball、上传到 GitHub Release。后续 job
  把两边的 `.sha256` 汇总成 `SHASUMS256.txt`。
- **Wi-Fi 详情 modal**（在任意扫描行按 `i` / `Enter` 或鼠标点击）。
  身份段（SSID / BSSID / 来自 `aps.yaml` 的 AP 名 / OUI 厂商 /
  「当前连接」标注），射频段（信道 / 频段 / 带宽 / PHY / 加密），
  信号段（RSSI / 噪声 / SNR），Beacon IE 段（BSS 负载、终端数、
  802.11r/k/v 支持 —— 全部缺失时整段省略），活动段。BSSID 被 TCC
  屏蔽时给出可操作的提示，不再静默。
- **Bonjour 详情 modal**（同一手势移植到 mDNS 面板）。身份段（实例 /
  服务类型 / i18n 类别 / 厂商），网络段（host / port / IPv4 + IPv6
  地址分行），TXT 记录段对 > 60 字符的值自动折叠（`<N-byte payload>`
  + 前 16 字节 hex 预览，避免 30+ TXT key 的 AirPlay 接收器把 modal
  撑爆），活动段。
- **任意详情 modal 内的实时导航**。modal 打开后按 ↑ / ↓ 既移动底下面
  板的选中，又重渲 modal 内容跟到新行。不用关再开就能扫一遍 AP / BLE
  设备 / Bonjour 服务。BLE modal 还会按设备拉一次 RSSI 历史，sparkline
  跟着切换。

### 变更
- **三个列表视图统一行选中手势**。BLE 自 v0.7 起就有的 ↑ / ↓ / `i`
  / `Enter` / 鼠标点击合约现在 Wi-Fi 与 Bonjour 也按。每个面板的方
  向键 action 都按视图门控，同一物理键在不同视图下安全。规则落到
  `openspec/specs/tui-shell/spec.md`，未来新加列表面板默认继承。
- **`find_helper()` 搜索顺序增加第 5 个候选**：`~/Library/Application
  Support/diting/diting-tianer.app`，即 curl-bash installer 落地的位
  置。in-repo 开发构建仍排在最前，确保贡献者跑 `uv run diting` 永远
  拿到刚 `make helper` 出来的 bundle。
- **README** 开头改成一行 installer；原 `git clone` + `uv sync` +
  `make helper` 流程移到「从源码安装（贡献者）」二级标题下，原封保
  留。两条路径同机共存。

### 修复
- **TCC 屏蔽扫描时 Wi-Fi 选中健码退化无冲突**。BSSID 为 `None` 时
  选中键退化为 `f"{ssid}#{channel}"`，未授定位的用户仍可上下导航。
  同名 SSID 同信道的冲突边界条件已记录在 spec 里。
- **关 modal 不动选中**。`Esc` / `i` / `q` 关任意详情 modal 都不清
  除面板高亮，重新打开还回到同一行。

### 维护备注
- **`docs/RELEASE.md`**（+ `docs/zh/RELEASE.md` 镜像）—— 发版 runbook：
  版本号 bump、打 tag、盯 workflow、人工冒烟、GitHub Release 文案、
  workflow_dispatch 干跑、排查（PyInstaller hooks / Gatekeeper /
  `macos-13` runner 终将退役）。
- **`docs/workflow.md`**（+ 中文镜像）说明 `uv run diting` 是开发者路
  径、curl 一行是用户路径，两者都属于一等公民。
- OpenSpec 规范条数：17 → 20（新增 `wifi-detail-modal`、
  `bonjour-detail-modal`、`installation`；修改 `ble-detail-modal`、
  `tui-shell`、`macos-helper`）。

## [0.9.0] — 2026-05-12

**「Bonjour 版」**。TUI 第三块面板从「Wi-Fi / BLE 二选」扩展为
「Wi-Fi / BLE / Bonjour 三循环」，并加入始终可见的视图 tab 指示，
任意一屏都能看出三视图存在。`--notify` 终于覆盖三种异常事件，
并按 target 做静默窗口去重。加上 2026-05-11 ~ 2026-05-12 期间
自动化 `/tui-audit` 跑出的一长串 i18n 打磨、BLE Categories 清理、
analyze 命令修复。

CHANGELOG 维护策略变更：随着 OpenSpec archive 作为变更履历的工作
流稳定下来，本文件**只在 cut 版本时维护**（不再每个 PR 都更新）。
细粒度的「为什么这么改」请直接看 `openspec/changes/archive/`。

### 新增
- **mDNS / Bonjour 发现** 作为 TUI 的第三块面板加入，与 Wi-Fi、BLE
  并列。按 `n` 在 Wi-Fi → BLE → mDNS → Wi-Fi 三态间循环切换。新面板
  列出本地链路上的 Bonjour 服务宣告（AirPlay、Chromecast、Sonos、
  打印机、NAS、HomeKit、Mac 工作站等），列：厂商 / 名称 / 服务类别 /
  最近见到 / 主机。完全被动监听，基于 `zeroconf` 库，只订阅白名单内
  的常见服务类型（不会发起 meta-discovery 洪水广播）。Poller 是惰
  性的——用户不切到 mDNS 视图就既不会 import zeroconf 也不会启动
  后台线程。服务类别会按 i18n 规则翻译。新增能力 `mdns-scanning`；
  `tui-shell` 调整为三态切换。新依赖：`zeroconf >= 0.130`。
- **异常守望模式（anomaly watchdog）。** `--notify` 现在会对三种异常
  事件（`rf_stir` / `latency_spike` / `loss_burst`）都触发 macOS 通知
  中心横幅，并且同时在 `diting monitor --notify`（无头）和默认 TUI 子
  命令（`diting --notify`）下生效。按 (event-type, target) 维度做
  静默窗口，持续告警每个 target 每分钟最多弹一次横幅。两个环境变量
  可调参：`DITING_NOTIFY_SILENCE_S`（3-3600，默认 60）覆盖静默窗口；
  `DITING_NOTIFY_STIR_CONFIDENCE`（`high` / `medium` / `all`，默认
  `high`）放宽 `rf_stir` 置信度阈值。非法值会落回默认并在 stderr
  打印一行 warning。静默窗口状态仅存在内存，重启即清零。JSONL 事件
  流不做去重 —— 静默窗口只针对 OS 通知这一副作用。无 `--notify` 的
  `diting` 与 `diting monitor` 行为保持与 0.8.0 完全一致。
- **小米 / 华米厂商数据 decoder**：`src/diting/decoders/xiaomi.py`，
  识别 cid 0x038F 的广播帧，surface `xiaomi.cid` / `xiaomi.frame_seq` /
  `xiaomi.body_hex` / `xiaomi.body_len`，但不臆造语义字段（小米
  没公开规范）。配套 vendors 行新增「折叠数」标注，把
  `merged_count - 1` 加总，让用户读到「Anhui Huami 20 个 · 折叠
  8 条 RPA」，而不是怀疑 RPA 轮换在虚增计数。

### 变更
- **第三槽面板新增「视图 Tab」指示**，无论用户在 Wi-Fi / BLE / Bonjour
  哪个视图，面板边框上沿都显示 `Wi-Fi · BLE · Bonjour` 三选项，
  当前激活的那一项 cyan 加粗，另外两项 dim 灰。原来在 border_title
  上的面板详情（`附近 BSSID (N) · 排序：AP` 等）移到 `border_subtitle`
  （边框下沿），信息没丢。修复 mDNS 面板合入后审计发现的「三视图
  不可发现」问题。
- **Header 副标题** 使用用户友好的视图名（`视图：Wi-Fi` / `视图：BLE` /
  `视图：Bonjour`）而非内部 token。
- **帮助面板和 README** 描述 `n` 键为三态循环
  （`Wi-Fi BSSID → BLE → Bonjour`）。
- **BLE Name 列回退链**：`d.name → d.type → d.device_class →
  (未知)`。helper 已经识别为 `Find My target` / `MS device beacon` /
  `Apple Proximity` 等的行，现在 Name 列直接显示 type 名，不再是
  `(未知)`。Services 列简化为纯服务-UUID 类别，不再重复 type /
  device_class。
- **Bonjour 行渲染打磨**：名称列去掉冗余的 `._<service-type>.local.`
  后缀，RAOP 行额外去掉 `<MAC-as-hex>@` 机器前缀。主机列从 18 扩到
  26 格，统一去掉所有 Bonjour 主机的 `.local` 后缀，
  `ccy-MBP2024-M4-Office` 这类工作站名不再截断。
- **`Tx / Max` 行** 去掉冗余的 `max` / `最大` 尾缀（行 label 已经
  说了 Max）。
- **`analyze` 时间范围** 跨午夜时给 end 也带上日期。以前
  `2026-05-10 22:04 → 13:01 (14h 57m)` 让读者要靠 duration 倒推
  end 是哪天；现在跨日时 end 也带 `YYYY-MM-DD`。

### 修复
- **关闭 44 处 ZH catalog gap**，包括整个 `BLEDetailScreen` 模态
  （身份 / 活动 / 服务 节标题、所有字段标签、内联注解、`Esc / i
  关闭` 关闭提示）。帮助面板 `r` 键的空格 bug（`~5s` ↔ `~5 s`
  catalog/调用方不一致）也修复了。帮助面板里的 panel 短名也按
  i18n 规则翻译。
- **RF 扰动事件 confidence 枚举**（`medium` / `high` / `low`）在
  事件 modal 中渲染翻译值（`中` / `高` / `低`），ZH 下不再漏 EN。
- **延迟尖峰的 `% loss` 后缀** 在 ZH 下翻译为「丢包」（之前是
  bare EN）。
- **analyze 命令的 RF stir 汇总标签**（`modes:` / `confidence:` /
  `locations:`）也按 i18n 翻译了。
- **`service types` 中文 leak**（catalog key 空格不匹配）。
- **BLE Categories 诊断行** 不再把协议工具类 GATT 服务（`1800`
  Generic Access、`1801` Generic Attribute、`180A` Device
  Information）算成设备类型。每行单独显示的 Services 列仍然
  会渲染这些名字。
- **已连接 BLE 行** 在 last-seen 列显示 `online` / `在线`，
  不再是 `—`（已连接就意味着在线，不是缺数据）。
- **BLE Categories 诊断行** 改为「数字在前」格式（`8 iPhone`
  而非 `iPhone 8`），不会被误读为机型号。

### 移除
- 死代码 `_environment_line` helper（`src/diting/tui.py`）—— 没
  任何生产调用方（只有一个 unit test 覆盖它），名字还跟正在使用
  的 `_environment_lines` 撞车。清理掉。

### 维护备注
- **CHANGELOG 策略变更**：自 0.9.0 起，本文件**只在 release 时维护**。
  每个 PR 的变更由其 OpenSpec proposal 记录在 `openspec/changes/`
  下；release 时把上次 tag 以来归档的 proposals 总结进来。详见
  `docs/workflow.md`。

## [0.8.0] — 2026-05-10

「谛听」版本。项目从 `wifiscope` 改名为 **谛听 (Diting)**，README
按新定位重写（核心命题：「你的 Mac 听见了什么，告诉你」），BLE 深度
识别 + decoder 框架 + 详情模态整套上线，SDD 流程 + 15 份能力 spec
回流，并对 voice / type / iconography / layout 整体做了一次设计
系统审计与对齐。本版本利用 v0.x 阶段允许的次要破坏性变更，对环境
变量和 helper bundle ID 做了重命名。

### 破坏性变更 —— 项目改名：`wifiscope` → `diting (谛听)`

项目正式更名为 **谛听 (Diting)**。原名暗示这是一个只做 Wi-Fi 的工具；
实际的能力范围（BLE / 链路健康 / RF 环境，加上 LAN / mDNS / sensing
的路线图）远不止于此。谛听 —— 佛教神兽，一耳能听十方世界一切声音 ——
正好对应这个项目的核心命题：把 macOS 默默察觉到但没告诉你的信号显化
出来。

Tagline：*「你的 Mac 听见了什么，告诉你。」* /
*"Your Mac hears more than it tells you."*

对用户来说意味着什么：

- CLI 二进制：`wifiscope` → `diting`
- 辅助进程：`wifiscope-helper.app` → `diting-tianer.app`
  （天耳 —— 佛教六神通之一，谛听本身具备的"听十方"能力；这个 Swift
  小包持有 Location Services + Bluetooth 授权，把信号转交给 Python）。
  **首次启动需要重新点 Allow 授权 Location 和 Bluetooth** —— macOS TCC
  按 cdhash 锚定授权，新 bundle ID（`com.chenchaoyi.diting.tianer`）
  对 TCC 来说是一个新身份。
- 环境变量：`WIFISCOPE_*` → `DITING_*`（`WIFISCOPE_LANG`、
  `WIFISCOPE_HELPER`、`WIFISCOPE_INVENTORY`、`WIFISCOPE_GATEWAY`、
  `WIFISCOPE_WAN`、`WIFISCOPE_SCAN_INTERVAL`、
  `WIFISCOPE_LATENCY_WAN_TARGET`）。**没有兼容兜底** —— 如果你的脚本
  里写了旧名字，请直接改。
- 默认 JSONL 日志文件名：`wifiscope-<TS>.jsonl` → `diting-<TS>.jsonl`
- Python 包：`import wifiscope` → `import diting`；PyPI / 仓库随之改。
- **没有改**：代码里的 Wi-Fi 类名（`WiFiBackend` / `WiFiPoller` /
  `MacOSWiFiBackend` 描述的是 *Wi-Fi 能力*，不是 app 名字）；15 个
  capability spec 名字；任何功能行为。
- 下面的历史条目（v0.7.0 及之前）保留写着 `wifiscope` —— 那些是冻结的
  历史发版记录。

### 新增
- **Spec 驱动的开发流程**（`openspec/`）。每一个会改行为的能力，
  现在都对应 `openspec/specs/<name>/spec.md` 下的一份权威契约；
  新工作走 `openspec/changes/<name>/` 提案，merge 后归档。流程规则：
  `docs/workflow.md`（英）/ `docs/zh/workflow.md`（中）。本次回流
  15 个能力的 spec。
- **CI 强化** —— `.github/workflows/test.yml` 现在三关：pytest 矩阵
  + TUI 快照回归（失败时上传 `snapshot-output/`）+
  `openspec validate --strict` 校验。`.github/pull_request_template.md`
  PR 模板把分支 / spec / 测试 / 文档 / 归档 5 块强制勾选。
- **`/opsx:test` slash 命令** 把完整自测（pytest + 回归 + spec 校验）
  delegate 给子 agent，主线程上下文不被测试日志污染。
- **逐协议 BLE decoder** 落在 `src/wifiscope/decoders/`：iBeacon、
  Eddystone（UID/URL/TLM）、Apple Continuity（Nearby Info / Find My
  / Handoff，多子帧链式遍历）、Microsoft CDP + Swift Pair、
  RuuviTag Format 5。`@register` 装饰器注册，输出键带协议命名空间
  前缀。
- **BLE 详情模态**（`i` / `enter`）：键盘 up/down + 鼠标单击选中并
  inspect、按设备 RSSI 历史 sparkline（`BLEHistory` 环形缓冲）、
  距离估算、manufacturer / service data 原始 hex dump、"Decoded
  payload" 段聚合 `decode_all(d)` 的输出。
- **Helper schema-4 原始字段透传** —— `service_data`、`tx_power_dbm`、
  `solicited_service_uuids`、`overflow_service_uuids`、
  `manufacturer_hex` 全部直达 `BLEDevice`，下游 decoder 不再需要
  重复一遍 CoreBluetooth bridge。
- **31 个 Apple BT-MAC OUI** 加入 `wifi_ouis.json`，已连接的 Magic
  Keyboard / Trackpad 行终于显示 "Apple, Inc." 而不是 `(unknown)`。
- **Vendor 解析链** 增加了 `service_data` keys 的查询（之前只查
  `service_uuids`），把 Xiaomi MiBeacon / Google Fast Pair /
  Microsoft Find My 类设备从 `(unknown)` 救出。真实环境覆盖率从
  64% → 99.5%。
- **`(anonymous)` 与 `(unknown)` 区分** —— 完全静默的广播渲染为
  `(anonymous)`（物理上限），有数据但解析链放弃的渲染为
  `(unknown)`（可改进的 decoder 缺口）。

### 改动
- **STIR 图例** 现在读 `current σ > baseline ×2.5 (≥3 dB)` ——
  从 `DEFAULT_SPIKE_RATIO` / `DEFAULT_SPIKE_MIN_DB` 取，再不会
  和触发逻辑漂移。之前写的是 `×3`，把比率和绝对阈值搞混了。
- **BSSID 单复数语法** —— `1 wide 2.4 GHz BSSID`（单数）和
  `27 wide 2.4 GHz BSSIDs`（复数）在英文 UI 现在都正确。
- **BLE 厂商列截断** 用 `…` 标识，16 个常见消费品牌走别名表
  （`Hewlett Packard En` → `HP Enterprise`）。
- **中文翻译打磨** —— 重写 16 处生硬 / 歧义 / AI 痕迹的字串：
  `σ 是 RSSI 抖动` → `σ 是 RSSI 标准差`（术语正确性）、
  `宽带 BSSID` → `宽信道 BSSID`、同屏 `最近` 歧义拆为 `最强` /
  `最近见到`、`扫描频率 7s` → `扫描间隔 7s` 等。
- **`scripts/tui_snapshot.py` explore 模式** 现在尊重
  `WIFISCOPE_LANG=zh`，可以审中文 UI。

### 修复
- BLE 行导航键（`↑` / `↓` / `enter`）通过 `priority=True` 绑定优先
  于 `VerticalScroll` 的内置滚动处理。鼠标单击 BLE 行也能选中并
  打开详情。
- 回归套件里 Diagnostics 面板渲染稳定性 —— seed helper 把
  `_link_diagnostic_tuple` / `_environment_diagnostic_tuple` pin
  到 App，避免随机一次刷新把 seeded 的 Link / Environment 行擦掉。
- **帮助弹窗里 `force re-roam` 行的中文翻译** —— `i18n.py` 里登记的
  catalog key 是 `cycle WiFi off/on`，但 `tui.py:426` 调用方写的是
  `cycle Wi-Fi off/on`，导致中文查表 miss、静默回退到英文。
  Catalog key 已和调用方对齐。

### 文档
- **Spec 覆盖矩阵** 落进 `tests/TESTING.md`（中文镜像在
  `docs/zh/TESTING.md`）—— `openspec/specs/<capability>/spec.md` 里
  每条 Requirement 现在都对应：一个真实测试名 / 一条
  `(review-enforced)` 约定 / 一个 `(regression-only)` 快照场景 /
  或一个诚实的 `(gap)`。冷却 / rearm 逻辑、EventRing 容量上限、
  footer 分组、subtitle、fit_cells、network-change 探针重置、
  atexit writer 关闭、几条 CLI 派发路径等覆盖空白现在显式可见，
  不再是隐性的。
- **`Wi-Fi` / `WiFi` 用法归一** —— 所有面向用户的散文（README、
  帮助弹窗、re-roam 弹窗提示）统一为 `Wi-Fi`。内部类名
  （`WiFiBackend`、`WiFiPoller`）保留不动。
- **README 现在纯面向用户。** 偏向贡献者的几节
  （`Specifications`、`Development`、`How it works`）整体搬到了
  仓库根目录新增的 [`DEVELOPMENT.md`](../../DEVELOPMENT.md)，
  中文镜像在 [`DEVELOPMENT.md`](DEVELOPMENT.md)。README 在靠近底部
  的位置只留一条到 DEVELOPMENT.md 的指针。能力索引、开发命令、
  双语纪律、BSSID 解析算法深度细节都在新文档里；没有删任何内容，
  只是搬了位置。
- **README 按新定位重写。** `## 为什么需要它` 现在以核心命题开头
  （「macOS 听见的远比告诉你的多；谛听把它显化」），把 Wi-Fi /
  BLE / 链路健康 / RF 环境 / 事件五个能力面平等列出，不再 Wi-Fi
  优先。新增 `## 你能用它做什么` 列四类用户价值场景。路线图重写
  成三档：近期（mDNS / Bonjour、异常守望模式、单设备方向感罗盘、
  蜂窝状态）、中期（场景化 / 排查模式、JSONL 回放、趋势图、自动
  漫游）、远期（室内人员感知作为长期硬件辅助旗舰能力、菜单栏 App、
  Linux backend、Continuity / 热点 / Private Relay 状态）。

## [0.7.0] — 2026-05-07

「链路是不是真的通 + 周围有没有动静」版本。RSSI 单独并不能告诉你
网关是不是在排队丢包，也不能告诉你刚才有人是不是从笔记本旁边走过；
v0.7.0 加了两条持续探针来回答这两个问题。

### 新增
- **持续延迟 / 丢包探针**（每秒一次 ICMP，调用 `/sbin/ping`）针对
  用户的网关 + 自动检测的 WAN 锚点 —— 系统当前配置的 DNS 服务器，
  直接读 `SCDynamicStoreCopyValue("State:/Network/Global/DNS")`，
  退而求其次走 `scutil --dns` 子进程解析。优先级：
  `WIFISCOPE_LATENCY_WAN_TARGET` 环境变量 > 自动检测；如果配置的
  DNS 就是网关本身，WAN 探测被跳过，诊断行写
  `WAN n/a (DNS = 网关)` 让用户知道为什么少一列。DNS 检测每 60 秒
  刷新一次，切换网络后无需重启 wifiscope。纯 ICMP，不要 root。
  诊断面板新增一行
  `Link  gw 12 ms · 丢包 0% · WAN 18 ms · 丢包 0% · 抖动 3 ms`；
  丢包 / 高延迟 / 不可达状态会带 ⚠ 标志和红色样式。
- **辅助进程的 beacon IE 解析。** `runScanAndDumpJSON` 现在会遍历
  CoreWLAN 的 `informationElementData`，解出 BSS Load（Element ID
  11 → `bss_load_pct` + `bss_station_count`）、Mobility Domain
  （54 → `supports_802_11r`）、RM Enabled Capabilities（70 →
  `supports_802_11k`）、Extended Capabilities 第 19 位（127 →
  `supports_802_11v`）。每个字段只在对应 IE 出现时输出，schema 2 /
  仅有部分 IE 的旧消费者保持向前兼容。Schema 编号仍是 3；新增字段
  是叠加的。
- **环境监测器。** 新模块按 BSSID 计算滚动 RSSI σ，当两个阈值都满足
  （5 秒窗口 σ > 滚动 5 分钟中位 σ × 2.5 且 σ > 3 dB 绝对地板）就触发
  `RFStirEvent`，并在新增的 `Environment  σ 1.4 dB / 5s` 诊断行上以
  `稳定` / `活跃` / `安静` 三选一标签呈现。各 AP 融合模式按中位 RSSI
  自动分类：`co_located`（>= -65 dBm）做冗余融合（>= 2 个同位 AP
  同时跳变 = 高置信度）；`spatial_channel`（-65..-85）单 AP 一通道，
  事件标签上写该 AP 在 `aps.yaml` 里的名字；`ignored`（< -85）噪声
  太大，丢弃。**永远不会**说成「人数统计」或「移动检测」—— 所有界面
  上的措辞都是「有变化」。
- **统一事件面板 + `m` 模态浏览器。** v0.6.0 的「漫游日志」面板变成
  「事件」面板：同样的位置，同样的高度，但通过一个 `append_event`
  入口接收 roam / rf_stir / latency_spike / loss_burst / link_state
  五种事件。每行带类型前缀（`[漫游]` / `[扰动]` / `[延迟]` /
  `[丢包]` / `[链路]`）。新增 `m` 键打开 `EventsScreen` 模态：
  全屏浏览最近 100 条事件，可用 1/2/3/4/0 子键过滤，底部带各 AP σ
  基线小表 + 最近一小时 σ 走势 sparkline。
- **`wifiscope monitor` 与 `wifiscope calibrate` 子命令。** `monitor`
  无 TUI 长时运行，向 stdout（或 `--out path.jsonl`）逐行输出 JSONL
  事件，`--notify` 让高置信度事件触发 macOS 通知中心提醒。面向
  Home Assistant / 日志管道集成。`calibrate` 采集可配置时长（默认
  5 分钟）的「房间没人」基线 RSSI 样本，写入
  `./wifiscope-baseline.json`；环境监测器启动时读这份文件，把诊断
  行标签从默认的 `稳定 / 活跃` 切换到 `安静 / 活跃`。
- **`WIFISCOPE_LATENCY_WAN_TARGET` 环境变量** 用于在一次性调用、
  或 DNS 自动检测选错锚点的网络上手动指定 WAN 探针 IP。
- **`make monitor` Makefile 目标**（`uv run wifiscope monitor` 的
  快捷方式），便于发现。
- **EventsScreen 预览 SVG**（英文 + 中文）让 README 也能展示模态
  浏览器。原有 4 张 SVG（Wi-Fi + BLE × 英 + 中）保留；`make preview`
  现在生成 6 张。
- **40+ 项新测试，跨 4 个模块** 覆盖 ping 输出解析、尖峰 / 丢包风暴
  探测、规范明确列出的 7 种 DNS 自动检测形态、刷新节奏、环境变量
  覆盖、scutil 退路解析器、σ → 事件触发、模式分类、冗余融合、采集
  往返、每种事件格式行，以及诊断面板包含两个新行 + 模态打开 / 关闭
  流程。

### 变更
- 诊断面板现在是 7 行（原 5 行）：在原有可见网络 / 提醒 / 推荐信道 /
  健康 / 评分之后追加 `Link` 与 `Environment`。
- 「漫游日志」面板更名为「事件」—— 同位置、同高度、同样按时间排序的
  环形缓冲，但接收所有 v0.7.0 事件类型。
- ScanResult 数据类新增 `bss_load_pct` / `bss_station_count` /
  `supports_802_11r` / `supports_802_11k` / `supports_802_11v`，
  默认 None，所以 v2 helper / 旧版缓存扫描结果仍可解析。

### 已知局限
- 自适应基线会漂移 —— 6 点下班、第二天 8 点回来，那一阵子会触发
  误报事件。在意的用户可以跑 `wifiscope calibrate` 校正。
- `/sbin/ping` 只到毫秒精度；亚毫秒级有线 LAN 会读到 0 或 1 ms。
- 丢包风暴检测最多滞后 5 秒（3 中 5 规则）。
- 环境事件只是相关性，不是因果 —— 邻居 AP 重启也会触发一次 stir。
- DNS 自动检测忽略 DoH / DoT（Firefox 加密 DNS、Tailscale MagicDNS）；
  我们 ping 的是 OS 解析器认为的上游，不一定是某个 App 实际用的。

## [0.6.0] — 2026-05-07

「这到底是个什么设备 + 我现在到底连着什么」版本。这是 v0.5.0 BLE
面板回答不清楚的两个问题：那个写着「Apple, Inc.（匿名）Find My」
的到底是什么？我现在正在听的 AirPods 又在哪行？现在都有答案了。

### 新增
- **公开 BLE 广告格式的 Tier-1 深度识别。** Swift 辅助进程新增的
  `BLEAdParser` 识别 iBeacon（Apple 厂商类型 `0x02`）、AirTag /
  Find My 目标（Apple 类型 `0x12` ± Find My service `FD5A`）、
  Eddystone 全四种帧（UID / URL / TLM / EID，service `FEAA`）、
  Tile（`FEED` / `FEEC`）、Samsung SmartTag（Samsung 公司 ID +
  `FD5A`，从 Apple Find My 的同一 UUID 上区分出来）、Microsoft
  Swift Pair（Microsoft 公司 ID + 首字节 `0x03`）。Apple Nearby Info
  类型 `0x10` 解出未加密的设备类别 nibble：`iPhone`、`iPad`、`Mac`、
  `Apple TV`、`HomePod`、`Apple Watch`。每行的「服务」列现在以这个
  标签领头，所以面板会显示 `AirTag · Find My` 而不是只有 `Find My`。
  按规范不做的事：单机型识别（iPhone 14 vs 15，需要私有 GATT），以及
  Continuity 加密载荷的解密（锁屏状态、正在播放音乐 —— 加密、每设备
  一把密钥）。
- **当前已连接外设单独成段。** 辅助进程定期调用
  `retrieveConnectedPeripherals`，对一组常见 service UUID（Audio、
  HID、心率 / 电池、Find My、Eddystone、Tile）取并集，每个返回的
  外设输出一行 `{"connected": true, ...}`，再补一行
  `connected_snapshot` 哨兵让 Python 侧能够清理已经断开的旧条目。
  BLE 面板把它们渲染成单独的 `── 已连接 (N) ──` 区块，放在原有的
  `── 正在广播 (N) ──` 区块上面，RSSI 列里写 `—`（我们刻意不对活动
  连接调用 `readRSSI()`，避免打扰）。已连接条目按名字字母排序，
  绕过模糊合并。
- **「已连接」诊断行** 出现在「类别」行下方，仅当至少有一个外设
  连接时显示，并带每类别的细分（`已连接  3 个外设 · 2 音频 · 1 HID`）。
  「类别」行本身把 deep-ID 类型也算进去，所以 iBeacon、AirTag、被
  打上 iPhone 标签的设备会与 音频 / HID / 心率 一起出现。
- **Schema-3 辅助进程输出。** 每行广告 JSON 上多两个可选字段
  `type` 与 `device_class`；连接外设另起一种行 `connected: true`。
  Python TUI 兼容 schema-2 辅助进程（无 deep-ID、无连接列表），
  所以你刚升级 TUI 还没重建 helper bundle 时一切照旧。
- **20 个新的 BLE 单元测试** 在 `tests/test_ble.py`，加上 7 个新的
  TUI helper 测试，覆盖 deep-ID 检测算法（六个 Apple 设备类参数化）、
  connected 字典路由、`connected_snapshot` 哨兵剪枝、schema-2
  向后兼容、混流路由，以及 `BLEScanUpdate.connected` 在 poller 中的
  传播。还有一个 smoke 测试启动 App、灌入两个缓冲区、按 `n`、断言
  两个区块都已渲染。
- **i18n 字典条目** 覆盖区块标题（`已连接` / `正在广播`）、外设
  数量措辞、新的 `Find My target` 标签。品牌名类型（iBeacon、
  AirTag、Tile、SmartTag、Swift Pair、Eddystone-{UID,URL,TLM,EID}）
  与 Apple 设备类别名按设计在两种语言下都保持英文 —— 它们是专有名词。

### 变更
- BLE 预览 SVG（英文 + 中文）现在同时展示 `已连接 (2)` 段（AirPods Pro
  + Magic Keyboard）与 `正在广播 (8)` 段，并且至少给每个 Tier-1 类别
  一个示例（iPhone / AirTag / iBeacon / Eddystone-URL / Tile /
  Mi Band 7 等），让 README 头图反映 v0.6.0 的样子。
- `pyproject.toml` 版本号升到 0.6.0。

### 已知限制
- **Apple Continuity 的加密位仍然不可见。** 锁屏状态、正在播放音乐、
  AirDrop 会话信息 —— 这些都在 Apple 不公开的每设备密钥后面。我们只
  surface 类型 `0x10` 给出的 device_class。
- **已连接外设没有 RSSI / 厂商。** `retrieveConnectedPeripherals`
  返回的元数据远比一次新鲜广告少；面板在缺失的信号列里写 `—`，并
  把厂商列留白，而不是去伪造一个值。
- **`retrieveConnectedPeripherals` 必须列举服务 UUID。** 硬编码的
  service 列表会漏掉冷门外设（蓝牙 Mesh 节点、稀有 Health Devices）。
  对 v0.6.0 来说这个权衡可以接受。
- **MAC 随机化仍在。** 即使有了更深入的标签，30 分钟时间窗口里见到
  的同一台手机仍可能轮换好几个标识符。模糊合并器现在多了 `type` 与
  `device_class` 两个信号，但仍不能保证 1:1。

## [0.5.0] — 2026-05-06

「我身边到底有哪些电子设备」版本。

### 新增
- **附近 BLE 设备视图**，通过新增的 `n` 绑定切换。它在原位替换
  「附近 BSSID」面板（Diagnostics、Connection、漫游日志三个面板
  不变），改成可滚动的 BLE 设备列表 —— AirPods、Apple Watch、BLE
  键盘、Find My 信标、智能家居小物、iBeacon 等等。两个轮询器在
  app mount 时同时启动，所以在两个视图之间切换是即时的，不会出
  现「扫描中…」的过渡态。
- **通过现有辅助进程获得蓝牙权限。** `helper/wifiscope-helper.app`
  现在多承担一个 TCC 入口（`NSBluetoothAlwaysUsageDescription`），
  并新增 `ble-scan` 子命令把广告事件以 JSON Lines 流出。GUI 模式
  在启动时同时请求「定位服务」与「蓝牙」—— 一次点 Allow 同时覆盖
  两项。Python 侧不引入新依赖；现有的「权限隔离」架构保持不变。
- **打包好的 Bluetooth SIG 厂商表** 位于
  `src/wifiscope/data/bluetooth_vendors.json`（4021 条），新增
  `make update-vendors` 目标，会拉取上游 YAML、记录源仓库 commit
  hash 后重写文件。运行时不发起任何网络请求。
- **UUID 轮换的模糊合并。** 现代 BLE 设备会为隐私轮换标识；合并
  策略把 `(vendor_id, name)` 相同、RSSI 在 ±10 dB 内的条目折叠成
  一行，并显示 `(合并 N)` 徽章 —— 合并永远显式可见，不会静默。
  完全匿名的信标（厂商和名字都为空）永不合并，避免错误归并。
- **BLE 预览 SVG** 位于 `docs/preview-ble.svg` 与
  `docs/preview-ble.zh.svg`，与原有的 Wi-Fi 预览并列。README 头图
  现在同时展示两份，并附小字说明各自对应的视图。
- **8 个新的 BLE 单元测试** 在 `tests/test_ble.py`，覆盖 JSONL 解析、
  厂商查找、服务类别推断（心率 / HID / 音频 / 查找网络）、TTL 过期、
  模糊合并、权限拒绝处理、子进程崩溃韧性，以及 JSON 解析错误恢复。
- **i18n 字典条目** 覆盖每条新出现的用户可见字符串 —— 面板标题、
  视图副标题、服务类别（`音频` / `键盘` / `心率` / `查找网络`；
  按规范 iBeacon 保持英文）、占位提示、合并徽章。

### 变更
- `make preview` 现在生成 4 份 SVG（Wi-Fi + BLE，EN + ZH），新增
  `preview-ble-en` 与 `preview-ble-zh` 子目标可单独生成 BLE 视图。
  Wi-Fi 子目标行为不变。
- 帮助模态新增对 `n` 绑定的说明。
- 头部副标题新增 `view: wifi` / `view: ble` 段，让当前视图随时可见。

### 已知限制
- 本版仅 BLE，不涉及 macOS Bluetooth Classic / BR-EDR。
- 暂无 Linux / Windows BLE backend。
- 暂无 GATT 连接、配对，或单设备详情模态。
- Apple Continuity / Handoff 载荷统一显示为通用 Apple 设备 ——
  我们不会逆向解析这种私有格式。

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
