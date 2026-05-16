"""Static-at-launch i18n for the diting TUI / CLI.

Contract pinned in ``openspec/specs/i18n/spec.md`` — language
resolution order, ``t()`` lookup, pad_cells / fit_cells column-cell
math, English-keys-in-JSONL invariant, acronym non-translation rule.

Two languages: English (default) and Simplified Chinese. The active
language is decided once at process start and does not change
afterwards — CJK character widths affect column-aligned tables, and
re-laying out the whole TUI mid-session is more risk than value.

Resolution order (first hit wins):

    1. Explicit `--lang {en,zh}` on the CLI
    2. ``DITING_LANG=zh`` environment variable
    3. System locale (``LC_ALL`` / ``LC_MESSAGES`` / ``LANG``) starting
       with ``zh_``
    4. English fallback

Translation API is gettext-style: English strings are themselves the
catalog keys. A missing key in the Chinese catalog silently falls back
to the English source so the UI never goes blank, and so adding a new
string in code does not require a matching catalog entry on the same
commit. ``t(en, **kwargs)`` substitutes named placeholders after
lookup, so format strings translate cleanly.

CJK glyphs occupy two terminal cells; column-aligned labels and table
headers must use :func:`pad_cells` rather than ``str.ljust``, which
counts code points instead of cells.
"""

from __future__ import annotations

import os
from typing import Final

from rich.cells import cell_len

# Public language codes — kept short so ``--lang zh`` reads naturally.
EN: Final = "en"
ZH: Final = "zh"
_VALID = (EN, ZH)

_lang: str = EN


def get_lang() -> str:
    """Return the active language code (``"en"`` or ``"zh"``)."""
    return _lang


def set_lang(lang: str) -> None:
    """Force the active language. Callers are typically the CLI on
    startup; tests use this to flip languages without going through
    environment variables."""
    global _lang
    if lang not in _VALID:
        raise ValueError(f"unsupported language: {lang!r}")
    _lang = lang


def detect_default_lang(env: dict[str, str] | None = None) -> str:
    """Pick a default language from explicit env vars, then locale.

    The TUI calls this once on startup with ``os.environ``. Tests pass
    a synthetic dict to avoid leaking the host's locale into asserts.
    """
    src = os.environ if env is None else env
    explicit = (src.get("DITING_LANG") or "").strip().lower()
    if explicit in _VALID:
        return explicit
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = (src.get(var) or "").lower()
        if value.startswith("zh"):
            return ZH
    return EN


def resolve_lang(cli_override: str | None, env: dict[str, str] | None = None) -> str:
    """Resolve the final language given an optional CLI override.

    ``cli_override`` is the exact value passed to ``--lang`` (already
    validated by argparse), or ``None`` if the flag was absent.
    """
    if cli_override:
        if cli_override not in _VALID:
            raise ValueError(f"unsupported language: {cli_override!r}")
        return cli_override
    return detect_default_lang(env)


def t(en: str, **kwargs: object) -> str:
    """Look up the active-language version of ``en`` and substitute kwargs.

    Falls back to ``en`` if the catalog lacks the key. Keyword
    arguments are required when the source uses ``{placeholder}``
    syntax — both languages share the same placeholder names.
    """
    if _lang == ZH:
        translated = _ZH.get(en, en)
    else:
        translated = en
    if kwargs:
        return translated.format(**kwargs)
    return translated


def pad_cells(text: str, target: int) -> str:
    """Pad ``text`` with trailing spaces so it occupies ``target``
    terminal cells. CJK glyphs count as 2 cells each. Strings already
    at or beyond ``target`` are returned unchanged.
    """
    width = cell_len(text)
    if width >= target:
        return text
    return text + " " * (target - width)


def fit_cells(text: str, target: int) -> str:
    """Truncate ``text`` to fit within ``target`` terminal cells, then
    pad to exactly ``target``. Equivalent to ``text[:n].ljust(n)`` for
    ASCII, but cell-correct: a Chinese AP name like ``1F-书房`` keeps
    every glyph instead of having ``房`` chopped in half mid-byte. If
    truncation would land on the second cell of a wide glyph, the glyph
    is dropped entirely so the output is never visibly garbled.
    """
    if cell_len(text) <= target:
        return pad_cells(text, target)
    out = ""
    used = 0
    for ch in text:
        w = cell_len(ch)
        if used + w > target:
            break
        out += ch
        used += w
    return out + " " * (target - used)


# ---------------------------------------------------------------------
# Chinese catalog. Keys are the English source strings exactly as
# written at the call site; values must preserve every ``{placeholder}``
# from the source. New English strings without a Chinese entry fall
# back to the source, so the UI never goes blank if a translation lags
# the code.
#
# Style choices:
# - Acronyms (SSID / BSSID / RSSI / dBm / SNR / WPA2 / OPEN / ENT /
#   PHY / MCS / NSS / Tx / Max) are kept in English: they read more
#   naturally to Chinese network engineers, and translating them
#   creates needless line-length growth.
# - Tabular column headers stay short (≤ 4 cells) so column widths set
#   for the English UI do not need to grow for the Chinese one.
# ---------------------------------------------------------------------

_ZH: dict[str, str] = {
    # ---- panel titles ----
    "Connection": "连接",
    "Diagnostics": "诊断",
    "Nearby BSSIDs": "附近 BSSID",
    "Nearby BLE devices": "附近 BLE 设备",
    "Roam log": "漫游日志",
    "Events": "事件",
    "Events log": "事件日志",

    # ---- footer / app bindings ----
    "Quit": "退出",
    "Pause": "暂停",
    "Rescan": "重扫",
    "Sort": "排序",
    "Re-roam": "重选 AP",
    "View": "视图",  # legacy; kept for command-palette / Ctrl+P
    "Toggle Wi-Fi / BLE / Bonjour view": "切换 Wi-Fi / BLE / Bonjour 视图",
    # ---- mDNS / Bonjour panel ----
    "Nearby Bonjour devices": "附近 Bonjour 设备",
    "(no Bonjour devices yet — scanning...)": "(暂未发现 Bonjour 设备 —— 搜索中...)",
    "host": "主机",
    "Visible Bonjour  ": "可见 Bonjour  ",
    "Top services  ": "主要服务  ",
    "Top vendors  ": "主要厂商  ",
    "{n} service types": "{n} 种服务",
    # Bonjour service categories.
    "AirPlay audio": "AirPlay 音频",
    "Chromecast": "Chromecast",
    "Sonos": "Sonos",
    "Printer": "打印机",
    "File share": "文件共享",
    "Mac": "Mac",
    "HomeKit": "HomeKit",
    "Apple Companion": "Apple 配对",
    "Screen sharing": "屏幕共享",
    "SSH": "SSH",
    "HTTP": "HTTP",
    "Thread": "Thread",
    "Matter": "Matter",
    "→ {view}": "→ {view}",
    "Help": "帮助",
    "Basics": "基础知识",
    "Close": "关闭",

    # ---- header subtitle ----
    "sort: {mode}": "排序：{mode}",
    "scan {n}s": "扫描间隔 {n}s",
    "PAUSED": "已暂停",
    "ap": "AP",
    "signal": "信号",
    "view: {mode}": "视图：{mode}",
    "wifi": "Wi-Fi",
    "ble": "BLE",

    # ---- Connection panel ----
    "(not associated)": "(未连接)",
    "(unknown)": "(未知)",
    "  · country {cc}": "  · 区码 {cc}",
    "Channel": "信道",
    "PHY / Sec": "PHY / 加密",
    "Tx / Max": "Tx / Max",
    "{tx}  /  {max}": "{tx}  /  {max}",
    "MCS / NSS": "MCS / NSS",
    "{mcs}  ·  {nss}": "{mcs}  ·  {nss}",
    " streams": " 空间流",
    "Noise": "噪声",
    "IP / Router": "IP / 网关",
    "This Mac": "本机 MAC",
    "Signal": "信号",
    "  * Tx and Max use different CoreWLAN APIs and may diverge.":
        "  * Tx 与 Max 来自 CoreWLAN 不同 API，数值可能不一致。",

    # ---- Scan panel ----
    "(scanning...)": "(扫描中…)",
    "  · scanned {n}s ago": "  · {n}s 前扫描",
    "  · identity TCC-redacted": "  · 标识被 TCC 隐藏",
    "  · sort: {mode}": "  · 排序：{mode}",
    "(no APs from last scan — likely throttle, retrying)":
        "(上次扫描无返回 — 可能被限流，重试中)",

    # ---- Scan list column headers ----
    # "RSSI", "SSID", "BSSID" stay English by design (acronyms).
    "channel": "信道",
    "band": "频段",
    "AP host": "AP",
    "security": "加密",
    "width": "带宽",

    # ---- Scan list cell placeholders ----
    "(redacted)": "(已遮蔽)",
    "(hidden)": "(隐藏)",

    # ---- Scan list group summary (by-AP mode) ----
    "BSSID": "BSSID",
    "BSSIDs": "BSSID",   # Chinese has no plural form
    "  ·  {n} SSID": "  ·  {n} 个 SSID",
    "  ·  {n} SSIDs": "  ·  {n} 个 SSID",
    "  ·  {n} {bssid_word}  ·  {rssi_part}":
        "  ·  {n} 个 {bssid_word}  ·  {rssi_part}",
    "  · current": "  · 当前连接",

    # ---- Roam log ----
    "(no roam events yet)": "(暂无漫游事件)",
    "(no events yet)": "(暂无事件)",
    "same AP": "同一 AP",
    "[band switch on {ap}: {prev_band} -> {new_band}]":
        "[同 AP 切频段 {ap}：{prev_band} → {new_band}]",
    "[inter-AP roam]": "[跨 AP 漫游]",

    # ---- App notifications ----
    "Wi-Fi off → on — reconnecting via auto-join (2-5 s)":
        "Wi-Fi 关 → 开，正在通过自动加入重连（2-5 秒）",
    "no Wi-Fi interface": "未发现 Wi-Fi 网卡",

    # ---- Diagnostics: waiting state ----
    "(waiting for scan data...)": "(等待扫描数据…)",

    # ---- BLE panel ----
    "(no BLE devices yet — scanning...)": "(暂无 BLE 设备，扫描中…)",
    "(BLE permission required)": "(需要蓝牙权限)",
    "(BLE helper unavailable — run `make helper` then re-open it)":
        "(辅助进程不可用 —— 跑 `make helper` 后重新 open 它)",
    "(installed helper is too old; rebuild with `make helper`)":
        "(已安装的辅助进程太旧；用 `make helper` 重新构建)",
    "(BLE error — Bluetooth may be off in Control Center)":
        "(BLE 出错 —— 系统蓝牙可能在控制中心被关掉了)",
    "(BLE state unknown — waiting for helper)":
        "(BLE 状态未知 —— 等待辅助进程)",

    # ---- BLE diagnostics panel (parallel to Wi-Fi diagnostics) ----
    "(BLE diagnostics will appear after permission is granted)":
        "(授权后才会显示 BLE 诊断)",
    "Visible BLE  ": "可见 BLE  ",
    "{n} total": "共 {n} 个",
    "  ·  {n} connectable": "  ·  {n} 可连接",
    "  ·  {n} anonymous": "  ·  {n} 匿名",
    "Vendors  ": "厂商  ",
    "Categories  ": "类别  ",
    "Closest  ": "最强  ",
    "(none)": "(无)",
    "(anonymous)": "(匿名)",
    "? {n}": "? {n}",
    "(+{n} folded)": "(已折叠 {n})",
    "{n} other": "{n} 其他",
    # Service-category labels for ble.py.service_category() return values
    # are already translated below in the BLE table area; nothing extra
    # needed here.
    "(merged {n})": "(合并 {n})",
    "  · {n}s ago": "  · {n}s 前",
    "{n}s": "{n}s",
    "now": "刚刚",
    "vendor": "厂商",
    "name": "名称",
    "services": "服务",
    "last seen": "最近见到",
    "online": "在线",
    "id": "ID",
    # SSID is a Wi-Fi acronym, kept English in both locales.
    "SSID": "SSID",
    # ---- BLE detail modal (`i` / `enter` on a row) ----
    "Esc / i to close": "Esc / i 关闭",
    "BLE device": "BLE 设备",
    "Identity": "身份",
    "type": "类型",
    "device class": "设备类别",
    "identifier": "标识符",
    "flags": "标志",
    "connected": "已连接",
    "connectable": "可连接",
    "vendor unknown": "厂商未知",
    "smoothed": "平滑",
    "tx power": "发射功率",
    "distance": "距离",
    "rough free-space estimate": "自由空间粗略估算",
    "samples over": "个样本，窗口",
    "rssi history": "RSSI 历史",
    "Activity": "活动",
    "first seen": "首次见到",
    "ago": "前",
    "between ads": "两次广播间隔",
    "ad count": "广播次数",
    "merged": "合并",
    "rotated UUIDs folded": "已折叠轮换 UUID",
    "Services": "服务",
    "(none advertised)": "(未广播)",
    "Extra UUID lists": "额外 UUID 列表",
    "solicited": "请求",
    "overflow": "溢出",
    "Manufacturer data": "厂商数据",
    "(no manufacturer-specific data)": "(无厂商专属数据)",
    "decoded as": "解码为",
    "raw payload": "原始载荷",
    "bytes": "字节",
    "Decoded payload": "解码后内容",
    "Service data": "服务数据",
    "(uncategorised)": "(未分类)",
    # ---- Wi-Fi detail modal (`i` / `enter` on a scan row) ----
    "Wi-Fi access point": "Wi-Fi 接入点",
    "Radio": "射频",
    "Beacon IE": "Beacon IE",
    "AP name": "AP 名称",
    "channel width": "信道带宽",
    "PHY mode": "PHY 模式",
    "noise": "噪声",
    "SNR": "SNR",
    "BSS load": "BSS 负载",
    "BSS station count": "BSS 终端数",
    "802.11r": "802.11r",
    "802.11k": "802.11k",
    "802.11v": "802.11v",
    "yes": "是",
    "no": "否",
    "country code": "区码",
    "(associated)": "(当前连接)",
    "(redacted by TCC — grant Location Services for full data)":
        "(TCC 已遮蔽 —— 授予定位服务后才能看到完整数据)",
    # ---- Bonjour detail modal (`i` / `enter` on a service row) ----
    "Bonjour service": "Bonjour 服务",
    "Network": "网络",
    "TXT records": "TXT 记录",
    "instance": "实例",
    "service type": "服务类型",
    "category": "类别",
    "port": "端口",
    "addresses": "地址",
    "<{n}-byte payload>": "<{n} 字节载荷>",
    "hex": "16 进制",
    "(empty)": "(空)",
    # Service categories — translation matches the spec list. Anything
    # not in this catalog (raw 16-bit UUIDs etc.) passes through as-is.
    "Audio": "音频",
    "HID": "HID",
    "HID Keyboard": "键盘",
    "HID Mouse": "鼠标",
    "Heart Rate": "心率",
    "Find My": "查找网络",
    # Common 16-bit GATT services pulled from the SIG list. Anything
    # the user has any chance of recognising gets a Chinese gloss;
    # niche profiles (Glucose, Cycling Speed and Cadence, etc.) pass
    # through with their English SIG name as a service-column hint.
    "Battery": "电池",
    "Device Information": "设备信息",
    "Generic Access": "通用接入",
    "Generic Attribute": "通用属性",
    "Human Interface Device": "HID",
    "Environmental Sensing": "环境感知",
    "Health Thermometer": "体温计",
    "Blood Pressure": "血压",
    "Glucose": "血糖",
    "Cycling Speed and Cadence": "踏频/速度",
    "Running Speed and Cadence": "跑步速度",
    "Weight Scale": "体重计",
    "Pulse Oximeter": "血氧",
    "Body Composition": "体脂",
    "Continuous Glucose Monitoring": "动态血糖",
    "Current Time": "时间同步",
    "User Data": "用户数据",
    "Battery Service": "电池服务",
    "Immediate Alert": "即时告警",
    "Link Loss": "链路丢失",
    "Tx Power": "发射功率",

    # ---- BLE deep-identification (v0.6.0) ----
    # Section headers in the two-section BLE panel layout. Brand-name
    # types stay English (iBeacon, AirTag, Tile, SmartTag, Swift Pair,
    # Eddystone-{UID,URL,TLM,EID}) — they are proper nouns. Apple's
    # Nearby Info device classes (iPhone / iPad / Mac / Apple TV /
    # HomePod / Apple Watch) likewise stay English.
    "Connected": "已连接",
    "Advertising": "正在广播",
    "Connected  ": "已连接  ",
    "{n} peripherals": "{n} 个外设",
    "Find My target": "Find My 目标",
    # Apple Continuity protocol type-byte labels. iBeacon / AirTag stay
    # as proper nouns; the others get a brief Chinese gloss describing
    # the broadcast intent so a user can tell at a glance whether the
    # nearby Apple device is offering AirDrop, ringing AirPods, etc.
    "AirDrop": "AirDrop",
    "AirPods": "AirPods",
    "AirPlay target": "AirPlay 接收",
    "AirPlay source": "AirPlay 源",
    "Watch pairing": "Watch 配对",
    "Handoff": "接力",
    "Tethering target": "热点共享端",
    "Tethering source": "热点客户端",
    "Nearby Action": "附近请求",
    "Apple Proximity": "Apple 邻近",
    "MS device beacon": "Microsoft 信标",

    # ---- CLI --help ----
    "usage: diting [--lang en|zh] [--log [PATH]] [SUBCOMMAND]\n"
    "\n"
    "  (no args)   launch the TUI dashboard (default; pass --notify to\n"
    "              raise OS banners on anomaly events while TUI runs)\n"
    "  once        print the current connection and exit\n"
    "  watch       stream events as plain text until Ctrl+C\n"
    "  monitor     headless JSONL events (long-runs / Home Assistant)\n"
    "              flags: --out FILE  --notify  --gateway IP  --wan IP\n"
    "  calibrate   record an empty-room RSSI baseline (default 300 s)\n"
    "              flags: --duration SECONDS\n"
    "  analyze     read a JSONL log and print rule-based insights.\n"
    "              With no PATH, uses the newest diting-*.jsonl in cwd.\n"
    "  --lang L    interface language: en, zh. Defaults to DITING_LANG,\n"
    "              then to the system locale (zh_* → zh, anything else → en).\n"
    "  --log[PATH] also write JSONL events while the TUI runs. With no\n"
    "              path, writes ./diting-YYYYMMDD-HHMMSS.jsonl in cwd.\n"
    "              Same schema as `diting monitor`; append-mode + line-\n"
    "              flushed so already-emitted events survive Ctrl+C / kill /\n"
    "              traceback. Env: DITING_LOG=PATH (or =auto for default).\n"
    "  --version   print the running version and exit\n"
    "  -h, --help  show this message\n":
        "用法：diting [--lang en|zh] [--log [PATH]] [子命令]\n"
        "\n"
        "  (无参数)    启动 TUI 仪表盘（默认；加 --notify 可在异常事件\n"
        "              触发时同步弹出 macOS 通知中心横幅）\n"
        "  once        打印当前连接快照后退出\n"
        "  watch       以纯文本流式输出事件，直到 Ctrl+C\n"
        "  monitor     无 TUI 长时运行，逐行 JSONL 事件\n"
        "              选项：--out FILE  --notify  --gateway IP  --wan IP\n"
        "  calibrate   采集「房间没人」基线（默认 300 秒）\n"
        "              选项：--duration SECONDS\n"
        "  analyze     读取 JSONL 日志，输出基于规则的洞察。\n"
        "              不带 PATH 时使用 cwd 里最新的 diting-*.jsonl。\n"
        "  --lang L    界面语言：en、zh。默认读 DITING_LANG，\n"
        "              再退到系统 locale（zh_* → zh，其余 → en）。\n"
        "  --log[PATH] TUI 运行的同时把 JSONL 事件追加写入文件。不带\n"
        "              PATH 时写入 cwd 的 diting-YYYYMMDD-HHMMSS.jsonl。\n"
        "              schema 与 `diting monitor` 一致，append 模式 + 行\n"
        "              刷新，已写入的事件 Ctrl+C / kill / traceback 后都\n"
        "              留在文件里。环境变量：DITING_LOG=PATH 或 =auto。\n"
        "  --version   打印当前版本号后退出\n"
        "  -h, --help  显示本说明\n",
    "diting: unknown subcommand {cmd!r}":
        "diting：未知子命令 {cmd!r}",
    "note: writing JSONL events to {path}":
        "提示：JSONL 事件正写入 {path}",
    "tip: summarise this session with\n"
    "       diting analyze {path}":
        "提示：本次会话可用以下命令生成报告：\n"
        "       diting analyze {path}",

    # ---- `diting once` plain-text output ----
    "backend:    {name}": "后端：    {name}",
    "status:     not associated": "状态：    未连接",
    "timestamp:  {ts}": "时间：     {ts}",
    "Country": "区码",
    "Router": "网关",
    "WARNING: SSID and BSSID are hidden. CoreWLAN is redacted by Location\n"
    "         Services and the SCDynamicStore fallback also returned\n"
    "         nothing. Grant Location Services to your terminal app, or\n"
    "         see README's macOS 26 caveats section.\n":
        "警告：SSID 与 BSSID 不可见。CoreWLAN 被「定位服务」隐藏，\n"
        "      SCDynamicStore 旁路也没有数据。请给你的终端 App 授予\n"
        "      「定位服务」权限，或参考 README 的「macOS 26 注意事项」\n"
        "      一节。\n",
    "note: SSID/BSSID via SCDynamicStore fallback (CoreWLAN is redacted).\n":
        "提示：SSID 与 BSSID 来自 SCDynamicStore 旁路（CoreWLAN 已被隐藏）。\n",

    # ---- `diting watch` plain-text banner ----
    "backend: {name}  (Ctrl+C to quit)": "后端：{name}  (Ctrl+C 退出)",
    "inventory: {n_aps} APs, {n_overrides} overrides — {path}":
        "清单：{n_aps} 台 AP，{n_overrides} 条覆盖 — {path}",

    # ---- TUI launch flow: helper auto-build / grant prompts ----
    "note: diting-tianer not found and could not be built.\n"
    "      Scan list will be TCC-redacted. To fix, install the\n"
    "      Swift toolchain (Xcode CLT) and rerun, or build helper/\n"
    "      manually. See README's helper section.":
        "提示：未找到 diting-tianer，且自动构建失败。\n"
        "      扫描列表将被 TCC 隐藏。请安装 Swift 工具链（Xcode CLT）\n"
        "      后重试，或手动构建 helper/ 目录。详见 README 的\n"
        "      「Helper」一节。",
    "note: helper found but not in an .app bundle; cannot trigger\n"
    "      Location Services prompt. Scan list will be redacted.":
        "提示：找到 helper，但它不在 .app 包内，无法触发「定位服务」\n"
        "      授权弹窗。扫描列表将被隐藏。",
    "Launching helper {bundle}": "启动辅助进程 {bundle}",
    "to grant Location Services. Click Allow when macOS asks.":
        "请在 macOS 弹窗中点 Allow 授予「定位服务」权限。",
    "(Ctrl+C to skip and start the TUI with redacted scan rows.)":
        "(按 Ctrl+C 可跳过，TUI 会以隐藏的扫描行启动。)",
    "  failed to open helper: {err}": "  启动 helper 失败：{err}",
    "Permission granted — starting TUI.": "授权成功，正在启动 TUI。",
    "(no grant after {n}s; starting TUI anyway.\n"
    " rerun diting after granting to see unredacted scan.)":
        "({n} 秒内未授权，TUI 仍将启动。\n"
        " 授权后重新运行 diting 即可看到未隐藏的扫描数据。)",
    "Skipped; starting TUI with redacted scan.":
        "已跳过，TUI 将以隐藏的扫描数据启动。",

    # ---- Bootstrap two-permission flow (Location + Bluetooth) ----
    "note: helper found but not in an .app bundle; cannot trigger\n"
    "      macOS permission prompts. Scan list will be redacted\n"
    "      and BLE view will be empty.":
        "提示：找到了 helper 但它不在 .app 包内，无法触发 macOS 授权弹窗。\n"
        "      扫描列表会被遮蔽，BLE 视图会是空的。",
    "Permissions required:": "需要以下权限：",
    "Location Services (Wi-Fi scan list)": "定位服务（Wi-Fi 扫描列表）",
    "Bluetooth (BLE devices view)": "蓝牙（BLE 设备视图）",
    "Click Allow on each macOS prompt that appears.":
        "在每个弹出的 macOS 授权窗口中点 Allow。",
    "(Ctrl+C to skip and start the TUI with degraded views.)":
        "(按 Ctrl+C 可跳过，TUI 会以受限视图启动。)",
    "  Location: {loc}    Bluetooth: {bt}":
        "  定位：{loc}    蓝牙：{bt}",
    "granted": "已授权",
    "waiting": "等待中",
    "All permissions granted — starting TUI.":
        "所有权限已授予 —— 正在启动 TUI。",
    "(no full grant after {n}s; starting TUI anyway with whatever\n"
    " permissions did land. Rerun diting after granting to\n"
    " unlock the remaining views.)":
        "({n} 秒内未全部授权，TUI 仍将以当前已有的权限启动。\n"
        " 授权完整之后重新运行 diting 即可解锁剩余视图。)",
    "Skipped; starting TUI with whatever permissions are in place.":
        "已跳过，TUI 将以当前已有的权限启动。",

    # ---- Stale-helper detection (0.4.0 → 0.5.0 upgrade path) ----
    "note: installed helper at {bundle} predates 0.5.0 (no\n"
    "      ble-scan subcommand). The BLE view would wedge\n"
    "      forever. Rebuilding the in-repo helper to use\n"
    "      instead — replace the installed copy at your\n"
    "      convenience.":
        "提示：{bundle} 处的辅助进程比 0.5.0 旧（没有 ble-scan\n"
        "      子命令）。BLE 视图会卡死。临时构建仓库内的辅助\n"
        "      进程顶上 —— 等你方便的时候替换掉那个旧的。",
    "Using freshly-built helper at {path}.":
        "改用新构建的辅助进程：{path}。",
    "warning: could not build a 0.5.0-capable helper. The\n"
    "         BLE view will show an 'incompatible helper'\n"
    "         placeholder; remove the old bundle from\n"
    "         /Applications and run `make helper` to fix.":
        "警告：未能构建 0.5.0 兼容的辅助进程。BLE 视图会显示\n"
        "      「辅助进程不兼容」占位；删掉 /Applications 下\n"
        "      的旧 bundle 后跑 `make helper` 修复。",

    # ---- Diagnostics: visible networks line ----
    "Visible BSSIDs  ": "可见 BSSID  ",
    "{n} total  2.4 GHz: {n2}  5 GHz: {n5}  6 GHz: {n6}":
        "共 {n} 个  2.4 GHz: {n2}  5 GHz: {n5}  6 GHz: {n6}",
    "  hidden in this scan: {n}": "  本次扫描隐藏：{n}",
    "  redacted: {n}": "  被遮蔽：{n}",
    "  country codes: {codes}": "  区码：{codes}",

    # ---- Diagnostics: warnings line ----
    "Things to notice  ": "提醒  ",
    "{n} open/no-password {b}": "{n} 个 BSSID 无密码",
    "{n} wide 2.4 GHz {b}": "{n} 个 2.4 GHz 宽信道 BSSID",
    "{n} other {b} on your channel": "本机信道上还有 {n} 个 BSSID",
    "mixed country codes nearby": "附近区码混合",
    "No obvious environment warnings from the scan.":
        "扫描未发现明显环境异常。",

    # ---- Diagnostics: recommendations line ----
    "Least crowded channels  ": "最空闲信道  ",
    "Estimated from the scan.": "按扫描结果估算",
    "  {band}: ch{n}": "  {band}: 信道 {n}",
    " (no AP heard)": "（信道无 AP）",

    # ---- Diagnostics: health line ----
    "Current link  ": "当前连接  ",
    "weak signal {dbm} dBm": "信号弱 {dbm} dBm",
    "fair signal {dbm} dBm": "信号一般 {dbm} dBm",
    "SNR {db} dB": "SNR {db} dB",
    "stronger same-name AP nearby: +{delta} dB ({label})":
        "附近有同名 AP 信号更强：+{delta} dB ({label})",
    "Looks OK": "正常",
    "  press c to re-roam": "  按 c 重选 AP",

    # ---- Diagnostics: roam score line ----
    "Roam score  ": "漫游评分  ",
    "current {n}/100": "当前 {n}/100",
    "  ·  no clearly better same-SSID BSSID": "  ·  暂无明显更优的同名 BSSID",
    "  ·  better candidate {n}/100": "  ·  更优候选 {n}/100",

    # ---- Link-score reasons ----
    "no signal reading": "无信号读数",
    "strong signal": "信号强",
    "good signal": "信号好",
    "usable signal": "信号可用",
    "weak signal": "信号弱",
    "low SNR": "信噪比低",
    "cleaner 6 GHz band": "6 GHz 频段更清净",
    "5 GHz": "5 GHz",
    "2.4 GHz crowding risk": "2.4 GHz 拥挤风险",
    "busy channel": "信道拥挤",
    "some channel sharing": "信道有共享",
    "different security": "加密类型不同",
    "open network": "开放网络",

    # ---- Help modal ----
    "  ·  macOS terminal listening post for Wi-Fi, BLE, link\n"
    "     health, and the RF environment.\n":
        "  ·  macOS 终端的信号监听台 —— Wi-Fi、BLE、链路健康、RF 环境。\n",
    "What": "概览",
    "What you get": "能看到什么",
    "  Live view of which AP / BSSID you're on, the BSSIDs around\n"
    "  you, connection latency / loss / jitter to the gateway and\n"
    "  WAN, an RSSI-variance environment monitor, and a deep BLE\n"
    "  device list — everything macOS hides from its own Wi-Fi\n"
    "  menu plus the diagnostic surfaces it never exposed.\n":
        "  实时看清你连在哪个 AP / BSSID、附近还有哪些 BSSID、到网关 /\n"
        "  WAN 的延迟 / 丢包 / 抖动、基于 RSSI 波动的环境监测，以及完整\n"
        "  的 BLE 设备列表 —— 把 macOS 隐藏掉的 Wi-Fi 信息和它从来没\n"
        "  暴露过的诊断维度都摆出来。\n",
    "Panels": "面板",
    "Conn.": "连接",
    "Scan": "扫描",
    "Diag.": "诊断",
    "Nearby": "附近",
    "Events": "事件",
    "Link (gateway / WAN latency, loss, jitter) and":
        "链路（网关 / WAN 延迟、丢包、抖动）与",
    "Environment (RSSI σ across nearby APs)\n":
        "环境（附近各 AP 的 RSSI σ）\n",
    "BSSIDs near you, BLE devices, or Bonjour services (cycle: n)":
        "附近的 BSSID、BLE 设备或 Bonjour 服务（按 n 循环）",
    "strip at the bottom; full browser via m":
        "底部窗格；按 m 打开完整查看器",
    "current AP, signal bar, link / IP / radio details":
        "当前 AP、信号条、链路 / IP / 无线参数",
    "every BSSID in range, grouped by physical AP":
        "范围内所有 BSSID，按物理 AP 分组",
    "band-switch and inter-AP roam events as they happen":
        "频段切换与跨 AP 漫游事件实时记录",
    "Bindings": "按键",
    "quit": "退出",
    "pause / resume polling": "暂停 / 恢复刷新",
    "force a rescan now (CoreWLAN ~5 s throttle still applies)":
        "立即重新扫描（CoreWLAN 仍有 ~5 s 限流）",
    "cycle scan sort:  by AP  ↔  by signal":
        "扫描排序切换：按 AP ↔ 按信号",
    "force re-roam (cycle Wi-Fi off/on so the OS re-picks the":
        "重选 AP（关再开 Wi-Fi，让系统重新挑选",
    "strongest BSSID — fixes sticky associations)\n":
        "最强 BSSID —— 解决卡死在弱 AP 的问题）\n",
    "toggle this help": "切换帮助",
    "cycle Nearby view: Wi-Fi BSSIDs → BLE → Bonjour":
        "切换附近视图：Wi-Fi BSSID → BLE → Bonjour",
    "open Wi-Fi basics for SSID, BSSID, channel, band, security":
        "打开 Wi-Fi 基础知识：SSID / BSSID / 信道 / 频段 / 加密",
    "open Wi-Fi / BLE basics glossary":
        "打开 Wi-Fi / BLE 术语表",
    "list cursor — move selection up / down (Wi-Fi / BLE / Bonjour)":
        "列表光标——上下移动选中行（Wi-Fi / BLE / Bonjour 三个视图）",
    "inspect the selected row (open detail modal)":
        "查看选中的行（打开详情）",
    "open the Events browser (filterable list, per-AP σ":
        "打开事件查看器（可过滤列表、各 AP σ",
    "baseline, last-hour σ sparkline)\n":
        "基线、最近一小时 σ 走势）\n",
    "AP aliases (optional)": "AP 别名（可选）",
    "  Drop ./aps.yaml (next to aps.example.yaml in the cloned repo)\n"
    "  listing your APs by management MAC; diting renders friendly\n"
    "  names ('1F-bedroom') in place of MAC fragments ('?af:5e:a7').\n"
    "  Without the file the tool still works — every BSSID gets an\n"
    "  auto-cluster label like '?AB:CD:EF' so radios of the same\n"
    "  physical AP still group together.\n":
        "  在 ./aps.yaml（与 aps.example.yaml 同目录，通常是 clone\n"
        "  出来的仓库根目录）里按管理 MAC 列出你的 AP，diting 会把\n"
        "  MAC 片段（'?af:5e:a7'）显示成可读名字（'1F-书房'）。没有\n"
        "  这份文件也能用 —— 每个 BSSID 会自动获得形如 '?AB:CD:EF' 的\n"
        "  聚簇标签，同一台物理 AP 的所有无线电仍然会被分到同一组。\n",
    "Helper": "辅助进程",
    "Helper bundle": "辅助进程包",
    "Events modal (m)": "事件查看器（m）",
    "BLE view": "BLE 视图",
    "Subcommands": "子命令",
    "(none)": "（无参数）",
    "launch the TUI dashboard (this view)":
        "启动 TUI 仪表盘（即当前视图）",
    "print current connection details and exit":
        "打印当前连接信息并退出",
    "stream events as plain text until Ctrl+C":
        "纯文本输出事件流，Ctrl+C 退出",
    "headless JSONL events for long-runs / Home Assistant":
        "无界面 JSONL 事件流，适合长时运行 / Home Assistant",
    "record an empty-room σ baseline (default 300 s)":
        "采集空房间的 σ 基线（默认 300 秒）",
    "read a JSONL log and print rule-based insights":
        "读取 JSONL 日志，输出基于规则的洞察",
    "monitor (headless event stream)": "monitor（无界面事件流）",
    "Event log (--log) — TUI + monitor share the schema":
        "事件日志（--log） —— TUI 和 monitor 共用同一份 schema",
    "\n"
    "  Adds a background JSONL writer to the normal TUI session.\n"
    "  Same event schema as `diting monitor`, append-mode, line-\n"
    "  buffered + flushed after every event — already-emitted events\n"
    "  survive Ctrl+C, kill, or even an unhandled traceback. Only a\n"
    "  kernel panic / power loss between an event and the next disk\n"
    "  sync window can drop something.\n"
    "\n"
    "  The schema is locale-stable (English keys / values regardless\n"
    "  of DITING_LANG) so log analysis scripts and AI consumers\n"
    "  do not break when you toggle the UI to Chinese. User-supplied\n"
    "  strings — SSID, AP names from aps.yaml — pass through as UTF-8\n"
    "  so a Chinese SSID like 咖啡馆 stays grep-able in the file.\n":
        "\n"
        "  在正常 TUI 会话之上增加一个后台 JSONL 写入器。事件 schema 与\n"
        "  `diting monitor` 一致，append 模式 + 每个事件落盘 ——\n"
        "  Ctrl+C / kill / 异常 traceback 都不会丢已经写入的事件。\n"
        "  只有内核 panic / 断电这种掉电场景才可能丢失刚写还没落盘的数据。\n"
        "\n"
        "  schema 与界面语言无关（无论 DITING_LANG 设置什么，写入文件\n"
        "  的 keys / values 都保持英文），日志分析脚本和 AI 消费方不会\n"
        "  因为 UI 切到中文而失效。用户自定义字符串 —— SSID、aps.yaml 里\n"
        "  的 AP 名字 —— 以 UTF-8 原样写入，中文 SSID 像 咖啡馆 这样的\n"
        "  在文件里仍可直接 grep。\n",
    "\n"
    "  Long-running JSONL stream — one event per line. No TUI, no\n"
    "  cursor movement, safe to redirect / pipe / tail. Events:\n"
    "    link_state    — associate / disassociate (BSSID, SSID)\n"
    "    roam          — band switch or inter-AP roam\n"
    "    rf_stir       — RSSI variance spike with confidence tag\n"
    "    latency_spike — gateway or WAN RTT above threshold\n"
    "    loss_burst    — gateway or WAN probe loss above threshold\n"
    "\n"
    "  Flags:\n"
    "    --out FILE    append JSONL to FILE (line-buffered) instead\n"
    "                  of stdout. Survives session disconnects.\n"
    "    --notify      raise a macOS Notification Centre alert when an\n"
    "                  anomaly fires (rf_stir / latency_spike /\n"
    "                  loss_burst). Per-(event-type, target) silence\n"
    "                  window (default 60 s; DITING_NOTIFY_SILENCE_S).\n"
    "                  rf_stir gated by DITING_NOTIFY_STIR_CONFIDENCE\n"
    "                  (high|medium|all, default high). Also valid on\n"
    "                  the default TUI subcommand: `diting --notify`.\n"
    "    --gateway IP  override gateway probe target. Default: the\n"
    "                  router IP from the active connection.\n"
    "    --wan IP      override WAN probe target. Default: the\n"
    "                  first non-gateway DNS server detected via\n"
    "                  SCDynamicStore. Probe is TCP/53 connect.\n"
    "\n"
    "  Examples:\n"
    "    diting monitor                              # to stdout\n"
    "    diting monitor --out ~/wifi.jsonl --notify  # daemon-ish\n"
    "    diting monitor --gateway 192.168.1.1 --wan 1.1.1.1\n"
    "\n"
    "  Tail-friendly: each line is a self-contained JSON object\n"
    "  with a top-level 'ts' (ISO-8601) and 'type'. Pipe through\n"
    "  jq for filtering: `tail -F wifi.jsonl | jq 'select(.type==\"roam\")'`\n":
        "\n"
        "  长时运行的 JSONL 事件流 —— 每行一个事件。无 TUI、无光标移动，\n"
        "  可安全重定向 / 管道 / tail。事件类型：\n"
        "    link_state    — 关联 / 断开（BSSID、SSID）\n"
        "    roam          — 频段切换或跨 AP 漫游\n"
        "    rf_stir       — RSSI 波动尖峰，带置信度标签\n"
        "    latency_spike — 网关或 WAN 的 RTT 超阈值\n"
        "    loss_burst    — 网关或 WAN 探测丢包超阈值\n"
        "\n"
        "  参数：\n"
        "    --out FILE    将 JSONL 追加到 FILE（行缓冲），而非输出到\n"
        "                  stdout。会话断开后仍持续写入。\n"
        "    --notify      异常事件触发 macOS 通知中心横幅（覆盖 rf_stir /\n"
        "                  latency_spike / loss_burst）。按 (event-type,\n"
        "                  target) 维度做静默窗口（默认 60 s，\n"
        "                  DITING_NOTIFY_SILENCE_S 可覆盖）；rf_stir 按\n"
        "                  DITING_NOTIFY_STIR_CONFIDENCE 阈值过滤\n"
        "                  （high|medium|all，默认 high）。默认 TUI 子\n"
        "                  命令同样支持：`diting --notify`。\n"
        "    --gateway IP  覆盖网关探测目标。默认为当前连接的路由器 IP。\n"
        "    --wan IP      覆盖 WAN 探测目标。默认为通过 SCDynamicStore\n"
        "                  检测到的第一个非网关 DNS。探测使用 TCP/53\n"
        "                  连接握手。\n"
        "\n"
        "  示例：\n"
        "    diting monitor                              # 输出到 stdout\n"
        "    diting monitor --out ~/wifi.jsonl --notify  # 类守护进程\n"
        "    diting monitor --gateway 192.168.1.1 --wan 1.1.1.1\n"
        "\n"
        "  适合 tail：每行是一个独立的 JSON 对象，顶层包含 ts（ISO-8601）\n"
        "  和 type 字段。可用 jq 过滤：\n"
        "  `tail -F wifi.jsonl | jq 'select(.type==\"roam\")'`\n",
    "  Filterable scroll of every event the dashboard has detected:\n"
    "  ROAM (AP switches), STIR (RF disturbance from σ baseline),\n"
    "  LATENCY / LOSS (link probe spikes), LINK (associate /\n"
    "  disassociate). Use 1/2/3/4/0 to filter by category. Below\n"
    "  the list: a per-AP σ table summarising which APs are stable\n"
    "  vs stirring, plus a σ sparkline covering the trailing hour.\n":
        "  仪表盘检测到的所有事件可过滤滚动列表：\n"
        "  ROAM（AP 切换）、STIR（基于 σ 基线的 RF 扰动）、\n"
        "  LATENCY / LOSS（链路探测尖峰）、LINK（关联 / 断开）。\n"
        "  按 1/2/3/4/0 切换过滤。列表下方：各 AP σ 表，标出哪些 AP\n"
        "  稳定 / 哪些抖动，以及最近一小时 σ 走势图。\n",
    "  Toggle with n. Two sections: Connected (system-paired\n"
    "  peripherals you're actively using — keyboards, AirPods, Magic\n"
    "  Trackpad) and Advertising (everything broadcasting nearby).\n"
    "  Vendor / device-class identification uses public Bluetooth SIG\n"
    "  data (manufacturer-IDs, GATT services, member UUIDs) plus\n"
    "  Apple Continuity protocol parsing for AirDrop / AirPods /\n"
    "  Watch pairing / Hotspot etc. RSSI is EMA-smoothed for the\n"
    "  sort key so the row order stops jiggling on packet jitter.\n":
        "  按 n 切换。分两组：已连接（系统配对、正在使用的外设 ——\n"
        "  键盘、AirPods、Magic Trackpad），正在广播（附近所有发广播\n"
        "  的设备）。厂商 / 设备类识别基于公开的 Bluetooth SIG 数据\n"
        "  （manufacturer-ID、GATT 服务、member UUID），以及苹果\n"
        "  Continuity 协议解析（AirDrop / AirPods / Watch 配对 / 热点 等）。\n"
        "  RSSI 用 EMA 平滑后作为排序键，列表行序不再因单包抖动而跳动。\n",
    "  macOS 14.4+ redacts SSID / BSSID in scan results unless the\n"
    "  caller has Location Services granted; CoreBluetooth refuses\n"
    "  to enter poweredOn for processes without Bluetooth grant. A\n"
    "  Terminal-launched Python CLI cannot earn either. The helper\n"
    "  is a tiny Swift .app bundle that can — diting auto-builds\n"
    "  it on first launch, opens it once so macOS shows the prompts,\n"
    "  and from then on shells out to the bundle for unredacted\n"
    "  scan data plus the BLE feed.\n\n"
    "  Build / grant: ./helper/build.sh, then\n"
    "    open helper/diting-tianer.app  (one-time, click Allow).\n"
    "  Leave the bundle in place; do NOT move it to /Applications/\n"
    "  (TCC keys grants by cdhash so a copy forces a re-grant).\n":
        "  macOS 14.4+ 扫描结果里的 SSID / BSSID 会被遮蔽，除非调用者\n"
        "  已获得「定位服务」授权；没有「蓝牙」授权的进程，CoreBluetooth\n"
        "  也不会进入 poweredOn。从终端启动的 Python CLI 拿不到任何一项。\n"
        "  辅助进程是一个小巧的 Swift .app 包 —— 它能 —— diting 首\n"
        "  次启动时自动编译并 open 一次，让 macOS 弹出授权提示，之后所有\n"
        "  扫描和 BLE 数据都通过它拿到完整结果。\n\n"
        "  构建 / 授权：./helper/build.sh，然后\n"
        "    open helper/diting-tianer.app  （一次性，点 Allow 即可）。\n"
        "  让包留在原地；**不要**移动到 /Applications/\n"
        "  （TCC 按 cdhash 记授权，复制 / 移动会强制让你重新授权）。\n",
    "  macOS 14.4+ redacts the SSID and BSSID of every AP in the scan\n"
    "  list to None unless the calling process has Location Services\n"
    "  permission, and a Python CLI launched from Terminal cannot get\n"
    "  on that list. The helper is a tiny Swift `.app` bundle that\n"
    "  can — diting auto-builds and `open`s it once on first launch,\n"
    "  the user clicks Allow in the macOS prompt, and from then on\n"
    "  diting shells out to the bundle's binary for unredacted scan\n"
    "  data. The TCC grant is persistent; the helper window auto-\n"
    "  closes on grant. Without it the Nearby APs panel works but\n"
    "  every row shows '(redacted)' for SSID and BSSID.\n":
        "  macOS 14.4+ 会把扫描列表里所有 AP 的 SSID 和 BSSID 隐藏成\n"
        "  None，除非调用进程拿到了「定位服务」权限；从终端启动的\n"
        "  Python CLI 进不了授权列表。辅助进程是一个极小的 Swift .app\n"
        "  打包，它可以进列表 —— 首次启动时 diting 会自动编译并\n"
        "  `open` 它一次，你在 macOS 弹窗里点 Allow，后续每次扫描\n"
        "  diting 都会调它的二进制拿到未隐藏的数据。授权是持久的，\n"
        "  辅助进程窗口在授权后会自动关闭。没有它，附近 BSSID 面板\n"
        "  仍可工作，但每行 SSID 和 BSSID 会显示为「(已遮蔽)」。\n",
    "Tunables": "可调参数",
    "  DITING_SCAN_INTERVAL=N    seconds between scans, default 7.\n"
    "                                CoreWLAN throttles around 5 s,\n"
    "                                so values below ~6 yield empty\n"
    "                                scans every other call. Min 3.\n"
    "  DITING_INVENTORY=path     override aps.yaml location.\n"
    "  DITING_HELPER=path        override helper.app path.\n"
    "  DITING_LANG=en|zh         override interface language.\n":
        "  DITING_SCAN_INTERVAL=N    扫描间隔（秒），默认 7。\n"
        "                                CoreWLAN 大约 5 秒限流一次，\n"
        "                                低于 ~6 秒时每隔一次返回空。\n"
        "                                最小 3 秒。\n"
        "  DITING_INVENTORY=path     覆盖 aps.yaml 路径。\n"
        "  DITING_HELPER=path        覆盖 helper.app 路径。\n"
        "  DITING_LANG=en|zh         覆盖界面语言。\n",
    "  DITING_SCAN_INTERVAL=N    seconds between Wi-Fi scans,\n"
    "                                default 7. CoreWLAN throttles\n"
    "                                around 5 s; values below ~6\n"
    "                                yield empty scans. Min 3.\n"
    "  DITING_INVENTORY=path     override aps.yaml location.\n"
    "  DITING_HELPER=path        override helper.app path.\n"
    "  DITING_LANG=en|zh         override interface language.\n"
    "  DITING_GATEWAY=ip         override gateway probe target.\n"
    "  DITING_WAN=ip             override WAN probe target\n"
    "                                (default: auto-detected DNS).\n":
        "  DITING_SCAN_INTERVAL=N    Wi-Fi 扫描间隔（秒），默认 7。\n"
        "                                CoreWLAN 大约 5 秒限流一次，\n"
        "                                低于 ~6 秒时每隔一次返回空。\n"
        "                                最小 3 秒。\n"
        "  DITING_INVENTORY=path     覆盖 aps.yaml 路径。\n"
        "  DITING_HELPER=path        覆盖 helper.app 路径。\n"
        "  DITING_LANG=en|zh         覆盖界面语言。\n"
        "  DITING_GATEWAY=ip         覆盖网关探测目标。\n"
        "  DITING_WAN=ip             覆盖 WAN 探测目标\n"
        "                                （默认：自动检测的 DNS）。\n",
    "made by ": "作者：",
    "Esc or h to close": "Esc 或 h 关闭",

    # ---- Basics modal ----
    "Wi-Fi Basics": "Wi-Fi 基础知识",
    "Glossary": "术语表",
    "  ·  the words diting uses in the dashboard\n":
        "  ·  仪表盘里这些术语都是什么意思\n",
    "  ·  every term diting shows in the dashboard\n":
        "  ·  仪表盘里出现的每个术语\n",
    "Wi-Fi": "Wi-Fi",
    "Link health": "链路健康",
    "RF environment": "RF 环境",
    "BLE": "BLE",
    "RSSI / Signal": "RSSI / 信号",
    "Noise / SNR": "Noise / SNR",
    "Band": "频段",
    "Width": "带宽",
    "Security": "加密",
    "Roam": "漫游",
    "Roam score": "漫游评分",
    "The Wi-Fi name people choose from, such as Meituan or Guest. "
    "Many access points can broadcast the same SSID.":
        "Wi-Fi 列表里看到的网络名字，比如 Meituan 或 Guest。"
        "多个接入点可以广播同一个 SSID。",
    "The radio identity behind one SSID on one AP/radio. A single "
    "physical AP may expose many BSSIDs when it broadcasts several "
    "SSIDs on 2.4 GHz and 5 GHz.":
        "一个 AP 上某个 SSID 对应的无线电身份。一台物理 AP 在 "
        "2.4 GHz 和 5 GHz 同时广播多个 SSID 时，会暴露多个 BSSID。",
    "diting's best guess for the physical access point that owns "
    "a BSSID. Names you set in ./aps.yaml (optional, next to "
    "aps.example.yaml in the repo) are most accurate; ? labels are "
    "auto-inferred from MAC address patterns when no aps.yaml entry "
    "matches.":
        "diting 推断的「这个 BSSID 属于哪台物理 AP」。"
        "你在 ./aps.yaml（可选，与仓库里的 aps.example.yaml 同目录）"
        "里配置的名字最准确；找不到匹配条目时，会用以 ? 开头的标签"
        "按 MAC 前缀自动推断。",
    "Received signal strength. Less negative is stronger: -45 dBm is "
    "excellent, -65 dBm is usable, and around -75 dBm is weak.":
        "接收信号强度。负值越接近 0 越强：-45 dBm 极好，-65 dBm 可用，"
        "-75 dBm 左右就偏弱了。",
    "Noise is background radio energy. SNR is signal minus noise; "
    "higher is better. Low SNR can cause retries even when the AP is visible.":
        "噪声是背景无线电能量。SNR（信噪比）= 信号 - 噪声，越高越好。"
        "SNR 偏低时即便看得见 AP 也会频繁重传。",
    "The radio range: 2.4 GHz reaches farther but is crowded; 5 GHz is "
    "faster with shorter range; 6 GHz is newer, cleaner, and shorter range.":
        "频段：2.4 GHz 覆盖远但拥挤；5 GHz 更快但距离短；"
        "6 GHz 较新、较干净，距离也短。",
    "The slice of a band the AP is using. APs on the same or nearby "
    "channels share airtime, so a quieter channel can help.":
        "AP 占用的某段频谱。处在相同或相邻信道上的 AP 会争抢空中时间，"
        "选更空的信道能改善体验。",
    "How much spectrum the AP uses, such as 20/40/80 MHz. Wider can be "
    "faster but also easier to interfere with, especially on 2.4 GHz.":
        "AP 占用的频谱宽度，比如 20/40/80 MHz。带宽越大速度可能更快，"
        "也更容易互相干扰，2.4 GHz 上尤其明显。",
    "OPEN means no Wi-Fi-layer password/encryption. ENT means enterprise "
    "authentication. WPA2/WPA3 are password or modern secured modes.":
        "OPEN 表示 Wi-Fi 层没有密码 / 加密。ENT 表示企业认证。"
        "WPA2 / WPA3 是密码或更现代的加密模式。",
    "When the Mac moves from one BSSID to another. Same SSID does not "
    "guarantee the Mac picked the strongest or best AP.":
        "Mac 从一个 BSSID 切换到另一个的过程。SSID 相同并不保证 "
        "Mac 选中了最强或最合适的 AP。",
    "A simple 0-100 guide, not a standard. It rewards strong RSSI, good "
    "SNR, cleaner bands, and quieter channels, and penalizes weak signal, "
    "busy channels, open networks, and security mismatches. A better "
    "candidate is shown only when the same SSID scores clearly higher.":
        "一个 0-100 的简易参考分，不是标准。RSSI 强、SNR 好、"
        "频段干净、信道空闲会加分；信号弱、信道拥挤、开放网络、"
        "加密类型不一致会扣分。只有同名 SSID 候选明显更高时才会显示。",
    "Esc or b to close": "Esc 或 b 关闭",
    "↑/↓/PgUp/PgDn to scroll  ·  Esc or b to close":
        "↑/↓/PgUp/PgDn 翻屏  ·  Esc 或 b 关闭",
    "↑/↓/PgUp/PgDn to scroll  ·  Esc or h to close":
        "↑/↓/PgUp/PgDn 翻屏  ·  Esc 或 h 关闭",

    # ---- Basics modal: link health ----
    "Latency / RTT": "延迟 / RTT",
    "Loss": "丢包",
    "Jitter": "抖动",
    "WAN reachability": "WAN 可达性",
    "Round-trip time of a probe packet to the gateway (ICMP ping) and "
    "to a public DNS server (TCP/53 connect). Under 50 ms feels snappy, "
    "100–200 ms is OK for most things, > 300 ms hurts video calls.":
        "探测包到网关（ICMP ping）和到公共 DNS（TCP/53 连接）的往返时间。"
        "50 ms 以下很顺滑；100–200 ms 大多数场景能用；超过 300 ms "
        "视频通话会明显卡。",
    "Percentage of probes that did not come back inside the window. "
    "0 % is the only good number; even 1–2 % loss to the gateway is "
    "abnormal on a healthy LAN. WAN loss is more variable.":
        "在采样窗口内没回来的探测包比例。0% 是唯一让人放心的数字 —— "
        "健康内网即便 1–2% 也算异常。WAN 侧丢包波动更大。",
    "Variation in latency between consecutive probes. Calls and games "
    "feel choppy when jitter is high even if average latency is low.":
        "相邻探测之间的延迟变化幅度。即便平均延迟不高，抖动大时通话和"
        "游戏体验仍会卡顿。",
    "diting probes a public DNS server via TCP port 53 (not ICMP) "
    "because many resolvers block ping. A successful TCP handshake "
    "means the WAN path works even when ping is silent.":
        "diting 用 TCP 53 端口探测公共 DNS（不用 ICMP），因为很多 "
        "DNS 服务商会屏蔽 ping。TCP 握手成功就说明 WAN 通了，即便 "
        "ping 不响应。",

    # ---- Basics modal: RF environment ----
    "σ (sigma)": "σ（标准差）",
    "Stir / 扰动": "Stir / 扰动",
    "Co-located vs spatial channel": "同位 AP 与邻信道 AP",
    "Standard deviation of RSSI over a short window. A still room has "
    "low σ (signal barely changes); people walking around or doors "
    "opening push σ up. diting uses σ as the substrate for the "
    "Stir / Environment monitor.":
        "短窗口内 RSSI 的标准差。安静的房间 σ 很低（信号几乎不变）；"
        "人走动、开关门会把 σ 推高。diting 用它作为环境扰动监测的基础。",
    "An event fired when current σ exceeds the AP's running baseline "
    "by ≥3× and clears 5 dB on its own. 'High confidence' if two or "
    "more nearby APs see the spike at the same time; 'medium' alone.":
        "当前 σ 超过该 AP 滚动基线的 ≥3 倍且自身 ≥5 dB 时触发的事件。"
        "如果同一时刻两台及以上邻近 AP 都看到尖峰，标记为「高置信」；"
        "单 AP 单独触发时是「中等」。",
    "Same-room APs (RSSI ≥ −60) form a redundancy group: a stir on "
    "two of them at once gets upgraded to high confidence. Far APs "
    "(RSSI −60 to −85) each act as an independent spatial 'lane'. "
    "Below −85 dBm an AP is too noisy to draw conclusions from.":
        "同房间 AP（RSSI ≥ −60）组成冗余组：两台同时报扰动时会被升级"
        "为「高置信」。较远 AP（−60 到 −85 dBm）各自作为独立的空间「通道」。"
        "弱于 −85 dBm 的 AP 太嘈杂，从中得不出可靠结论。",
    "Stir is correlation, never presence": "扰动是相关性，不是「有人」",
    "A stir says 'something in the RF environment changed' — it does "
    "NOT say 'a person walked by'. A passing person, a neighbour AP "
    "rebooting, your phone refreshing a background scan, and a "
    "moving curtain all produce the same σ spike. Treat the signal "
    "as a hint to look, not a claim about who or what.":
        "扰动事件说的是「RF 环境变了」，不是「有人路过」。路过的人、"
        "重启的邻居 AP、你手机做后台扫描、挪动的窗帘——都会产生同样的"
        " σ 尖峰。把这个信号当成「值得看一眼」的提示，不要当作是谁、"
        "是什么的判断。",

    # ---- Basics modal: BLE ----
    "BSSID rotation / merged N": "BSSID 轮换 / 合并 N",
    "Connected vs Advertising": "已连接 与 正在广播",
    "iBeacon / Eddystone / Tile": "iBeacon / Eddystone / Tile",
    "Find My target / AirTag": "Find My 目标 / AirTag",
    "AirDrop / Hotspot / Watch pairing": "AirDrop / 热点 / Watch 配对",
    "Privacy-preserving devices (most modern phones, AirPods) rotate "
    "their BLE identifier every ~15 min. diting's fuzzy merger "
    "groups rotations of the same vendor + name + signal range as "
    "one row tagged '(merged N)' so the list does not balloon.":
        "保护隐私的设备（多数现代手机、AirPods）每 ~15 分钟轮换一次 "
        "BLE 标识。diting 的模糊合并器把同厂商 + 同名称 + 同信号区间的"
        "轮换实例归为一行，标记为「合并 N」，避免列表爆炸。",
    "Connected: peripherals you're actively using (keyboard, AirPods). "
    "These come from the system Bluetooth stack and rarely change. "
    "Advertising: every device broadcasting nearby; updates every 2 s.":
        "已连接：正在使用的外设（键盘、AirPods 等），来自系统蓝牙栈，"
        "变化很少。正在广播：附近所有发广播包的设备，每 2 秒刷新。",
    "Standardised public-format BLE broadcasts. iBeacon and Eddystone "
    "are commercial location beacons; Tile is a tracker. diting "
    "labels them by parsing the public protocol fields, not by guess.":
        "标准化的公开格式 BLE 广播。iBeacon 和 Eddystone 是商用位置信标，"
        "Tile 是物品追踪器。diting 通过解析公开协议字段识别，不是猜测。",
    "Apple Find My broadcasts. AirTag-class hardware never carries a "
    "name (privacy by design). AirPods and Apple Watch broadcast the "
    "same Find My beacon when away from their owner but DO carry a "
    "name — diting uses the name as the AirTag-vs-rest tiebreaker.":
        "苹果 Find My 广播。AirTag 类硬件按设计绝不带名称（隐私需求）。"
        "AirPods 和 Apple Watch 远离主人时会发送同样的 Find My 信标，"
        "但会携带设备名 —— diting 用 name 是否存在区分二者。",
    "Apple Continuity protocol broadcasts. diting parses the "
    "manufacturer-data type byte to label what intent the device is "
    "broadcasting (AirDrop transfer, Personal Hotspot, Watch unlock "
    "pairing, etc.) — answers 'why is this Apple device chirping?'.":
        "苹果 Continuity 协议广播。diting 解析 manufacturer-data 的 "
        "type 字节，标出设备在广播什么动作（AirDrop 传输、个人热点、"
        "Watch 解锁配对 等）——回答「这台苹果设备到底在嚷什么？」。",
    "(anonymous) vs (unknown)": "(匿名) 与 (未知)",
    "(anonymous) means the broadcast carries zero identifying info — "
    "no manufacturer ID, no service UUIDs, no name. There is nothing "
    "to look up; the device is a privacy beacon by design. (unknown) "
    "means there IS some data but the lookup chain abstained — that "
    "row is actionable: a missing OUI / member UUID / name pattern.":
        "(匿名) 表示广播里完全没有可识别字段——没有 manufacturer ID、"
        "没有服务 UUID、没有名称，本身就是按设计的隐私信标，没东西可查。"
        "(未知) 表示有一些数据但查找链路放弃了识别——这种行是可改进的："
        "缺一个 OUI、缺一个 member UUID、或者缺一条 name pattern。",

    # ---- v0.7.0 Diagnostics rows: Link / Environment ----
    "Link  ": "链路  ",
    "Environment  ": "环境  ",
    "stable": "稳定",
    "active": "活跃",
    "quiet": "安静",
    # RFStirEvent confidence enum — rendered after σ in the events modal
    # (`σ 13.9 dB · medium` → `σ 13.9 dB · 中`). Surfaced by tui-audit.
    "high": "高",
    "medium": "中",
    "low": "低",
    "σ {db} dB / {n}s": "σ {db} dB / {n}s",
    "{loss}% loss": "丢包 {loss}%",
    "WAN {ms} ms": "WAN {ms} ms",
    "jitter {ms} ms": "抖动 {ms} ms",
    "WAN unreachable": "WAN 不可达",
    "(no ICMP reply)": "(ICMP 无响应)",
    "WAN n/a (DNS == gateway)": "WAN n/a (DNS = 网关)",
    "WAN n/a": "WAN n/a",
    "(measuring...)": "(测量中…)",
    "last event {n}s ago": "上次事件 {n}s 前",

    # ---- Unified Events panel + modal ----
    "Events log": "事件日志",
    "[ROAM]": "[漫游]",
    "[STIR]": "[扰动]",
    "[LATENCY]": "[延迟]",
    "[LOSS]": "[丢包]",
    "[LINK]": "[链路]",
    "RF stir at {location}": "{location} 处 RF 扰动",
    "{target} latency spike: {ms} ms": "{target} 延迟尖峰：{ms} ms",
    "{target} loss burst: {loss}%": "{target} 丢包风暴：{loss}%",
    "associated to {ssid}": "已连接至 {ssid}",
    "disassociated": "已断开",
    "Events ({n})": "事件 ({n})",
    "  filter: {mode}": "  过滤：{mode}",
    "all": "全部",
    "roam": "漫游",
    "stir": "扰动",
    "latency": "延迟",
    "loss": "丢包",
    "Per-AP σ baseline": "各 AP 环境稳定度",
    "σ = RSSI stddev; current σ > baseline ×{ratio} (≥{floor} dB) fires [STIR]":
        "σ 是 RSSI 标准差；当前 σ 超过基线 ×{ratio}（且 ≥{floor} dB）时报告 [扰动]",
    "AP": "AP",
    "mode": "模式",
    "BSSIDs": "BSSID",
    "baseline σ": "基线 σ",
    "current σ": "当前 σ",
    "RSSI": "RSSI",
    "status": "状态",
    "co-located": "同位",
    "spatial channel": "邻信道",
    "ignored": "忽略",
    "stirring": "抖动",
    "({n} APs still collecting samples)":
        "({n} 个 AP 仍在采集样本)",
    "Last hour σ sparkline": "最近一小时 σ 走势",
    "data ~{n}m": "数据 ~{n}m",
    "(σ history outside the last hour)":
        "(无最近一小时内的 σ 历史)",
    "Press 1/2/3/4/0 to filter; m or Esc to close":
        "按 1/2/3/4/0 切换过滤；m 或 Esc 关闭",

    # ---- Calibration CLI ----
    "Calibrating environment baseline ({n}s remaining)...":
        "正在采集基线（剩余 {n}s）…",
    "Baseline saved to {path}": "基线已保存至 {path}",
    "Calibration cancelled.": "已取消采集。",
    "No samples captured — leave the radio on a single network and retry.":
        "未采集到样本 —— 保持连在同一个网络后重试。",

    # ---- analyze CLI ----
    "diting analyse {path}": "diting 分析 {path}",
    "Time range: {start} → {end}  ({duration})":
        "时间范围：{start} → {end}  （{duration}）",
    # Inline labels in the RF-stir aggregates block. Trailing spacing
    # padding is left to the caller's f-string so the colon-spacing
    # stays consistent with the catalog key.
    "modes:": "模式：",
    "confidence:": "置信度：",
    "locations:": "位置：",
    "{n} min": "{n} 分钟",
    "{h}h {m}m": "{h}小时{m}分",
    "Total events: {n}": "事件总数：{n}",
    "Latest association: {ssid} @ {bssid}":
        "最近一次关联：{ssid} @ {bssid}",
    "Roam events: {n}  (band switch {b} / inter-AP {i})":
        "漫游事件：{n}  （频段切换 {b} / 跨 AP {i}）",
    "Disassociates: {n}": "断开次数：{n}",
    "RF stir events: {n}": "RF 扰动事件：{n}",
    "  σ range:     {lo} – {hi} dB  (median {p50})":
        "  σ 范围：    {lo} – {hi} dB  （中位 {p50}）",
    "Latency spikes: {n}  ({by})  peak {peak} ms":
        "延迟尖峰：{n}  （{by}）  峰值 {peak} ms",
    "Loss bursts: {n}  peak {pct}%":
        "丢包风暴：{n}  峰值 {pct}%",
    "Insights": "洞察",
    "TODO: ": "待办：",

    "Empty log": "空日志",
    "No JSONL events parsed. Is diting still writing? "
    "Check the path and that the producer is running.":
        "未解析到 JSONL 事件。diting 还在写吗？"
        "检查路径以及生产端是否还在运行。",
    "Re-run with --log on a session that produces events.":
        "用 --log 重启一次能产生事件的会话再分析。",

    "Timezone mismatch in log": "日志时区错位",
    "Adjacent events span an exact-hour gap, which usually "
    "means producer wrote some timestamps as local time "
    "labelled UTC. Versions before the timestamp fix had "
    "this bug.":
        "相邻事件之间隔了整数小时，通常是生产端把本地时间"
        "标成了 UTC。时间戳 bug 修复之前的版本会出现这个问题。",
    "Update diting and re-record. Existing data is still "
    "usable but cross-timezone analysis may misorder events.":
        "升级 diting 后重新记录。已有数据仍然可读，"
        "但跨时区分析时事件顺序可能会乱。",

    "All stir events medium-confidence": "全部扰动事件均为中等置信",
    "Every RF stir landed at medium confidence and on one "
    "AP location ({n} events). With only one co-located AP "
    "diting cannot upgrade events to high confidence — "
    "redundancy fusion needs ≥2 APs in the same room.":
        "全部 {n} 条 RF 扰动均为中等置信，且都来自同一台 AP。"
        "只有一台同位 AP 时，diting 没法升级到高置信 —— "
        "冗余融合需要同房间至少 2 台 AP。",
    "If you want richer presence detection, add a second "
    "AP in the same area on a different channel. Keep your "
    "existing per-floor layout for coverage; add a near "
    "duplicate only where you want the disambiguation.":
        "想要更强的扰动识别，可以在同区域加一台不同信道的 AP。"
        "现有每层一台的部署保留以保覆盖；只在想要更精确判断的"
        "区域增加一台近重叠 AP。",

    "Sustained RF activity": "持续性 RF 活动",
    "{n} stir events with median σ {sigma} dB (range "
    "{lo}–{hi}). Long runs at a similar σ suggest "
    "ongoing motion rather than isolated spikes.":
        "{n} 条扰动事件，σ 中位 {sigma} dB（范围 {lo}–{hi}）。"
        "σ 长时间维持在相近水平，更像是持续活动而非孤立尖峰。",

    "Latency spikes without loss": "延迟尖峰但无丢包",
    "{n} latency spikes fired with zero loss bursts. "
    "Single RTT spikes (router/CPU busy, transient queue, "
    "scan overlap) are different from sustained packet "
    "loss; this set looks like jitter, not link failure.":
        "{n} 次延迟尖峰，丢包风暴为 0。单次 RTT 尖峰"
        "（路由器 CPU 忙、瞬时队列、扫描叠加）与持续性"
        "丢包不是一回事；这批数据看起来是抖动，不是链路故障。",
    "If spikes correlate with stir bursts, the AP may be "
    "doing background scans during high airtime. Disable "
    "auto-channel or lower BLE scan rate on the AP if "
    "available.":
        "如果尖峰与扰动事件在时间上吻合，AP 可能在高空中负载"
        "时跑后台扫描。可以在路由器上关掉自动选信道或降低 BLE "
        "扫描频率（如果支持）。",

    "Real packet loss observed": "出现真正的丢包",
    "{n} loss-burst events (peak {pct}%). This is sustained "
    "loss, not single-packet jitter — investigate before "
    "assuming a transient.":
        "{n} 次丢包风暴（峰值 {pct}%）。这是持续性丢包，"
        "不是单包抖动 —— 别简单当作瞬时问题。",
    "Check the gateway probe target separately from WAN. "
    "Gateway loss → LAN issue (cable, AP overload). WAN "
    "loss only → ISP / upstream issue.":
        "把网关探测和 WAN 探测分开看：网关有丢包 → 内网问题"
        "（线缆、AP 过载）；只有 WAN 丢包 → ISP / 上行问题。",

    "Repeated disassociations": "频繁断开重连",
    "{n} disassociate events. Repeated reconnects within "
    "one session usually mean weak signal at the edge of "
    "an AP's range, mixed PHY/MCS issues, or driver hand-"
    "off problems.":
        "{n} 次断开事件。一个会话里反复重连，通常是处在 AP "
        "覆盖边缘信号弱、PHY/MCS 不一致，或驱动切换有问题。",
    "Look at your roam events to see if the Mac is failing "
    "to find a target, then either move the second AP "
    "closer or enable 802.11k/v on the existing one.":
        "看看漫游事件，确认 Mac 是不是找不到漫游目标。如果是，"
        "要么把第二台 AP 挪近一点，要么在现有 AP 上启用 "
        "802.11k/v。",

    "Mostly band-switch roams": "主要是频段切换式漫游",
    "{n} roams of which {pct}% were band switches "
    "(2.4 ↔ 5 GHz on the same AP). Common sign of an "
    "AP doing aggressive band-steering; no action "
    "needed unless the Mac picks 2.4 too often.":
        "{n} 次漫游里 {pct}% 是频段切换（同一台 AP 的 2.4 ↔ 5 GHz）。"
        "通常是 AP 启用了 band-steering，不需要处理 —— 除非 Mac "
        "经常落到 2.4 GHz。",

    "Frequent inter-AP roams": "频繁跨 AP 漫游",
    "{n} roams, mostly across different APs. Either you "
    "are walking around the building, or APs nearby "
    "have similar enough RSSI that the Mac keeps "
    "switching between them.":
        "{n} 次漫游，主要是跨 AP 切换。要么你在楼里走动，"
        "要么相邻 AP 的 RSSI 太接近导致 Mac 反复切换。",
    "If you weren't moving, check whether two APs "
    "advertise the same SSID with overlapping coverage "
    "and similar TX power. Consider lowering one or "
    "splitting SSIDs.":
        "如果你没走动，看看是不是两台 AP 同 SSID 覆盖重叠"
        "且发射功率相近。可以调低其中一台的功率，或者拆 SSID。",

    "Short observation window": "观测窗口太短",
    "Log spans under 10 minutes. Heuristics that need "
    "trends (RSSI baselines, traffic patterns) will be "
    "noisy on this little data.":
        "日志覆盖不足 10 分钟。需要趋势的判定（RSSI 基线、"
        "流量模式）在这么少的数据上会很不稳。",
    "Re-run with --log over a longer session "
    "(an evening, a workday) for richer signal.":
        "用 --log 跑一个更长的会话（一晚上、一个工作日）以获得"
        "更丰富的数据。",

    "No specific insights — the session looks routine. "
    "Re-run with a longer log or a noisier environment for "
    "richer signal.":
        "没有特别的洞察 —— 会话看起来一切如常。"
        "可以用更长的日志或更嘈杂的环境再跑一次。",

    "diting analyze: no log file given and no "
    "diting-*.jsonl found in the current directory.\n"
    "Pass a path: diting analyze ~/wifi-20260507.jsonl":
        "diting analyze：没指定日志文件，当前目录也没有 "
        "diting-*.jsonl。\n"
        "请提供路径：diting analyze ~/wifi-20260507.jsonl",
    "diting analyze: file not found: {path}":
        "diting analyze：找不到文件：{path}",
    "Network change(s) detected": "检测到网络切换",
    "{n} gateway-IP transition(s) during this session: "
    "{moves}. Treat per-network statistics separately — "
    "stir / latency / loss aggregates pre and post a "
    "network change describe physically different APs.":
        "本次会话出现 {n} 次网关 IP 切换：{moves}。"
        "网络切换前后的 stir / 延迟 / 丢包应分段统计 —— "
        "它们对应的是物理上不同的 AP。",
    "Loss bursts may be probing a stale gateway":
        "丢包风暴可能在探测过期网关",
    "All {n} loss-burst events target {ip}, even though "
    "the session crossed {roams} roam(s). Pre-0.7.0 "
    "versions had a bug where LatencyPoller did not "
    "refresh after a network change, so the probe kept "
    "pinging the previous network's gateway. The flood "
    "of loss bursts is then a measurement artifact, not "
    "real link degradation.":
        "{n} 次丢包风暴全都在探测 {ip}，但会话期间发生了 "
        "{roams} 次漫游。0.7.0 之前的版本有 bug：网络切换后 "
        "LatencyPoller 不会刷新，会一直 ping 旧网关。这种"
        "情况下大量丢包风暴是测量假阳性，不是真正的链路退化。",
    "Update diting and re-record. Post-fix the "
    "LatencyPoller rebuilds on every gateway-IP change "
    "and emits an explicit network_change event.":
        "升级 diting 后重新记录。修复版本会在每次网关 IP 变化"
        "时重建 LatencyPoller，并显式发出 network_change 事件。",
}
