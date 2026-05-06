<sub>[English](../../helper/README.md) · **中文**</sub>

# wifiscope-helper

一个极简的 Cocoa `.app`，唯一职责是持有 macOS「定位服务」权限，
让 Python TUI 能读取扫描列表里**每个 AP 的真实 SSID 与 BSSID**，
而不仅仅是当前已关联的那一个。

## 为什么需要它

macOS 14.4+ 把 CoreWLAN 的 `bssid()` / `ssid()` 隐藏成 None，除非
调用进程属于一个被授予「定位服务」权限的 `.app` 包。从终端启动的
CLI 工具进不了那个授权列表 —— `wifiscope` 主进程通过 SCDynamicStore
旁路绕开了 *当前连接* 的限制，但邻居列表没有等价的旁路。这个 `.app`
是规范的解法：用一个真实的 `.app` 注册到 TCC，用户授权一次，CoreWLAN
就会对该 `.app` 的所有子进程返回未隐藏的数据。

## 构建

需要 Swift 5.9+（Xcode 命令行工具或完整 Xcode）。

```bash
cd helper
./build.sh
```

产出 `helper/wifiscope-helper.app`。

## 安装

```bash
mv wifiscope-helper.app /Applications/   # 或 ~/Applications/
open /Applications/wifiscope-helper.app
```

`.app` 窗口出现后会请求「定位服务」，授权完成后会有提示。关闭窗口
即可，wifiscope 日常使用不需要它一直开着。

也可以把 `.app` 留在仓库里 —— `wifiscope` 会搜索常见路径以及位于
`helper/wifiscope-helper.app` 的开发者构建。设
`WIFISCOPE_HELPER=/full/path/to/wifiscope-helper.app` 可强制指定路径。

## wifiscope 如何找到它

`MacOSWiFiBackend` 在构造时通过 `src/wifiscope/_helper.py:find_helper`
按以下顺序解析辅助进程位置：

1. `WIFISCOPE_HELPER` 环境变量（指向 `.app` 包或其二进制）
2. `/Applications/wifiscope-helper.app`
3. `~/Applications/wifiscope-helper.app`
4. 与本 README 同级的 `helper/wifiscope-helper.app`（开发用途）

找到之后，`scan()` 会执行 `<binary> scan` 并解析一份未隐藏的网络
JSON 文档。如果找不到或子进程失败，backend 会回落到直接调用
CoreWLAN —— 仍能拿到 RSSI / 信道 / 频段，但 macOS 26 在没有授权时
SSID / BSSID 仍被隐藏。

## 同一二进制的两种角色

```bash
wifiscope-helper            # GUI：请求「定位服务」并停留
wifiscope-helper scan       # CLI：输出一份 JSON 文档后退出
```

第一种是用户在 Finder 里双击 `.app` 时执行的形态。第二种是
`MacOSWiFiBackend` 在 Python 里 spawn 的形态。TCC 按 bundle 而不是
按二进制路径鉴权，所以 CLI 子进程会继承 GUI bundle 的权限授予。
