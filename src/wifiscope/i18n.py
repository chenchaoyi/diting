"""Static-at-launch i18n for the wifiscope TUI / CLI.

Two languages: English (default) and Simplified Chinese. The active
language is decided once at process start and does not change
afterwards — CJK character widths affect column-aligned tables, and
re-laying out the whole TUI mid-session is more risk than value.

Resolution order (first hit wins):

    1. Explicit `--lang {en,zh}` on the CLI
    2. ``WIFISCOPE_LANG=zh`` environment variable
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
    explicit = (src.get("WIFISCOPE_LANG") or "").strip().lower()
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
    "Re-roam": "断开重连",
    "View": "视图",  # legacy; kept for command-palette / Ctrl+P
    "Toggle Wi-Fi / BLE view": "切换 Wi-Fi / BLE 视图",
    "→ {view}": "→ {view}",
    "Help": "帮助",
    "Basics": "基础知识",
    "Close": "关闭",

    # ---- header subtitle ----
    "sort: {mode}": "排序：{mode}",
    "scan {n}s": "扫描频率 {n}s",
    "PAUSED": "已暂停",
    "ap": "AP",
    "signal": "信号",
    "view: {mode}": "视图：{mode}",
    "wifi": "Wi-Fi",
    "ble": "BLE",

    # ---- Connection panel ----
    "not associated": "未连接",
    "(unknown)": "(未知)",
    "  · country {cc}": "  · 区码 {cc}",
    "Channel": "信道",
    "PHY / Sec": "PHY / 加密",
    "Tx / Max": "Tx / Max",
    "{tx}  /  {max} max": "{tx}  /  {max} 最大",
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
    "WiFi off → on — reconnecting via auto-join (2-5 s)":
        "WiFi 关 → 开，正在通过自动加入重连（2-5 秒）",
    "no WiFi interface": "未发现 WiFi 网卡",

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
    "Closest  ": "最近  ",
    "(none)": "(无)",
    "(anonymous)": "(匿名)",
    "? {n}": "? {n}",
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
    "last seen": "最近",
    "id": "ID",
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
    "Handoff": "接力 Handoff",
    "Tethering target": "热点共享端",
    "Tethering source": "热点客户端",
    "Nearby Action": "附近动作",

    # ---- CLI --help ----
    "usage: wifiscope [--lang en|zh] [SUBCOMMAND]\n"
    "\n"
    "  (no args)   launch the TUI dashboard (default)\n"
    "  once        print the current connection and exit\n"
    "  watch       stream events as plain text until Ctrl+C\n"
    "  monitor     headless JSONL events (long-runs / Home Assistant)\n"
    "              flags: --out FILE  --notify  --gateway IP  --wan IP\n"
    "  calibrate   record an empty-room RSSI baseline (default 300 s)\n"
    "              flags: --duration SECONDS\n"
    "  --lang L    interface language: en, zh. Defaults to WIFISCOPE_LANG,\n"
    "              then to the system locale (zh_* → zh, anything else → en).\n"
    "  -h, --help  show this message\n":
        "用法：wifiscope [--lang en|zh] [子命令]\n"
        "\n"
        "  (无参数)    启动 TUI 仪表盘（默认）\n"
        "  once        打印当前连接快照后退出\n"
        "  watch       以纯文本流式输出事件，直到 Ctrl+C\n"
        "  monitor     无 TUI 长时运行，逐行 JSONL 事件\n"
        "              选项：--out FILE  --notify  --gateway IP  --wan IP\n"
        "  calibrate   采集「房间没人」基线（默认 300 秒）\n"
        "              选项：--duration SECONDS\n"
        "  --lang L    界面语言：en、zh。默认读 WIFISCOPE_LANG，\n"
        "              再退到系统 locale（zh_* → zh，其余 → en）。\n"
        "  -h, --help  显示本说明\n",
    "wifiscope: unknown subcommand {cmd!r}":
        "wifiscope：未知子命令 {cmd!r}",

    # ---- `wifiscope once` plain-text output ----
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

    # ---- `wifiscope watch` plain-text banner ----
    "backend: {name}  (Ctrl+C to quit)": "后端：{name}  (Ctrl+C 退出)",
    "inventory: {n_aps} APs, {n_overrides} overrides — {path}":
        "清单：{n_aps} 台 AP，{n_overrides} 条覆盖 — {path}",

    # ---- TUI launch flow: helper auto-build / grant prompts ----
    "note: wifiscope-helper not found and could not be built.\n"
    "      Scan list will be TCC-redacted. To fix, install the\n"
    "      Swift toolchain (Xcode CLT) and rerun, or build helper/\n"
    "      manually. See README's helper section.":
        "提示：未找到 wifiscope-helper，且自动构建失败。\n"
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
    " rerun wifiscope after granting to see unredacted scan.)":
        "({n} 秒内未授权，TUI 仍将启动。\n"
        " 授权后重新运行 wifiscope 即可看到未隐藏的扫描数据。)",
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
    " permissions did land. Rerun wifiscope after granting to\n"
    " unlock the remaining views.)":
        "({n} 秒内未全部授权，TUI 仍将以当前已有的权限启动。\n"
        " 授权完整之后重新运行 wifiscope 即可解锁剩余视图。)",
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
    "{n} open/no-password BSSIDs": "{n} 个 BSSID 无密码",
    "{n} wide 2.4 GHz BSSIDs": "{n} 个 2.4 GHz 宽带 BSSID",
    "{n} other BSSIDs on your channel": "本机信道上还有 {n} 个 BSSID",
    "mixed country codes nearby": "附近区码混合",
    "No obvious environment warnings from the scan.":
        "扫描未发现明显环境异常。",

    # ---- Diagnostics: recommendations line ----
    "Least crowded channels  ": "最空闲信道  ",
    "Estimated from the scan.": "按扫描结果估算。",
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
    "  press c to re-roam": "  按 c 断开重连",

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
    "  ·  terminal WiFi monitor for macOS, focused on roaming visibility.\n":
        "  ·  macOS 终端 Wi-Fi 监控工具，专注于漫游可见性。\n",
    "What": "概览",
    "  See which AP you are on, when your Mac switches, and how strong\n"
    "  the signal is — the things macOS hides from its own WiFi panel.\n":
        "  看清你的 Mac 连在哪个 AP、什么时候切换、信号到底有多强 ——\n"
        "  这些都是 macOS 自带 Wi-Fi 面板不会告诉你的信息。\n",
    "Panels": "面板",
    "current AP, signal bar, link / IP / radio details":
        "当前 AP、信号条、链路 / IP / 无线参数",
    "every BSSID in range, grouped by physical AP":
        "范围内所有 BSSID，按物理 AP 分组",
    "band-switch and inter-AP roam events as they happen":
        "频段切换与跨 AP 漫游事件实时记录",
    "Bindings": "按键",
    "quit": "退出",
    "pause / resume polling": "暂停 / 恢复轮询",
    "force a rescan now (CoreWLAN ~5s throttle still applies)":
        "立即重新扫描（CoreWLAN 仍有 ~5s 限流）",
    "cycle scan sort:  by AP  ↔  by signal":
        "扫描排序切换：按 AP ↔ 按信号",
    "force re-roam (cycle WiFi off/on so the OS re-picks the":
        "断开重连（关再开 Wi-Fi，让系统重新挑选",
    "strongest BSSID — fixes sticky associations)\n":
        "最强 BSSID —— 解决卡死在弱 AP 的问题）\n",
    "toggle this help": "打开 / 关闭本帮助",
    "toggle Nearby view: Wi-Fi BSSIDs ↔ BLE devices":
        "切换附近视图：Wi-Fi BSSID ↔ BLE 设备",
    "open Wi-Fi basics for SSID, BSSID, channel, band, security":
        "打开 Wi-Fi 基础知识：SSID / BSSID / 信道 / 频段 / 加密",
    "AP aliases (optional)": "AP 别名（可选）",
    "  Drop ./aps.yaml (next to aps.example.yaml in the cloned repo)\n"
    "  listing your APs by management MAC; wifiscope renders friendly\n"
    "  names ('1F-bedroom') in place of MAC fragments ('?af:5e:a7').\n"
    "  Without the file the tool still works — every BSSID gets an\n"
    "  auto-cluster label like '?AB:CD:EF' so radios of the same\n"
    "  physical AP still group together.\n":
        "  在 ./aps.yaml（与 aps.example.yaml 同目录，通常是 clone\n"
        "  出来的仓库根目录）里按管理 MAC 列出你的 AP，wifiscope 会把\n"
        "  MAC 片段（'?af:5e:a7'）显示成可读名字（'1F-书房'）。没有\n"
        "  这份文件也能用 —— 每个 BSSID 会自动获得形如 '?AB:CD:EF' 的\n"
        "  聚簇标签，同一台物理 AP 的所有无线电仍然会被分到同一组。\n",
    "Helper": "辅助进程",
    "  macOS 14.4+ redacts the SSID and BSSID of every AP in the scan\n"
    "  list to None unless the calling process has Location Services\n"
    "  permission, and a Python CLI launched from Terminal cannot get\n"
    "  on that list. The helper is a tiny Swift `.app` bundle that\n"
    "  can — wifiscope auto-builds and `open`s it once on first launch,\n"
    "  the user clicks Allow in the macOS prompt, and from then on\n"
    "  wifiscope shells out to the bundle's binary for unredacted scan\n"
    "  data. The TCC grant is persistent; the helper window auto-\n"
    "  closes on grant. Without it the Nearby APs panel works but\n"
    "  every row shows '(redacted)' for SSID and BSSID.\n":
        "  macOS 14.4+ 会把扫描列表里所有 AP 的 SSID 和 BSSID 隐藏成\n"
        "  None，除非调用进程拿到了「定位服务」权限；从终端启动的\n"
        "  Python CLI 进不了授权列表。辅助进程是一个极小的 Swift .app\n"
        "  打包，它可以进列表 —— 首次启动时 wifiscope 会自动编译并\n"
        "  `open` 它一次，你在 macOS 弹窗里点 Allow，后续每次扫描\n"
        "  wifiscope 都会调它的二进制拿到未隐藏的数据。授权是持久的，\n"
        "  辅助进程窗口在授权后会自动关闭。没有它，附近 BSSID 面板\n"
        "  仍可工作，但每行 SSID 和 BSSID 会显示为「(已遮蔽)」。\n",
    "Tunables": "可调参数",
    "  WIFISCOPE_SCAN_INTERVAL=N    seconds between scans, default 7.\n"
    "                                CoreWLAN throttles around 5 s,\n"
    "                                so values below ~6 yield empty\n"
    "                                scans every other call. Min 3.\n"
    "  WIFISCOPE_INVENTORY=path     override aps.yaml location.\n"
    "  WIFISCOPE_HELPER=path        override helper.app path.\n"
    "  WIFISCOPE_LANG=en|zh         override interface language.\n":
        "  WIFISCOPE_SCAN_INTERVAL=N    扫描间隔（秒），默认 7。\n"
        "                                CoreWLAN 大约 5 秒限流一次，\n"
        "                                低于 ~6 秒时每隔一次返回空。\n"
        "                                最小 3 秒。\n"
        "  WIFISCOPE_INVENTORY=path     覆盖 aps.yaml 路径。\n"
        "  WIFISCOPE_HELPER=path        覆盖 helper.app 路径。\n"
        "  WIFISCOPE_LANG=en|zh         覆盖界面语言。\n",
    "made by ": "作者：",
    "Esc or h to close": "Esc 或 h 关闭",

    # ---- Basics modal ----
    "Wi-Fi Basics": "Wi-Fi 基础知识",
    "  ·  the words wifiscope uses in the dashboard\n":
        "  ·  仪表盘里这些术语都是什么意思\n",
    "RSSI / Signal": "RSSI / 信号",
    "Noise / SNR": "Noise / SNR",
    "Band": "频段",
    "Width": "带宽",
    "Security": "加密",
    "Roam": "漫游",
    "Roam score": "漫游评分",
    "The Wi-Fi name people choose from, such as Meituan or Guest. "
    "Many access points can broadcast the same SSID.":
        "用户在 Wi-Fi 列表里看到的网络名字，比如 Meituan 或 Guest。"
        "多个接入点可以广播同一个 SSID。",
    "The radio identity behind one SSID on one AP/radio. A single "
    "physical AP may expose many BSSIDs when it broadcasts several "
    "SSIDs on 2.4 GHz and 5 GHz.":
        "一个 AP 上某个 SSID 对应的无线电身份。一台物理 AP 在 "
        "2.4 GHz 和 5 GHz 同时广播多个 SSID 时，会暴露多个 BSSID。",
    "wifiscope's best guess for the physical access point that owns "
    "a BSSID. Names you set in ./aps.yaml (optional, next to "
    "aps.example.yaml in the repo) are most accurate; ? labels are "
    "auto-inferred from MAC address patterns when no aps.yaml entry "
    "matches.":
        "wifiscope 推断的「这个 BSSID 属于哪台物理 AP」。"
        "你在 ./aps.yaml（可选，与仓库里的 aps.example.yaml 同目录）"
        "里配置的名字最准确；找不到匹配条目时，会用以 ? 开头的标签"
        "按 MAC 模式自动猜测。",
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

    # ---- v0.7.0 Diagnostics rows: Link / Environment ----
    "Link  ": "链路  ",
    "Environment  ": "环境  ",
    "stable": "稳定",
    "active": "活跃",
    "quiet": "安静",
    "σ {db} dB / {n}s": "σ {db} dB / {n}s",
    "{loss}% loss": "丢包 {loss}%",
    "WAN {ms} ms": "WAN {ms} ms",
    "jitter {ms} ms": "抖动 {ms} ms",
    "WAN unreachable": "WAN 不可达",
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
    "σ = RSSI stddev; current σ over baseline ×3 fires [STIR]":
        "σ 是 RSSI 抖动；当前 σ 超过基线 ×3 时报告 [扰动]",
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
}
