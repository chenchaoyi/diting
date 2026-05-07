<sub>[English](../../explainers/wifi-sensing.md) · **中文**</sub>

# Wi-Fi sensing 与 wifiscope 的边界

如果你听说过 Wi-Fi 能"穿墙检测人体运动"、"数房间里有几个人"、
"不用摄像头监测呼吸频率" —— 是的，这是真实的研究领域，叫
**Wi-Fi sensing**（Wi-Fi 感知）。我们经常被问 wifiscope 能不能
做这些，写这一篇当标准答复。

## 短答

**不能，而且是有意为之。** wifiscope 定位是 macOS 终端 Wi-Fi
漫游与信号质量监控工具。上面那些花哨能力都需要 **Channel State
Information（CSI）** —— 子载波级的振幅和相位数据 —— 而 macOS
不把这些数据暴露给用户空间。我们只能用 CoreWLAN 给的：RSSI、
信道、BSSID 等。做一个有用的 dashboard 够了，做姿态识别不够。

## 能力分层

Wi-Fi sensing 不是一件事，是从"今天可行"到"仅研究 demo"的光谱：

| Tier | 做什么 | 需要硬件 | 可靠度 |
|---|---|---|---|
| **0. RSSI 方差** | "无线环境在动" / 粗运动 | 任意 Wi-Fi 卡 | 视距动作可用 |
| **1. CSI 存在感** | 空房 vs 有人，单人走动 | ESP32、Intel 5300 或研究 NIC | 校准后较好 |
| **2. CSI 动作识别** | 走 / 坐 / 跌倒 / 手势 | 上面的 + 训练 ML 模型 | 在训练过的环境里可用 |
| **3. CSI 生命体征** | 呼吸频率、心率 | 上面的 + 干净 SNR + 带通滤波 | 受控环境下的真实研究 |
| **4. CSI 姿态 / 穿墙** | 17 点人体姿态、多人追踪 | 多基站 mesh + 重型 ML | 仅研究，没生产级实现 |

wifiscope **稳定坐在 Tier 0**，而且只是因为 RSSI 本来就是我们
做漫游 dashboard 要采集的数据。

## 为什么 macOS 上拿不到 CSI

Apple 的 Wi-Fi 驱动和固件签名加密，只能通过不暴露 CSI 的私有
framework 访问。从 Broadcom 芯片提取 CSI 的事实标准方案是
[`nexmon_csi`](https://github.com/seemoo-lab/nexmon_csi)（固件
patching），但它支持树莓派和某些 Linux 笔记本，**不支持** macOS
或 Apple Silicon。今天 macOS 上没有任何公开的 CSI API。Apple
Silicon 让这条路更难，不是更容易。

如果真要做 CSI 工作，可行选项：

- **ESP32** + [`espressif/esp-csi`](https://github.com/espressif/esp-csi)
  或 [`StevenMHernandez/ESP32-CSI-Tool`](https://github.com/StevenMHernandez/ESP32-CSI-Tool)
  —— 5 美元硬件、文档齐全、研究界广泛使用。
- **Intel 5300 / AX200 / AX210** NIC + Linux —— 研究级。
- [`Gi-z/CSIKit`](https://github.com/Gi-z/CSIKit) Python 处理上面任意一种 CSI 输出。

这些项目都已存在，我们指向它们，而不是在 wifiscope 里劣质重造。

## 哪些项目应该忽略

这个话题的搜索结果噪声大。对那种声称用"开箱即用的开源代码"实现
Tier 3 / Tier 4 能力（生命体征、姿态、穿墙）的项目要警惕。识别
模式：

- 长串听起来很专业的命名管道（"gestalt / sensory / topology /
  coherence / search / model" 之类六阶段协议）
- 引用具体准确率数字但没有论文 / benchmark 链接
- 声称"对任何 Wi-Fi 路由器开箱即用"
- star 数与 working demo / 第三方复现不匹配

这些是 AI 生成 boilerplate 但其实跑不起来的红旗。2025-2026 年
[RuView 的 Hacker News 讨论](https://news.ycombinator.com/item?id=46388904)
是一个延展案例。底层的*科学*是真的（CMU WiFi-DensePose、MIT
Vital-Radio），但把那转化成 `pip install` 是研究级项目，不是
一个周末。

## wifiscope 在 Tier 0 内可以做什么

不过度承诺的前提下，我们已经在采集的 RSSI / Tx 速率数据可以支撑：

- **环境稳定度指示** —— 滚动窗口的 RSSI 方差，呈现在诊断面板。
  标签是"稳定" vs "扰动"，永远不是 "N 人"。
- **运动事件日志** —— 较大的 RSSI 摆动（≥ 8 dB / < 5 s）以
  时间戳行的形式记录在事件面板，类似漫游日志。回答"14:32 发生
  了什么吗？"。
- **占用 yes/no** —— 用一段空房 baseline 校准后，可以以可接受
  准确率分类"当前安静" vs "当前在动"。但是再细的人数估算用 RSSI
  做不可靠，不要承诺。

这些已经写进 README 的路线图。它们不是学术意义上的"Wi-Fi
sensing"，是从我们已有数据派生出的诚实指标。

## 真要做 Wi-Fi sensing 怎么办

是另一个项目。买一片 ESP32-S3，烧 ESP-CSI Toolkit，可视化 CSI
数据流。wifiscope 的范围止于"你的 Mac 无线电看到什么"；CSI
sensing 从你引入专用外接硬件开始。我们可能某天写一个配套仓库
做这事，但它不会活在 wifiscope 这个代码库里。
