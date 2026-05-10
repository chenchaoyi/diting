<sub>[English](../../DEVELOPMENT.md) · **中文**</sub>

# diting —— 贡献与开发

> [`README.md`](../../README.md)（[中文](README.md)）介绍 diting 是
> 什么、怎么用。本文聚焦于如何开发、测试、贡献。

diting 用 **OpenSpec 形态的 SDD** 推进。每一个会改动行为的变更
都带一份位于 `openspec/changes/` 下的 spec delta 提案，与代码同评，
合并时把 delta 应用进 `openspec/specs/<capability>/spec.md` 这份
权威契约。

## 入口

| 文档 | 作用 |
|---|---|
| [`docs/zh/workflow.md`](workflow.md)（[English](../workflow.md)） | SDD 流程的权威说明 —— 分支规则、change 提案、归档流程、自测纪律 |
| [`docs/zh/TESTING.md`](TESTING.md)（[English](../../tests/TESTING.md)） | 权威测试方案 —— 每条测试都对应一条 spec Requirement，spec 覆盖矩阵显式列出空白 |
| [`openspec/AGENTS.md`](../../openspec/AGENTS.md) | AI agent 在 `openspec/` 内活动的规则 |
| [`.github/pull_request_template.md`](../../.github/pull_request_template.md) | PR 检查清单（分支 / spec / 测试 / 文档 / 归档） |
| [`CLAUDE.md`](../../CLAUDE.md) | 快速导览 + 硬性规则汇总 |

每个 PR 上 CI 强制项：pytest 矩阵（3.11 / 3.12 / 3.13）· TUI 快照
回归 · `openspec validate --specs --strict`。

## 能力索引

每个能力在 `openspec/specs/<name>/spec.md` 下有一份权威契约。新行为
先走 `openspec/changes/<name>/` 提案，merge 后归档进权威 spec。

| 能力 | 它管什么 |
|---|---|
| [`macos-helper`](../../openspec/specs/macos-helper/spec.md) | Swift 辅助进程包（TCC、子进程契约、schema） |
| [`wifi-scanning`](../../openspec/specs/wifi-scanning/spec.md) | 一行扫描结果承诺什么；遮蔽（redaction）的处理 |
| [`bluetooth-scanning`](../../openspec/specs/bluetooth-scanning/spec.md) | Schema-4 原始字段透传、vendor 解析链、anonymous 与 unknown 区分 |
| [`ble-decoders`](../../openspec/specs/ble-decoders/spec.md) | 逐协议 decoder 框架（iBeacon / Eddystone / Apple Continuity / MS CDP / RuuviTag） |
| [`ble-detail-modal`](../../openspec/specs/ble-detail-modal/spec.md) | 单设备 inspect 模态：选中、sparkline、解码后 payload |
| [`link-health`](../../openspec/specs/link-health/spec.md) | 网关 / WAN ping 聚合、抖动、丢包风暴 |
| [`environment-monitor`](../../openspec/specs/environment-monitor/spec.md) | RF 扰动检测、σ 基线、校准 |
| [`events`](../../openspec/specs/events/spec.md) | 五事件词汇表、环形缓冲、JSONL 序列化 |
| [`event-log`](../../openspec/specs/event-log/spec.md) | `--log` 与 `diting monitor` 共用的 JSONL writer |
| [`analyze`](../../openspec/specs/analyze/spec.md) | 纯规则日志后处理 + 启发式目录 |
| [`inventory`](../../openspec/specs/inventory/spec.md) | `aps.yaml` 解析、OUI 厂商表、cluster 标签 |
| [`roam-detection`](../../openspec/specs/roam-detection/spec.md) | 0–100 链路评分、+10 dB 候选门限、按 `c` 重选 AP |
| [`i18n`](../../openspec/specs/i18n/spec.md) | EN / ZH UI 不变量、JSONL 英文键规则、列宽 cell 计算 |
| [`tui-shell`](../../openspec/specs/tui-shell/spec.md) | 四面板布局、视图切换、模态生命周期、GroupedFooter |
| [`cli`](../../openspec/specs/cli/spec.md) | 子命令词汇表、`--lang` 优先级、`--log`、exit-hint |

## 本地开发

```bash
uv sync --all-groups          # 安装运行 + 开发依赖（pytest）
make test                     # 跑完整 pytest 套件
make test-all                 # 在 EN / ZH / locale 嗅探 ZH 三种环境下都跑
make preview                  # 重新生成两份预览 SVG（EN + ZH）
make help                     # 列出所有 make 目标
```

push 前自测（四道 CI 门）：

```bash
uv run pytest
uv run python scripts/tui_snapshot.py --mode regression
openspec validate --specs --strict
openspec validate <active-change> --strict   # 如果有正在进行的 change
```

或者用 Claude Code 里的 `/opsx:test` slash 命令把同样的检查 delegate
给子 agent，主线程上下文不被测试日志污染。

GitHub Actions 在每次 push 与 PR 上对 `main` 跑 macOS-latest × Python
3.11 / 3.12 / 3.13 的全量测试。CoreWLAN 与 SCDynamicStore 在 CI 里不
真跑 —— 这两层都在 subprocess / dynamic-store 边界处 mock。

## 维护中英双语 UI / 文档

仓库里两种语言并存，必须同步推进：

1. **文案**。`src/diting/` 里所有用户可见的字符串都经
   `i18n.t(...)`。新增或修改一条时，请同步在
   `src/diting/i18n.py` 的 `_ZH` 字典里加 / 改对应 key。缺 key
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

## 另见

- [`CHANGELOG.md`](../../CHANGELOG.md) —— 版本历史
- [`docs/zh/explainers/wifi-sensing.md`](explainers/wifi-sensing.md) ——
  我们刻意*不*声称的 Wi-Fi sensing 能力
