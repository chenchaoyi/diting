# remote-live-av 调研与接续记录

## 状态

2026-10-20：按维护者要求延期，保留调研与 OpenSpec 草案，后续再评审和排期。
本次只保存文档；实时音视频尚未实现，也未部署 TURN 或升级线上 relay。
`tasks.md` 中所有实现任务保持未完成。

原始讨论于 2026-07-07 收口为「开成 openspec 设计」。2026-10-20 从此前
Claude Code 的桌面／手机跨仓库会话恢复上下文，并核对当前代码。后续恢复会话的
系统记录没有新增产品决策。

## 已讨论的方向

- 保留现有 JPEG 快照，另加实时音视频层；不通过快照轮询队列拼接音频。
- 使用原生 WebRTC，媒体 peer 放在现有 Swift helper bundle 中，沿用该项目的
  设备权限归属方式；Python daemon 负责会话控制与信令转发。
- 复用 companion relay 传递加密 SDP／ICE，媒体走 WebRTC P2P 或 TURN。
  桌面发 offer，手机 answer。
- 优先考虑自建 VPS 上的 coturn，桌面签发短期凭证，共享密钥不交给手机。
  gtmux 的自建隧道提供运维参考，不能直接作为 WebRTC 的 TURN 服务。
- 默认关闭，摄像头和麦克风需前台授权；保持系统指示，记录会话起止，手机失联
  后释放设备。当前草案是 Mac 向手机的单向观看／收听，不包含双向对讲或录制。

这些是设计方向，不代表库选型、网络可达性或设备行为已经验证。

## 当前代码基线

核对基线：`36705a2`（2.1.5），现有分支 `feat/remote-live-av`。

| 项目 | 已核对的状态 | 代码入口 |
|---|---|---|
| 协议 | 最新 major 为 3，解码支持 1／2／3；command／media 最低版本为 3 | `src/diting/companion/protocol/version.py` |
| 消息 | 严格校验 camera command 和 JPEG media；尚无 signal | `src/diting/companion/protocol/messages.py` |
| 加密与契约产物 | 已有 secretbox 封装、schema／fixture 生成和 manifest 哈希 | `src/diting/companion/crypto.py`、`protocol/_generate.py` |
| relay | command／media 为短期、投递后删除队列；表名白名单及 channel bearer 鉴权 | `relay/src/index.js`、`relay/migrations/0003_command_media.sql` |
| 清理 | 解绑删除现有 command／media；未来 signal 队列也需纳入 | `relay/src/index.js::handleUnpair` |
| 测试 | 已有协议产物复现、兼容、加密和队列测试，可作为扩展入口 | `tests/test_companion_protocol.py`、`relay/test/relay.test.js` |

## 恢复实现前需确认

1. **信令结构。** 草案目前只列 `kind`、`sdp`、`candidate`，还未定稿会话标识、
   旧会话消息拒绝、ICE 结束标记、ICE-server 配置放置位置及大小限制。
   candidate 的 `sdpMid`／`sdpMLineIndex` 等字段需对齐两端原生 API。
   两个方向需各自的序号，避免与事件和快照游标混用。
2. **队列语义。** 确定 TTL、积压与单次拉取上限、并发 drain、重试／重放策略、
   解绑清理；同一 channel 共用 bearer，路由名称本身不提供桌面／手机角色鉴权。
3. **VPS 共存。** 确认公网地址、域名、证书、带宽、UDP 防火墙和 443 占用。
   TURN-over-TLS 不是 HTTPS，不能直接套用 gtmux 的 HTTP 反向代理。是否使用
   独立 IP、其他端口或四层分流，需要部署时决定；国内可达性需实测。
4. **原生依赖与权限。** `stasel/WebRTC` 只是候选；需要验证 macOS 支持、架构、
   SwiftPM 包装、签名、体积及 camera／mic 采集路径。此前「cdhash 改变必定让所有
   权限重授一次」的表述尚无本阶段证据，不能作为发布承诺。
5. **产品和跨仓库验收。** 明确后台／锁屏行为、会话超时和审计字段；与
   `diting-mobile` 配套修改、重 vendoring、兼容性测试和真机验收一起排期。

## 后续建议入口

恢复时先复核以上问题，再考虑协议 v4／signal 与 relay 路由这一独立阶段。
保留既有事件的 v1／v2 和快照的 v3 封装；新 signal 使用 v4。编写测试前先更新
`tests/TESTING.md` 及中文版。helper、daemon、手机与 coturn 分阶段推进，不能把
协议阶段完成等同于实时音视频可用。

## 来源与验证范围

- 仓库内原始方案：[proposal](proposal.md)、[design](design.md)、[tasks](tasks.md)
  及 `specs/` 下四项 capability delta。
- [W3C WebRTC](https://www.w3.org/TR/webrtc/)：ICE candidate 与 ICE-server
  数据模型的参考；本阶段未开展端到端互通实验。
- [coturn 官方配置示例](https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf)：
  TLS listener、共享密钥时限凭证及端口配置参考；本阶段未连接或配置 VPS。

2026-10-20 严格校验通过：`remote-live-av` change，以及现有 31 项 canonical
spec。此结果只证明规格格式有效，不代表实现或设备验证通过。
