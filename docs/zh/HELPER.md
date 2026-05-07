<sub>[English](../../helper/README.md) · **中文**</sub>

# wifiscope-helper

一个极简的 Cocoa `.app`，承担两个职责：持有 macOS「定位服务」权限
以让 Python TUI 读取扫描列表里**每个 AP 的真实 SSID 与 BSSID**；
持有「蓝牙」权限以让 TUI 在 BLE 视图里**流式接收附近 BLE 广告**。

## 为什么需要它

macOS 14.4+ 把 CoreWLAN 的 `bssid()` / `ssid()` 隐藏成 None，除非
调用进程属于一个被授予「定位服务」权限的 `.app` 包。CoreBluetooth
的 `CBCentralManager` 同样要求进程具备 `NSBluetoothAlwaysUsage
Description` 入口，否则永远进不了 `.poweredOn`。从终端启动的 CLI
工具两项都拿不到 —— `wifiscope` 主进程通过 SCDynamicStore 旁路绕开了
Wi-Fi *当前连接* 的限制，但邻居列表没有等价旁路，BLE 完全没有旁路。
这个 `.app` 是规范的解法：用一个真实的 `.app` 注册到 TCC，一次性授予
两项权限，bundle 的 CLI 子进程就会同时继承 CoreWLAN 与 CoreBluetooth
的信任。

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

## 同一二进制的三种角色

```bash
wifiscope-helper            # GUI：同时请求「定位服务」与「蓝牙」并停留
wifiscope-helper scan       # CLI：输出一份 CoreWLAN 扫描的 JSON 文档后退出
wifiscope-helper ble-scan   # CLI：流式输出 CoreBluetooth 广告 JSONL，直到 SIGTERM
```

第一种是用户在 Finder 里双击 `.app` 时执行的形态。第二种是
`MacOSWiFiBackend` 在 Python 里 spawn 出来扫一次 Wi-Fi 列表的形态。
第三种是 `wifiscope.ble.BLEPoller` 长期挂着的子进程：每个广告事件
就是 stdout 上的一行 JSON 对象，Python 侧逐行读取。

TCC 按 bundle 而不是按二进制路径鉴权，三种调用形态都会继承同一份
权限授予。

## Info.plist 里的权限

bundle 声明了两项 TCC 入口：

- `NSLocationUsageDescription` /
  `NSLocationWhenInUseUsageDescription` —— 让 CoreWLAN 在扫描列表
  里返回未隐藏的 SSID / BSSID。
- `NSBluetoothAlwaysUsageDescription`（0.5.0 新增）—— 让
  `CBCentralManager` 进入 `.poweredOn` 并开始触发
  `centralManager(_:didDiscover:advertisementData:rssi:)` 回调。

两项都在 GUI 模式启动时一并请求；每个弹窗点一次 Allow，两个 CLI
子命令都能用。

## ble-scan 输出格式

每行一个 JSON 对象（不外包数组、无尾随逗号），方便 Python 侧逐行
读取。流里交替三种行：

**Schema-3 广告行（每个广告事件）：**

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "id": "550E8400-E29B-41D4-A716-446655440000",
  "name": "AirPods Pro",
  "rssi_dbm": -52,
  "is_connectable": true,
  "service_uuids": ["180D", "1812"],
  "manufacturer_id": 76,
  "manufacturer_hex": "4c001907...",
  "type": "AirTag",          // 可选，仅 schema-3
  "device_class": "iPhone"   // 可选，仅 schema-3
}
```

可选的 `type` 与 `device_class` 字段由辅助进程的 `BLEAdParser` 通过
公开格式检测填上。`type` 覆盖 `iBeacon`、`AirTag`、`Find My target`、
`Eddystone`、`Eddystone-UID`、`Eddystone-URL`、`Eddystone-TLM`、
`Eddystone-EID`、`Tile`、`SmartTag`、`Swift Pair`。`device_class`
覆盖 Apple Nearby Info：`iPhone`、`iPad`、`Mac`、`Apple TV`、
`HomePod`、`Apple Watch`。识别不出来时两个字段都不出现 —— Python
侧默认 `None`，所以 schema-2 的旧 helper bundle 还能照常解析。

**Schema-3 已连接外设行**（每 ~5s 一轮，对每个由
`retrieveConnectedPeripherals` 返回的外设输出一行，跨服务去重）：

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "connected": true,
  "id": "AA000000-1111-2222-3333-444455556666",
  "name": "Magic Keyboard",
  "service_uuids": ["1812", "180F"]
}
```

厂商 / `device_class` / `type` 刻意不填 ——
`retrieveConnectedPeripherals` 给的元数据远比一次新鲜广告少。RSSI
也不报告（我们刻意不对活动连接调用 `readRSSI()`）。

**Schema-3 已连接快照哨兵**（每轮快照结束输出一次，紧跟在每外设行
之后）：

```json
{
  "ts": "2026-05-06T12:34:56.789Z",
  "connected_snapshot": true,
  "count": 2,
  "ids": ["AA000000-...", "BB000000-..."]
}
```

Python 侧用它来剪掉两轮快照之间断开的外设 —— 用户刚关掉的 Magic
Keyboard 会出现在某一轮的 `ids` 里、在下一轮缺席，这正好是把它从
「已连接」段移除的信号。

权限被拒绝时，stdout 上会输出一行 `{"error": "..."}` 并以退出码 3
结束，让 Python 侧能区分「没授权」、「还没收到设备」、「子进程崩了」
三种情况。

Wi-Fi `scan` 载荷的 `schema` 字段在 v0.6.0 从 `2` 升到 `3`，让
Python 侧能在 spawn BLE 子进程之前就知道这个 bundle 是否支持 BLE。
