<p align="right">
  <a href="../../README.md">English</a> · <strong>中文</strong>
</p>

<p align="center">
  <img src="../logo.svg" alt="wifiscope" width="320">
</p>

<p align="center">
  <strong>在终端里看清你的 Mac 连在哪个 Wi-Fi AP、什么时候切换、信号到底有多强。</strong>
</p>

<p align="center">
  <a href="https://github.com/chenchaoyi/wifiscope/actions/workflows/test.yml"><img src="https://github.com/chenchaoyi/wifiscope/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/chenchaoyi/wifiscope/releases"><img src="https://img.shields.io/github/v/release/chenchaoyi/wifiscope?display_name=tag" alt="release"></a>
  <a href="../../LICENSE"><img src="https://img.shields.io/github/license/chenchaoyi/wifiscope" alt="license"></a>
</p>

---

<p align="center">
  <img src="../preview.zh.svg" alt="wifiscope TUI – Wi-Fi 视图" width="100%">
  <br>
  <sub><i>Wi-Fi 视图（默认）</i></sub>
</p>

<p align="center">
  <img src="../preview-ble.zh.svg" alt="wifiscope TUI – BLE 视图" width="100%">
  <br>
  <sub><i>BLE 视图（按 <code>n</code> 切换）—— 上方是「已连接」外设，下方是「正在广播」设备，每行都给出公开格式识别出的标签。</i></sub>
</p>

<p align="center">
  <img src="../preview-events.zh.svg" alt="wifiscope TUI – 事件浏览器" width="100%">
  <br>
  <sub><i>事件浏览器（按 <code>m</code> 打开）—— 最近 100 条 漫游 / 扰动 / 延迟 / 丢包 / 链路 事件，附各 AP σ 基线小表 + 最近一小时 σ 走势 sparkline。</i></sub>
</p>

## 为什么需要它

你在家里或办公室部署了多台 AP，房间之间走来走去，但 Mac 死死黏在五小时之前
关联的那台 AP 上 —— 信号已经只剩 -75 dBm，旁边明明还有同名 AP，信号 -45 dBm。
Zoom 卡顿，你抱怨网络，却又找不到证据。

苹果自带的 Wi-Fi 面板只会告诉你**当前**信号，但不会告诉你*你在哪个 AP*、
*该不该换*、*OS 什么时候漫游过（或没漫游）*。`wifiscope` 把这个黑盒子拆开，
做成一个 TUI：

- 顶部面板把 Apple「按住 Option 点击 Wi-Fi」面板里的所有信息全部呈现，再加上
  IP / 网关 / 网卡 MAC / MCS / NSS / 最大链路速率
- 诊断面板把一次密集扫描翻译成可读结论：可见 BSSID 数、无密码 BSSID、
  信道拥挤度、最空信道建议、当前链路健康度、简易漫游评分
- 滚动的「附近 BSSID」面板列出范围内每个 BSSID，**按物理 AP 分组**
  —— 一台 AP 同时广播 5 个 SSID 时会折叠成一组带标签的群
- 底部面板**实时记录漫游事件**，标记 `[同 AP 切频段]`（同 AP 不同频段切换）
  或 `[跨 AP 漫游]`（真正在 AP 之间移动）
- **附近 BLE 设备视图**（按 `n` 在原位切换，替换扫描列表）分成两段：
  **已连接** 列出你*现在*正在用的外设（AirPods、Magic Keyboard、
  Apple Watch —— 它们不广播，所以普通 BLE 扫描看不见），**正在广播**
  列出附近每个广播中的 BLE 设备并标注**它到底是什么类型** —— `AirTag`、
  `iBeacon`、`Eddystone-URL`、`Tile`、`SmartTag`、`iPhone`、`Mac`、
  `Apple Watch`、`HomePod` —— 不再是「Apple, Inc.（匿名）Find My」
  这种墙
- 两条新的**链路健康**行：`Link` 行每秒一次 ping 网关 + 自动检测的
  DNS 服务器，让 -55 dBm 的 AP 在上游故障时也读得出来；`Environment`
  行用滚动 RSSI 方差给出 `稳定` / `活跃` 标签（跑过
  `wifiscope calibrate` 之后切到 `安静` 基线）。按 `m` 打开全屏事件
  浏览器，看最近 100 条 漫游 / RF 扰动 / 延迟 / 丢包 / 链路 事件。
  **不是** Wi-Fi sensing —— 我们刻意不声称的能力见
  [`docs/explainers/wifi-sensing.md`](explainers/wifi-sensing.md)

卡在弱 AP 上不动？按 `c`，`wifiscope` 会循环关再开 Wi-Fi，让 macOS 重新
auto-join，重新关联到信号最强的 BSSID。和「点菜单关 Wi-Fi 再开」是同一条路径，
但只需要一次按键。

## 快速开始

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)，外加 Xcode 命令行工具
（首次启动时会从一份小 Swift 源码自动构建辅助进程）。

```bash
git clone git@github.com:chenchaoyi/wifiscope.git
cd wifiscope
uv sync
uv run wifiscope
```

首次运行时，`wifiscope` 会构建并 `open` 一个迷你的 **辅助进程 .app**，请求
「定位服务」权限。点一次 Allow，窗口自动关闭，TUI 启动并显示完整的 SSID
和 BSSID。后续启动直接进 TUI —— 授权是持久的。

> **为什么需要辅助进程？** macOS 14.4+ 把 SSID 与 BSSID 隐藏成 None，
> 除非调用进程已被授予「定位服务」权限。从 Terminal 启动的 Python CLI 进
> 不了那个权限列表，但一个小 `.app` 打包可以。`wifiscope` 调用它来取扫描
> 数据，从而拿回真实值。在 TUI 里按 `h` 看完整说明。

## 切换语言

```bash
uv run wifiscope --lang zh           # 强制中文
WIFISCOPE_LANG=zh uv run wifiscope   # 用环境变量
```

不传任何参数时，`wifiscope` 会自动嗅探系统 locale —— `LANG=zh_CN.UTF-8`
默认走中文，其余默认英文。

## 按键

| 键 | 作用 |
|-----|--------|
| `q` | 退出 |
| `p` | 暂停 / 恢复轮询 |
| `r` | 立即重扫（CoreWLAN ~5 秒限流仍然会生效） |
| `s` | 扫描排序切换：按 AP ↔ 按信号 |
| `n` | 切换附近视图：Wi-Fi BSSID ↔ BLE 设备 |
| `c` | 断开重连 —— 关再开 Wi-Fi，让系统重新挑选最强的 BSSID |
| `m` | 打开 / 关闭事件浏览器 —— 最近 100 条 漫游 / 扰动 / 延迟 / 丢包 / 链路 |
| `h` | 打开 / 关闭应用内帮助页 |
| `b` | 打开 / 关闭 Wi-Fi 基础知识：SSID、BSSID、信道、频段、加密、漫游评分 |

`watch`、`once`、`monitor`、`calibrate` 子命令不走 TUI：

```bash
uv run wifiscope once                       # 当前连接快照
uv run wifiscope watch                      # 流式文本事件（Ctrl+C 退出）
uv run wifiscope monitor                    # 无 TUI，逐行 JSONL 事件
uv run wifiscope monitor --out events.jsonl # 追加 JSONL 到文件
uv run wifiscope monitor --notify           # 高置信度事件触发 macOS 通知
uv run wifiscope calibrate                  # 5 分钟「房间没人」基线 → ./wifiscope-baseline.json
```

`monitor` 是长时运行 / Home Assistant 集成场景：每一次漫游、RF
扰动、延迟尖峰、丢包风暴、链路状态变化都会输出一行符合 schema 的
JSON。schema 定义见
[`docs/specs/v0.7.0-network-ground-truth-and-environment-monitor.md`](../specs/v0.7.0-network-ground-truth-and-environment-monitor.md#single-eventsjsonl-schema-for-all-three-layers)。

## 配置

### AP 别名（可选）

`wifiscope` 不需要任何 AP 名字配置就能跑 —— 每个 BSSID 都会被分配一个形如
`?AB:CD:EF` 的自动聚簇标签，同一台物理 AP 的所有无线电会被分到同一组，
跨 AP 漫游分类也照常工作。

如果你想在扫描列表和漫游日志里看到**可读的 AP 名字**（比如 `2F-客厅`
而不是 `?40:fe:95`），在 `./aps.yaml`（与 `aps.example.yaml` 同目录，
通常是 clone 出来的仓库根目录）放一份配置：

```yaml
aps:
  - name: 1F-书房
    mgmt_mac: 40:fe:95:8a:3c:07
  - name: 2F-客厅
    mgmt_mac: 40:fe:95:8a:3c:54
  - name: 3F-阁楼
    mgmt_mac: bc:22:47:ca:79:46
```

`wifiscope` 会用 **`2F-客厅 (5G)` (40:fe:95:8a:3c:58)** 这种形式替换原始
BSSID，漫游事件会显示成 `[同 AP 切频段 2F-客厅: 5G → 2.4G]` 或
`[跨 AP 漫游]`。

**管理 MAC 从哪来。** 大多数控制器（H3C / Aruba / Ubiquiti / Cisco /
华硕 mesh 等）只暴露每台 AP 的**管理 MAC**，并不暴露 AP 实际广播的每个
无线电的 BSSID。从控制器 Web UI 的 **AP 列表页**（一般叫 "Access Points"
/ "AP 列表" / "Devices"）抄出来，按你能记住的空间标签起名字写进
`aps.yaml`。

**什么时候直接跳过。** 在企业网 / 共享网 / 不熟悉的网络里，你拿不到
控制器，那就不要建 `aps.yaml`。自动聚簇标签（`?AB:CD:EF`）已经能正确
把同一台物理 AP 的所有无线电归到一起 —— 你只是少了人可读的名字，其他
功能不受影响。

如果你的 AP 厂商对每个无线电随机化 MAC（少见，部分 Cisco Meraki SKU
会这么做），可以再加一段 `radio_overrides`，把指定 BSSID 直接映射到 AP
名字。示例见 [`aps.example.yaml`](../../aps.example.yaml)。

设 `WIFISCOPE_INVENTORY=/some/path/aps.yaml` 可以让 wifiscope 从当前
目录之外的位置加载这份文件。

### 环境变量

| 变量 | 默认值 | 作用 |
|---|---|---|
| `WIFISCOPE_LANG` | 自动嗅探 | 界面语言：`en` 或 `zh`。也可用 `--lang`。 |
| `WIFISCOPE_INVENTORY` | `./aps.yaml`（相对当前目录） | AP 别名 YAML 路径。文件可选，没有就走自动聚簇标签。 |
| `WIFISCOPE_HELPER` | 在 `/Applications`、`~/Applications`、仓库 `helper/` 中查找 | 指定 `wifiscope-helper.app` 包或其二进制路径。 |
| `WIFISCOPE_SCAN_INTERVAL` | `7` | 扫描间隔秒数。CoreWLAN 大约 5 秒限流一次，低于 ~6 秒时每隔一次返回空。最小 3。 |
| `WIFISCOPE_LATENCY_WAN_TARGET` | 由 `scutil --dns` 自动检测 | WAN 延迟探针的 IP。默认从 `SCDynamicStoreCopyValue("State:/Network/Global/DNS")` 取第一条非网关 DNS；如果配置的 DNS 就是网关，WAN 探测被跳过，诊断行写 `WAN n/a (DNS = 网关)`。可以指定固定 IP（如 `1.1.1.1`，仅在网络允许时使用）。 |

## macOS 注意事项

**部分邻居的 SSID 显示为 `(隐藏)`。** 这是 802.11 的隐藏 SSID 位 —— AP 在
正常广播，只是 SSID 信息字段被刻意空置。BSSID、信道、信号、能力都还能看见。
隐藏 ≠ 不可探测。

**`Tx Rate` 与 `Max Link Speed` 可能不一致。** Apple 的 `transmitRate`
（当前数据速率，可能含帧聚合）与 `maximumLinkSpeed`（在已协商的 PHY/MCS/NSS
下的能力上限）取自不同的 CoreWLAN API；并不保证「当前 ≤ 最大」。Connection
面板同时显示两者并附说明。

**诊断面板是引导，不是 RF 勘测工具。** 信道建议和漫游评分都由 CoreWLAN 最近
一次扫描里可见的 BSSID 估算而来。它会奖励更强 RSSI、更好 SNR、更干净的频段
和更空的信道，惩罚开放网络与加密类型不一致的候选。请把它当成「下一步该看
哪里」的提示，而不是 Apple 官方的漫游决策依据。

**`OPEN` 表示 Wi-Fi 层没有密码 / 加密。** Captive portal 仍可能在关联后要求
登录，但无线电链路本身是开放的。附近 BSSID 面板会标记这类行，便于快速评估
访客网络与意外开放的 SSID。

**没有辅助进程时，附近 BSSID 扫描列表会被完全隐藏。** RSSI、信道、频段、
带宽仍然可读，但每个 SSID 都显示成 `(已遮蔽)`，每个 BSSID 也是
`(已遮蔽)`。Connection 面板不受影响 —— `wifiscope` 通过另一条 SCDynamicStore
旁路读取*当前*关联 AP 的 SSID 与 BSSID，而 macOS 忘了对这条路径脱敏。

**BLE 设备会为隐私轮换标识。** 同一台物理设备（AirTag、手机、Apple
Watch）会在不同时段以不同 CoreBluetooth UUID 出现。wifiscope 的
模糊合并器会把 `(vendor_id, name)` 一致且 RSSI 在 ±10 dB 以内的条目
合并成一行，并在合并后的行上显示 `(合并 N)` 徽章 —— 但策略保守：完全
匿名（厂商和名字都为空）的信标永远不合并，否则会静默吞掉真实信号。
名字时有时无的设备多半会多出一两行，属于预期。

**BLE 距离短**（约 10 m，Wi-Fi 约 30 m），所以 BLE 列表通常会比
Wi-Fi 扫描"小一圈"，即便在密集楼层也是如此。

**macOS 不暴露 BLE 的底层 MAC**。CoreBluetooth 只给出每台主机一个
UUID；厂商识别只能走 manufacturer-data 公司 ID 字段。wifiscope 解析
Apple Continuity 的*公开*部分（Nearby Info 里未加密的设备类别 nibble
—— `iPhone` / `iPad` / `Mac` / `Apple TV` / `HomePod` / `Apple Watch`）
以及 Find My / iBeacon 的签名，但加密载荷（锁屏状态、AirDrop、正在
播放音乐、Handoff 会话信息）保持不可见。**单机型识别**（iPhone 14 vs
15）不在任何公开广告报文里 —— 谁要是声称做到了，那是 connect 之后
读取专有 GATT 服务，我们不做这件事。

**`Environment` 行不是 Wi-Fi sensing。** wifiscope 处于 Wi-Fi 感知
能力阶梯的 Tier 0：用 CoreWLAN 已经暴露的数据做滚动 RSSI 方差。
我们只输出 `稳定` / `活跃`（跑过 `wifiscope calibrate` 之后是
`安静` / `活跃`）这种二值标签 —— 永远不会做人数统计、姿态识别、
呼吸频率检测。CSI（学界 sensing 真正用的数据）在 macOS 上不开放，
即使在 ESP32 / Linux 下的 Intel 5300 上也开放，那些 Tier-3+ demo
也是研究级工程，不是 `pip install`。完整说明见
[`docs/explainers/wifi-sensing.md`](explainers/wifi-sensing.md)；
`Environment` 行就是「我们用 RSSI 老实做了什么」的现场示例。

**已连接外设没有 RSSI。** `retrieveConnectedPeripherals` 给出当前与
Mac 关联的外设（你正在听的 AirPods、正在敲的 Magic Keyboard），但要
中途读它们的信号需要对活动连接调用 `readRSSI()` —— 这是一次有副作用
的打扰，我们刻意不做。已连接段在信号列里写 `—`，按名字字母排序。

**`disassociate()` 在强制漫游上不可靠。** `wifiscope` 早期版本曾用
`iface.disassociate()` 实现 `c` 键；在 802.1X 企业网络上，它会把链路拆掉
但 macOS 不会自动重连。改成 `setPower(false)` + `setPower(true)` 之后
路径与 Wi-Fi 菜单的关再开一致，能可靠触发完整 auto-join，复用 Keychain
凭据。

## 贡献

参与开发？请看 [`DEVELOPMENT.md`](DEVELOPMENT.md)（[English](../../DEVELOPMENT.md)）：
SDD 工作流、能力索引、本地开发命令、双语纪律，以及实现细节
（BSSID 解析、信道处理、可插拔 backend）都在那里。

版本变更记录见 [`CHANGELOG.md`](CHANGELOG.md)。

## 路线图

按粗略优先级排列。分割线以下的是 nice-to-have，不在近期发版计划上。

### 近期版本规划

- **延迟 / 丢包 / 抖动连续探测** —— 后台 1 Hz ping 网关与公共 DNS，
  在诊断面板里呈现。补上"RSSI 看着不错但 Zoom 还是糊"这个纯无线
  指标回答不了的缺口；信号强是链路工作良好的必要条件，但不充分。
- **mDNS / Bonjour LAN 设备发现** —— 新增 `m` 键切换的视图，与
  Wi-Fi / BLE 平级，列出本地网络上每台 Sonos、Apple TV、HomePod、
  NAS、打印机、可 AirDrop 的 Mac、HomeKit 网关、Time Capsule 等
  在做服务广播的设备。比单纯 ARP 扫描信息丰富得多，对 Apple
  生态密集的环境尤其有价值。
- **Beacon Information Element 解析** —— 读出每个 BSSID 的 BSS Load
  （当前信道利用率 %）、802.11k 邻居报告、802.11r 快速漫游能力、
  802.11v BSS Transition 支持。这些字节其实已经在 CoreWLAN scan
  输出里，只是 helper 还没解码。让诊断能讲出"你当前 AP 的信道
  利用率 78%"或"3 台候选 AP 不支持快速漫游"这种结论，而不是从
  BSSID 密度去猜。
- **RSSI 历史 sparkline** —— 在附近 BSSID 每行右侧加一条 8 字符的
  `▁▂▃▄▅▆▇█` 火花线，显示该 BSSID 最近 N 次扫描的 RSSI 趋势。
  让"在跌"、"稳定"、"在涨"一眼可见，不用盯着面板看。
- **JSONL 会话日志 + 重放模式** —— `wifiscope log session.jsonl`
  持续追加连接 / 扫描 / 漫游 / 延迟事件；`wifiscope replay <file>`
  把日志重新喂进 TUI，事后回放调试昨天某段时间的网络故障。
- **TUI 内的趋势图** —— RSSI / 延迟 / 信道利用率随时间变化、每个
  BSSID 的关联时长。基于 JSONL 日志构建。

### 远期 / 待定

- **Linux backend** —— 通过 `pyroute2` 调 `nl80211`，或 fork `iw scan`。
  架构上 `WiFiBackend` 抽象层已经为它留好位置。
- **自动漫游模式** —— 门控、保守。当同名 SSID 候选明显更优持续
  ≥ N 秒后自动循环关再开 Wi-Fi。无人值守解决卡死弱 AP 的原始痛点。
- **可选的菜单栏 App** —— 即便不开终端也能 ambient 感知。
- **Continuity / 个人热点 / iCloud Private Relay 状态** ——
  Mac 专属整合，呈现在诊断面板里。

## License

MIT。见 [`LICENSE`](../../LICENSE)。
