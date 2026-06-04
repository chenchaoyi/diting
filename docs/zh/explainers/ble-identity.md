<sub>[English](../../explainers/ble-identity.md) · **中文**</sub>

# diting 如何识别一个 BLE 设备

现代 BLE 设备会轮换广播地址（隐私特性），所以「同一个 identifier 又出现了」几乎
说明不了什么——你五分钟前看到的 identifier 属于（可能是）同一台物理设备的另一次
随机轮换。要对*复现*说点有用的话——「这是用户的常见环境，还是真正的新来者？」
——diting 需要一个能熬过地址轮换的**稳定身份**。

这个身份正是**熟悉度（familiarity）**层所依据的，也是「不做基于名字的分类」规则
约束的对象：显示名是用户可控、极易伪造的，所以**绝不**作为身份。

## 身份阶梯

对每个 BLE 设备，diting 按以下顺序选取它能得到的最强的稳定、*权威*身份：

1. **厂商 payload** —— `ble:<manufacturer_hex>`。设备广播厂商专属数据时，payload
   本身就是一个按设备的 token（与显示层「merged N」融合所用相同）。仅非 Apple
   —— Apple 的 Continuity payload 在设备间是通用的。

2. **service-data 按设备 id** —— `ble:sd:<id>`。一大类真实设备——小米手环 /
   Amazfit / 华米 / 华为可穿戴——通过 **service-data** 而非 manufacturer-data 广播：
   无厂商 payload、无名字、UUID 轮换。它们看起来匿名，但 service-data 帧里可能嵌有
   一个持久 id。diting 解析 **MiBeacon（`FE95`）**：当帧控制的「含 MAC」位置位时，
   嵌入的六字节 MAC 就是设备真实地址，跨轮换稳定 → `mibeacon:<mac>`。（其他 schema
   —— 华为/HONOR、SwitchBot、Govee —— 在加上解析器前落到后面的阶梯。）

3. **公司 id + 名字** —— `ble:vn:<vendor_id>/<name>`。在有 SIG 公司 id 和/或名字但
   无可用 payload 时的回退。

4. **厂商分组** —— `ble:vg:<vendor>`。最后的兜底。当一个设备被*确凿地归属到某厂商*
   （通过 OUI、SIG 公司 id、member-UUID 或厂商持有的 service-data UUID），但不暴露
   上面任何按设备 token 时，diting 把该厂商所有无 payload、无名字、轮换的设备折成
   **一个环境分组**。在高密度办公室里，这把 1400+ 个无法区分的华米出现折成单条
   *habitual* 记录，而不是 1400 条未分类记录。

如果都不适用——真正静默的信标——该设备**没有**熟悉度身份，这是诚实的：它的广播里
没有可供复现的东西。

## 为什么第 4 级用分组 key

第 1–2 级给出真实的按设备句柄。第 4 级刻意**不**给：这些设备轮换一切、不带任何
按设备 token，所以从空中根本拿不到按设备身份。按厂商分组是复现记账——「华米类设备
在这里是环境噪声」——不是按设备或信任判断。代价：若真有若干*新的*同厂商设备涌入，
会被读成一个已熟悉的分组，不会触发 `new_device_cluster` 洞察。对「环境 vs 有价值」
的目标这是正确取舍；带真实按设备 token 的设备（第 1–2 级）保留完整的新到达敏感度。

每一级都依据**权威**信号——payload、嵌入的 MAC、OUI/UUID/公司 id 派生的厂商——
绝不用可伪造的显示名。

## 范围

这是**熟悉度**身份（复现追踪），不改变实时显示去重 / 簇合并，所以 JSONL 事件日志
仍按每次轮换记录一条 `seen` / `left`；改变的是这些事件现在带熟悉度分类，于是
salience 能给它们排序，habitual 分组不再被读成 `first_time`。
