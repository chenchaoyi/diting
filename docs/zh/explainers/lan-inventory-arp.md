<sub>[English](../../explainers/lan-inventory-arp.md) · **中文**</sub>

# 「谁在用我的 Wi-Fi」—— 技术方案设计

LAN-清单这类能力，能让一台普通的手机 / 笔记本（在同一子网上）
回答**「现在哪些设备连在我家网络里」**，不用登录路由器后台。
这篇是 diting 里实现这一能力的详细设计：一个新的第四面板，
把本地子网每台主机的厂商、主机名、Bonjour 关联信息列出来，
活动状态实时刷新。

我们没承诺要做 —— 这是「决定做时按这个方案做」的设计稿。重点
讨论**从一台 Mac 客户端能观察到什么**，以及边界在哪里。

## 「看到 Wi-Fi 上的设备」到底指什么

这句话里其实藏着三个问题：

1. **现在在 LAN 上活跃**。有 IP X、MAC Y，过去一分钟跟谁讲过
   话。**普通客户端能回答。** 这是本文的范围。
2. **现在关联到 AP 上**。AP 的关联表里有它 —— 不一定在收发
   流量。**只有 AP / 路由器知道。** 不在范围。
3. **历史上曾经关联过**。每台加入过这个网络的设备的名册。
   **只有路由器知道，而且只在保留窗口内。** 不在范围。

diting 在普通家庭网络上能比较好地回答 (1)。在启用了**客户端
隔离**的企业 / 访客 Wi-Fi 上，下面所有方法都失效 —— AP 在
L2 直接丢弃所有客户端互发的流量。那是网络策略，不是我们能
修的 bug。

## 探测工具箱

下面每种观察方法都是**任何 LAN 客户端能做的被动 / 非特权
主动探测**。不需要 root、不需要 raw socket、不需要路由器
凭证。

### 二层：ARP 缓存 + ICMP / ARP 扫描

ARP 是地基。同一 /24 上任何设备想跟另一个设备说话，都得先
广播一句「谁是 X.X.X.X？」，对方回复的 MAC↔IP 映射落进本机
ARP 缓存：

```bash
$ arp -an
? (192.168.1.1) at aa:bb:cc:11:22:33 on en0 ifscope [ethernet]
? (192.168.1.42) at de:ad:be:ef:00:01 on en0 ifscope [ethernet]
? (192.168.1.55) at f4:5c:89:11:22:33 on en0 ifscope [ethernet]
```

这是**我们刚才跟谁讲过话**，不是网络上谁还活着。Mac 没主动
连过的设备不会出现。

要把全部主机点出来，得先做一次 **ICMP ping 扫描**，再读 ARP
缓存：

1. 从 `ifconfig en0` 推出子网（接口 IP + 掩码）。家庭网络大多
   /24，254 台主机要扫一遍。
2. 对每个 IP 并发 `ping -c 1 -W 200 X.X.X.X`（asyncio 任务池，
   并发 ~30）。每个 ping 要么收到 ICMP 应答（主机活着），要么
   200 ms 超时。
3. 扫描结束后再读一次 `arp -an`。**只要 ping 发出去**，前面那个
   ARP 请求就已经把 MAC↔IP 映射写进缓存了，哪怕主机回的是
   "host unreachable"。

**为什么用 ICMP ping、不用纯 ARP 扫描：** macOS 自带的 `ping`
是无特权的。纯 ARP 扫描走 raw socket 需要 root。先 ICMP 后读
ARP 拿到的结果一样，但不用提权。

**为什么不用 `nmap -sn`：** 一样的效果，但要拉个第三方依赖，
不值得。

健康环境下一次 /24 全扫 30 路并发 ~2-3 秒能完，沉默主机多
的话 ~10 秒。

### 二层兜底：被动监听 ARP

ARP 是 L2 广播 —— 「谁是」的请求每台同段设备都能听到。我们
可以**被动监听**接口上的 ARP 包（`tcpdump arp` 就行，BPF
过滤 `ether proto 0x0806`）。这能抓到我们没主动 ping 过的
设备，**只要它们自己讲过话**。慢，但完全不占用我们这边的
网络流量。

最划算的组合：每 60s 一次 ICMP 主动扫描兜底，扫描之间被动
监听做补充。

### 三层：OUI → 厂商

每个 MAC 地址前 24 位是 IEEE 给制造商分配的「组织唯一标识符」
(OUI)。IEEE 公布完整注册表；diting 已经在 BLE 这一侧用了一份
精选过的 OUI 表（`src/diting/data/wifi_ouis.json`）。以太网 /
Wi-Fi MAC 跟 BLE MAC 共用同一个 OUI 命名空间，所以这个数据
文件可以直接复用。

常见设备能免费拿到 `aa:bb:cc:11:22:33` → `Apple, Inc.`。长尾
厂商兜底为 `(未知)`。

### 四层：反向 DNS

对每个发现的 IP，`socket.gethostbyaddr(ip)` 发起一次 PTR 查询。
行为分几种：

- **带本地 DNS 的家用路由器**（华硕、ubiquiti、Fritz 等）：
  返回 DHCP 写入的主机名 → `airport-express.local`。
- **大多数家用路由器**：没本地 DNS → 查询透到上游公共 DNS →
  没结果。
- **macOS 本身**：`gethostbyaddr` 会先查 mDNS，所以广播 Bonjour
  的设备 IP↔主机名映射即使路由器没 DNS 也能拿到。

每次查询走 `asyncio.to_thread` 包一层，挂掉的 DNS 服务器不会
卡死面板。

### 五层：与现有 Bonjour 状态交叉关联

这一层是 diting 相对一般 LAN-清单工具的优势。`BonjourPoller` 已经在被动
监听 mDNS announce 了，每个 `BonjourDevice` 都带 `host`
(`.local.` 名字) 和 `addresses` (IPv4 + IPv6)。ARP 发现 IP X
之后，去 Bonjour 状态表里查这个 IP：

```
ARP 说：     192.168.1.42 = de:ad:be:ef:00:01 (Apple, Inc.)
Bonjour 说： 192.168.1.42 = ccy-MBP2024-M4-Office.local
                            服务: AirPlay, AirPlay 音频, Apple 配对
→ 渲染:     Apple, Inc.  ccy-MBP2024-M4-Office  AirPlay+3  192.168.1.42
```

对那些会广播 mDNS 的非 Apple 设备（打印机、NAS、Chromecast、
智能音箱、ESPHome IoT）也一样，免主动探测就能拿到友好名。
不广播 mDNS 的设备（多数通用 IoT、Android 手机、Windows
笔记本）就只剩 OUI 厂商 + IP + MAC 一行。

### 可选的第五+层：被动身份提示

MVP 后想再加：

- **SSDP / UPnP** (UDP 239.255.255.250:1900)：一次组播 "M-SEARCH"
  能从智能电视、游戏机、媒体渲染器拿到设备描述 URL。代码 ~20 行，
  跟现在 Bonjour poller 一样的只听不主动模式。
- **NetBIOS / LLMNR**：Windows 上还活着。UDP 137 名字查询能拿到
  NetBIOS 名字。现代 LAN 上越来越少。
- **TCP banner 抓取**：连一下 22 / 80 / 443 / 8080 / 5353 端口，
  读第一行 banner。能认出 SSH 版本、web 后台等。**已经跨进
  「主动端口扫描」的红线**，只能默认关闭、不能在陌生网络上跑。

MVP 我们到 SSDP 就停，banner 抓取留到后面再说，且要显式开关。

### 我们故意不做的

- **不爬路由器后台。** 有些工具会爬路由器 web UI 的 DHCP
  租约表。脆弱（每个路由器型号 HTML 不一样）、需要密码、对
  厂商也不太友好。不在范围。
- **不做 DPI（深包检测）。** 我们只看 L2 / L3 元数据，不看
  payload。
- **不抓包写 pcap。**
- **不端口扫描。** SYN 扫每台主机 65k 端口是把 diting 在
  公司 EDR 里挂上「恶意软件」标签的最快捷径。绝对不做。

## 用户看到什么

新增第四个面板循环 (`n` 切换变成 Wi-Fi → BLE → Bonjour →
**LAN**)，或者另起一个独立键 —— 走哪种是 UX 决策。每一行：

```
 厂商            名称                      服务 / mDNS             IP              MAC                  最近见到
 Apple, Inc.    ccy-MBP2024-M4-Office     AirPlay (+3)            192.168.1.42    de:ad:be:ef:00:01    now
 TP-Link        网关                       —                      192.168.1.1     aa:bb:cc:11:22:33    now
 Roku, Inc.     Living-Room-TV            SSDP                    192.168.1.55    f4:5c:89:11:22:33    now
 (未知)         —                          —                      192.168.1.81    98:76:54:32:10:00    13s 前
```

顶部诊断行：

```
LAN 清单  17 台主机  ·  4 台有名字 (Bonjour)  ·  2 台厂商未知  ·  子网 192.168.1.0/24  ·  上次扫描 8s 前
```

按 `i` 进入详情 modal 展示：IP / MAC / 厂商 / 主机名 / 该主机
所有 Bonjour 服务 / 首次见到 / 最近见到 / 到这台主机的 RTT
（复用 LatencyPoller）。

## 架构草图

```
LANInventoryPoller (新增, src/diting/lan.py)
  ├─ 子网检测：启动时解析 `ifconfig en0` 一次
  ├─ 扫描任务：每 60s 一次，asyncio.gather(254 个 ping) → 读 arp -an
  ├─ 被动监听（可选）：tcpdump -ni en0 'arp' 子进程，stdout 解析
  │   who-has / is-at，喂进状态表
  ├─ 富化：
  │     OUI 查表（复用 data/wifi_ouis.json）
  │     反向 DNS (asyncio.to_thread / IP / 500 ms 超时)
  │     Bonjour 交叉关联（读 BonjourPoller 的状态）
  ├─ 状态：dict[mac, LANHost]，按 MAC 索引（IP 会变 MAC 不变）
  └─ 向消费者吐 LANInventoryUpdate 快照
```

`LANHost`：

```python
@dataclass(frozen=True, slots=True)
class LANHost:
    mac: str
    ip: str
    vendor: str | None         # 来自 OUI 表
    hostname: str | None       # 来自反向 DNS
    bonjour_name: str | None   # 来自 BonjourPoller 交叉关联
    bonjour_services: tuple[str, ...]
    first_seen: datetime
    last_seen: datetime
    is_gateway: bool           # IP 等于 Connection.router_ip
    is_self: bool              # MAC 等于 Connection.interface_mac
```

新增 OpenSpec 能力 `lan-inventory`，包含 schema、扫描节奏、
交叉关联三组 requirement。`tui-shell` 加新视图标签 + 详情
modal。

## 性能预算

- **扫描的网络影响**：254 个 ICMP echo 请求 = 出 ~21 KB，
  回类似。每分钟一次 → 平均 0.35 kbps，可以忽略不计。
- **耗时**：典型家庭 /24 上 ~2-10 秒端到端。
- **CPU**：受 asyncio 调度限速；254 个各跑 ~200 ms 的 ping 任务，
  可控。
- **内存**：跟主机数线性增长；小型办公室 LAN 上一般 < 100 台。

poller 节奏比 scan / BLE 更慢（60-120 s 比较合适），因为 ARP
状态变化本来就慢。用户按 `r` 强制立即扫描。

## 局限性（要在 basics modal 里坦白）

1. **客户端隔离**：企业 / 访客 Wi-Fi 经常在 AP 层丢掉客户端
   互发流量。我们只能看到网关和自己。诊断行应该写：
   「网关之外暂未发现其他主机 — 网络可能启用了客户端隔离」。
2. **VLAN 切分**：不同机制同效果 —— 不在同 VLAN 的设备不可达。
3. **睡眠中的设备**：手机灭屏 + Wi-Fi 省电时不一定立刻回
   ICMP，得在后续扫描里补抓。
4. **IPv6-only / 双栈边缘**：纯 IPv6 LAN 在消费级设备里很少见；
   先做 IPv4，IPv6 NDP 发现放 v2。
5. **MAC 随机化**：iOS / Android 每个网络一个随机 MAC。我们能
   正确拿到「这个网络的 MAC」，但 OUI 查表会看到「本地管理位」
   是 1 → 厂商显示为 `(未知)`。Bonjour 交叉关联通常还是能
   靠主机名认出来。
6. **DHCP 租约变动**：设备重连 IP 会变。我们按 MAC 索引状态，
   行不会丢，IP 列自动刷新。

## 威胁模型与隐私

这是个**被动观察工具**。在自己家的网络上没问题。换别人的
网络就有讲究了 —— 60 s 一次 ICMP 全扫，IDS 会记日志（不太
礼貌），在公司 Wi-Fi 上跑会引来安全部门关注（明显可疑）。

特性默认**关掉**，让用户显式开启（`aps.yaml` 里加个 flag，
或 CLI / env var），README 加一行警示。能力规范里要写明
「默认禁用」这条要求。

## 为什么这事值得做

三个真实场景：

1. **「有没有陌生人进了我家网络？」** 不用猜、不用登录路由器
   就能看见。和现有的 roam 日志时间线结合，就成了「网络的
   传记」。
2. **「`192.168.1.81` 是什么、为什么吃我带宽？」** 带宽问题
   diting 答不了，但「这是谁」回答了一半问题。
3. **debug「电视 AirPlay 推不上去」**：把 LAN 清单和
   Bonjour 看到的东西对齐，刚好就是你要做的诊断。

## 工作量估计

- **MVP（扫描 + 读 ARP + OUI + 反向 DNS + Bonjour 交叉关联，
  不带 SSDP，不带 port banner）**：~1-2 天，含 OpenSpec、
  测试、TUI 面板。
- **打磨（加 SSDP、详情 modal、跟 LatencyPoller 整合显示 RTT）**：
  再 1-2 天。

如果决定做，丢进未来的 v1.2 是合理的。不引入任何新依赖 ——
stdlib + `subprocess` + 现有的 zeroconf / pyobjc 栈就够。

## 再次声明不在范围里

- **24/7 监控。** 那是
  [边缘硬件 sidecar](#) 的事，不是这个。MVP 只在 TUI 打开时
  做清单。
- **「把某台设备踢出网络」。** 这是路由器侧的动作，普通 LAN
  客户端做不到 —— 除非走 ARP 欺骗，我们不会做。
- **新设备告警**（「有陌生人刚加入！」）。可以靠 diff 快照
  做到，但前提是 diting 重启之后还能持久化历史 —— 那又回到
  边缘硬件的范围了。MVP 只展示实时状态。
