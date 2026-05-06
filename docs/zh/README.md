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
  <img src="../preview.zh.svg" alt="wifiscope TUI" width="100%">
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
| `c` | 断开重连 —— 关再开 Wi-Fi，让系统重新挑选最强的 BSSID |
| `h` | 打开 / 关闭应用内帮助页 |
| `b` | 打开 / 关闭 Wi-Fi 基础知识：SSID、BSSID、信道、频段、加密、漫游评分 |

`watch` 与 `once` 子命令以纯文本模式运行 —— 适合管道接日志或一次性诊断：

```bash
uv run wifiscope once     # 输出当前连接快照后退出
uv run wifiscope watch    # 流式打印事件，Ctrl+C 退出
```

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

**`disassociate()` 在强制漫游上不可靠。** `wifiscope` 早期版本曾用
`iface.disassociate()` 实现 `c` 键；在 802.1X 企业网络上，它会把链路拆掉
但 macOS 不会自动重连。改成 `setPower(false)` + `setPower(true)` 之后
路径与 Wi-Fi 菜单的关再开一致，能可靠触发完整 auto-join，复用 Keychain
凭据。

## 工作原理

下面这一节面向想了解细节的人，日常使用不需要读。

**从 BSSID 解析到物理 AP。** 两条规则，都受最后一字节邻近度门限的约束：

1. *前 5 个 octet 匹配 + 最后字节窗口。* 无线电与 VAP 通常按
   `mgmt + N` 分配（N 一般 1..6）。当多台 AP 共享同一段 OUI 时（比如 H3C
   控制器把多台 AP 分配在 `…3c:07`、`…3c:15`、`…3c:54`），单看前缀会撞车；
   规则要求 BSSID 的最后字节落在 AP 管理 MAC 最后字节 +8 之内，并选最近的。
2. *Octets 2..5 匹配 + 同一窗口。* 部分厂商把芯片的「用户」SSID 与
   「厂商内部」SSID 拆到相邻 OUI 段（H3C 用 `40:fe:95:…` 和 `44:fe:95:…`）。
   Octets 2..5 携带的是芯片序号位，跨段不变；规则把它们归到同一台 AP。
   误匹配概率约 1 / 2³²。

`radio_overrides` 永远胜过这两条规则。

**信道取自 `SCDynamicStore` 顶层 `CHANNEL` 字段**，而不是
`CWInterface.wlanChannel().channelNumber()`。macOS 在已关联状态下会做
后台扫描，1 Hz 的 CoreWLAN 轮询经常抓到无线电正在「扫描中跳频」的瞬间，
导致信道看起来在抖动。`SCDynamicStore` 的字段反映 OS 视角下的当前
关联信道，稳定。

**Backend 可插拔。** `WiFiBackend` 是一个抽象基类，提供 `get_connection`、
`scan`、`permission_state` 三个方法；macOS 的实现在 `MacOSWiFiBackend`。
未来要加 Linux backend（`nl80211` / `iw`）只需新增一个实现，不影响轮询、
清单、UI 任何一层。

## 开发

```bash
uv sync --all-groups          # 安装运行 + 开发依赖（pytest）
make test                     # 跑完整测试套件
make preview                  # 重新生成两份 preview SVG（EN + ZH）
make help                     # 列出所有 make 目标
```

[`TESTING.md`](TESTING.md) 是 canonical 测试计划 —— 每条自动化用例都在那份
文档里有一行；改测试场景请先改文档，再改测试代码。**评审 PR 时先读它。**

GitHub Actions 在每次 push 与 PR 上对 `main` 跑 macOS-latest × Python
3.11 / 3.12 / 3.13 的全量测试。CoreWLAN 与 SCDynamicStore 在 CI 里不
真跑 —— 这两层都在 subprocess / dynamic-store 边界处 mock。

### 维护中英双语 UI / 文档

仓库里两种语言并存，必须同步推进：

1. **文案**。`src/wifiscope/` 里所有用户可见的字符串都经
   `i18n.t(...)`。新增或修改一条时，请同步在
   `src/wifiscope/i18n.py` 的 `_ZH` 字典里加 / 改对应 key。缺 key
   时会回退到英文原文 —— 应用不会因此崩，但会静默漏译，所以漏
   翻的责任在改动作者本人。
2. **文档**。每份英文文档在 `docs/zh/` 下都有中文镜像。改一份
   就在同一个 commit 改另一份。每份文件顶部的 `English · 中文`
   切换条让漂移在读者眼里立即可见。
3. **预览 SVG**。`docs/preview.svg`（英文）与
   `docs/preview.zh.svg`（中文）都来自 `docs/_capture_preview.py`
   里的同一份 fake backend。**任何影响渲染的 UI 改动都要执行
   `make preview`**，让两份 SVG 与代码保持一致。一旦漂移，README
   首页的 hero 截图立刻就会暴露。

`make test-all` 会在 EN、ZH、自动嗅探 ZH 三种默认语言下都跑一遍
测试套件，专门捕捉任一语言场景下才会出现的 binding 顺序或 catalog
形态回归。

版本变更记录见 [`CHANGELOG.md`](CHANGELOG.md)。

## 路线图

- **CSV / JSONL 会话日志** —— `wifiscope log` 模式，把每次连接 / 扫描 /
  漫游事件追加到文件，便于后续分析。
- **TUI 内的趋势图** —— RSSI 随时间变化、每个 BSSID 的关联时长。
- **Linux backend** —— 通过 `pyroute2` 调 `nl80211`，或 fork `iw scan`。
- **可选的菜单栏 App** —— 即便不开终端也能 ambient 感知。

## License

MIT。见 [`LICENSE`](../../LICENSE)。
