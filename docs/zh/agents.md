# 给 agent 的 diting 指南

diting 的命令行就是面向 agent 的接口。每个 read 命令都是 JSON 优先的
—— stdout 只有 JSON，人类文案和报错走 stderr —— 并且干净退出，所以你
可以把 diting 当工具来驱动，无需抓取 help 文本或解析表格。

TUI（裸 `diting`）是给终端前的人用的。下面的内容都是给你用的。

## 先发现命令面

```bash
diting capabilities --json
```

返回一个可以据以固定（pin）的稳定清单：

```json
{
  "schema_version": 1,
  "exit_code_convention": {"0": "success", "1": "runtime error", "2": "usage error"},
  "deprecated_aliases": {"once": "status", "watch": "stream", "monitor": "stream"},
  "commands": [
    {
      "name": "status",
      "summary": "...",
      "output": "json-object",
      "exit_codes": {"0": "associated", "1": "not associated", "2": "usage error"},
      "flags": [{"name": "--json", "type": "bool", "default": false, "repeatable": false}]
    }
  ]
}
```

`commands[].output` 取值之一为 `json-object`（stdout 上一个 JSON 文档）、
`json-lines`（换行分隔的 JSON，每行一个对象）或 `text`。
`schema_version` 从 `1` 起；一旦变化，依赖某字段前先重新读取清单。

## 命令一览

| 命令 | 输出 | 用途 |
|---|---|---|
| `diting status [--json]` | json-object | 一次性读取当前连接 + 权限状态 |
| `diting scan [--wifi] [--ble] [--duration D] [--json]` | json-object | 拍一张一次性的传感器快照 |
| `diting stream [--duration D] [--out FILE] [--notify]` | json-lines | 捕获实时事件流（限时或直到被杀） |
| `diting analyze [PATH ...] [--since D] [--json]` | json-object | 把已捕获的 JSONL 日志后处理成报告 |
| `diting capabilities [--json]` | json-object | 发现命令面 |

主机未关联时 `status` 退出 `1`（快照仍然结构完整）。`--wifi` / `--ble`
都不给时 `scan` 两个传感器都跑，并按传感器给 JSON 建键；若某个传感器
不可用，其值是 `{"error": ..., "code": ...}` 对象，另一个照常返回。
`stream` 输出规范事件日志 JSONL —— 与 `analyze` 消费的格式完全一致 ——
所以捕获的流可以原样过一遍 `analyze`。

`--duration`（用于 `scan` / `stream`）与 `--since`（用于 `analyze`）
共用一套语法：裸整数（秒）或整数加 `s` / `m` / `h` 后缀 ——
`30`、`45s`、`5m`、`2h`。

## 你可以依赖的契约

- **stdout 纯净。** `--json` 下 stdout 只承载 JSON。所有横幅、提示、
  场景行、弃用提示都走 stderr。stdout 可直接管进 `jq`，无需过滤。
- **报错结构化。** `--json` 运行失败时向 stderr 打印
  `{"error": "<消息>", "code": <int>}` 并以对应码退出。CLI 绝不打印
  Python traceback（调试时设 `DITING_DEBUG=1` 可恢复）。
- **退出码稳定。** `0` 成功 · `1` 运行时错误（含 `status` 未关联）·
  `2` 用法错误（未知旗标、错误参数、未知子命令）。
- **键是稳定英文。** 无论 `--lang` 如何，JSON 的键与值保持英文；
  只有 stderr 上的人类文案会本地化。

## 常用模式

先发现，再读单个信号：

```bash
diting capabilities --json | jq -r '.commands[].name'
diting status --json | jq '.connection.rssi_dbm'
```

一次性环境快照：

```bash
diting scan --json | jq '{aps: (.wifi | length), ble: (.ble | length)}'
```

捕获一个限时窗口，再分析它：

```bash
diting stream --duration 5m --out /tmp/cap.jsonl
diting analyze /tmp/cap.jsonl --json | jq '.insights'
```

跟踪实时流里的某类事件：

```bash
diting stream | jq -c 'select(.type == "roam")'
```

## 弃用的动词

`once`、`watch`、`monitor` 仍然可用 —— 它们向 stderr 打印一行弃用提示，
再分别转发到 `status`、`stream`、`stream`。清单里的 `deprecated_aliases`
映射是权威来源；请迁移到规范名。

## 还没有的能力

无头流目前观测 Wi-Fi、延迟和 RF 扰动。把 BLE / LAN / mDNS 纳入捕获路径、
以及 diting 自管的后台捕获会话，作为后续工作在跟进。眼下，长时间观测就是
由你的 harness 后台运行 `diting stream --out FILE`，再 `diting analyze FILE`。
