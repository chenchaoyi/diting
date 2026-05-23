## ADDED Requirements

### Requirement: i18n catalogs SHALL provide EN ↔ ZH parity for all new LAN-identification surface strings
For every new English string introduced by the `expand-lan-identification` change, the ZH catalog in `src/diting/i18n.py` SHALL ship a corresponding Chinese translation. The strings include, at minimum:

| EN key | ZH value (illustrative) |
|---|---|
| `class` (column header) | `分类` |
| `[new]` (chip) | `[新]` |
| `[probing]` (subtitle chip) | `[探测中]` |
| `Active discovery` (modal section header) | `主动探测` |
| `NBNS` (modal label) | `NBNS` |
| `UPnP server` (modal label) | `UPnP 标识` |
| `Friendly name` (modal label) | `友好名称` |
| `Model` (modal label) | `型号` |
| `TTL` (modal label) | `TTL` |
| `Class:` (modal label, identity section) | `分类：` |
| `Vendor (IEEE)` (modal continuation label) | `厂商（IEEE 注册名）` |
| `(not probed)` (modal placeholder) | `（未主动探测）` |
| `phone` (class value) | `手机` |
| `tablet` (class value) | `平板` |
| `laptop` (class value) | `笔记本` |
| `desktop` (class value) | `台式机` |
| `tv` (class value) | `电视` |
| `camera` (class value) | `摄像头` |
| `smart-home` (class value) | `智能家居` |
| `printer` (class value) | `打印机` |
| `nas` (class value) | `NAS` |
| `gaming` (class value) | `游戏机` |
| `speaker` (class value) | `音箱` |
| `router` (class value) | `路由器` |
| `Model:` (modal label, identity section) | `型号：` |
| `Active LAN probing` (modal title) | `LAN 主动探测` |
| `Scene:` (modal label) | `场景：` |
| `Network:` (modal label) | `网络：` |
| `(disassociated)` (modal value) | `（未连接 Wi-Fi）` |
| `One-shot probe. Re-confirm next time.` | `单次探测。下次还需重新确认。` |
| `esc cancel` (modal footer) | `esc 取消` |
| `wait 2s` (modal footer cooldown) | `等待 2 秒` |
| `y probe now` (modal footer) | `y 立即探测` |

The user-facing consequences paragraph in the probe consent modal SHALL be a single key whose ZH translation conveys the same three risk points (other guests' devices receive probes; IDS may flag; captive portal may rate-limit).

The class-value strings (`phone`, `laptop`, etc.) SHALL be passed through `t()` at the call site so the row + modal both pick up ZH translations when `DITING_LANG=zh`.

#### Scenario: ZH user sees translated chip
- **WHEN** `DITING_LANG=zh` is set and a LAN row was first seen 2 hours ago
- **THEN** the row line starts with `[新]` (not `[new]`)

#### Scenario: ZH user opens probe consent modal
- **WHEN** `DITING_LANG=zh` is set and the user presses `P` in public scene
- **THEN** the modal title reads `LAN 主动探测`; the body uses the ZH strings; the footer reads `[esc 取消]   [等待 2 秒]` during cooldown and `[esc 取消]   [y 立即探测]` after

#### Scenario: ZH user sees translated device class
- **WHEN** `DITING_LANG=zh` is set and a host's `device_class="tv"`
- **THEN** the LAN row's class column renders `电视`; the detail modal's `分类：` row renders `电视`

#### Scenario: EN user sees raw English labels
- **WHEN** `DITING_LANG=en` (default) and a host has `device_class="tv"`
- **THEN** the LAN row's class column renders `tv`; the detail modal renders `Class: tv`
