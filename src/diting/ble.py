"""Async BLE scanning layer.

Spawns the Swift helper's ``ble-scan`` subcommand, reads its JSONL
stdout in the background, and emits :class:`BLEScanUpdate` snapshots
on a fixed cadence. The TUI consumes the snapshots like
:class:`diting.poller.WiFiPoller` consumes Wi-Fi events — different
sources, same async-iterator shape.

The poller is responsible for:

- maintaining a rolling map ``{identifier: BLEDevice}`` of every
  advertisement seen,
- resolving the manufacturer-data company-ID prefix to a vendor name
  via the bundled Bluetooth SIG snapshot,
- expiring entries unseen for more than ``ttl_s`` seconds (default 30,
  reflecting macOS-side ad coalescing — most active devices repeat
  every few seconds),
- folding rotated-UUID duplicates into a single row using a
  fuzzy-merge over (vendor_id, name, recent RSSI window).

Permission failures are surfaced cleanly: the helper exits with code 3
and a JSON ``{"error": "..."}`` line; the poller flips
``permission_state`` to ``"denied"`` and keeps yielding empty
snapshots so the TUI's BLE panel can render its "(BLE permission
required)" placeholder without crashing.

Subprocess crashes (e.g. SIGKILL during a system Bluetooth restart)
are treated similarly: future snapshots are empty; no exception
bubbles up.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import BLEDeviceLeftEvent, BLEDeviceSeenEvent


# ---------- public dataclasses ----------

@dataclass(frozen=True, slots=True)
class BLEDevice:
    """One BLE peripheral as currently understood by the poller.

    ``identifier`` is the CoreBluetooth per-host UUID, lower-cased.
    Modern devices rotate this UUID for privacy, so the same physical
    device can appear under multiple identifiers over time. The
    fuzzy merger in :func:`merge_for_display` collapses such cases by
    matching on ``(vendor_id, name)`` plus an RSSI tolerance window;
    when entries fold, ``merged_count`` exceeds 1 and the renderer
    shows a ``(merged N)`` badge.

    Schema-3 (v0.6.0+) optional fields:

    - ``type`` is the helper's public-format detection result —
      ``"iBeacon"``, ``"AirTag"``, ``"Eddystone-URL"``, ``"Tile"``,
      ``"SmartTag"``, ``"Swift Pair"``, etc. None when the device's
      advertisement is not in any well-documented format.
    - ``device_class`` is the Apple Nearby Info device-class nibble
      decoded into ``"iPhone"`` / ``"iPad"`` / ``"Mac"`` / ``"Apple
      TV"`` / ``"HomePod"`` / ``"Apple Watch"``. None for non-Apple
      devices and for Apple devices not advertising Nearby Info.
    - ``is_connected`` is True for entries that came from the helper's
      ``retrieveConnectedPeripherals`` snapshot (your AirPods, Magic
      Keyboard, etc., which are not advertising and so otherwise
      invisible to the BLE panel). Connected entries have no RSSI
      reading and are sorted alphabetically by name in the panel.
    """

    identifier: str
    name: str | None
    vendor: str | None
    vendor_id: int | None
    services: tuple[str, ...]
    rssi_dbm: int | None
    is_connectable: bool
    first_seen: datetime
    last_seen: datetime
    ad_count: int
    merged_count: int = 1
    type: str | None = None
    device_class: str | None = None
    is_connected: bool = False
    # Exponential-moving-average RSSI used as the *sort* key in the
    # panel so a 5–15 dB single-packet jitter (normal for BLE) does
    # not cause neighbouring rows to swap on every snapshot. Display
    # still uses ``rssi_dbm`` because the user wants to see the live
    # value, not a smoothed one. ``None`` until at least one valid
    # RSSI sample arrives; matches ``rssi_dbm`` for the very first
    # sample so the first render is not artificially weighted.
    rssi_smooth: int | None = None
    # Schema-4 (v0.8.0+) raw advertisement-data passthrough. Empty / None
    # for older helpers. Plumbed through so downstream payload decoders
    # (sensor data, Eddystone, MiBeacon, Govee, SwitchBot) can run
    # against the raw bytes without re-implementing a CoreBluetooth
    # bridge in Python.
    #
    # Manufacturer-specific data, hex-encoded. The first 2 bytes are
    # the SIG company ID (little-endian, mirrors ``vendor_id``); the
    # remainder is vendor-specific payload. Helper emits this when the
    # advertisement carries ``CBAdvertisementDataManufacturerDataKey``.
    manufacturer_hex: str | None = None
    # ``service_data`` is a tuple of (uuid_string, hex_bytes) pairs
    # rather than a dict so the dataclass stays frozen + hashable. Keys
    # are CBUUID strings as emitted by the helper (16-bit short like
    # "FEAA" or 128-bit canonical like "FD5A0000-..."); values are the
    # raw payload as hex, matching ``manufacturer_hex``'s encoding.
    service_data: tuple[tuple[str, str], ...] = ()
    # CoreBluetooth's ``CBAdvertisementDataTxPowerLevelKey``: the
    # transmitter's reported tx power in dBm. Consumers can derive a
    # rough distance from ``tx_power_dbm − rssi_dbm``.
    tx_power_dbm: int | None = None
    # ``CBAdvertisementDataSolicitedServiceUUIDsKey`` — services the
    # peripheral wants to be connected for. Useful for HID / Find My
    # peer-discovery rows that omit primary service UUIDs.
    solicited_service_uuids: tuple[str, ...] = ()
    # ``CBAdvertisementDataOverflowServiceUUIDsKey`` — UUIDs that
    # didn't fit in the primary 31-byte adv frame. Apple Continuity
    # secondary advertisements land here.
    overflow_service_uuids: tuple[str, ...] = ()


class BLEHistory:
    """Per-device rolling RSSI sample buffer.

    BLEDevice is a frozen dataclass with one current reading per
    field; tracking history requires a separate, mutable container.
    Each ``identifier`` gets a deque of ``(timestamp, rssi_dbm)``
    pairs capped at ``maxlen`` samples — enough to draw a 30-sample
    sparkline in the detail modal without growing unbounded over a
    multi-hour session.

    Devices that drop out of the snapshot are pruned via
    :meth:`expire` so a long session of churning random-MAC
    advertisers does not leak history forever.
    """

    def __init__(self, *, maxlen: int = 60) -> None:
        from collections import deque
        self._samples: dict[str, "deque[tuple[datetime, int]]"] = {}
        self._maxlen = maxlen
        self._deque = deque  # closed over for ``record``

    def record(
        self, identifier: str, ts: datetime, rssi_dbm: int | None,
    ) -> None:
        """Append one sample to the device's history.

        ``rssi_dbm = None`` is silently dropped — connected
        peripherals from IOBluetoothDevice never get an RSSI
        reading and would otherwise pollute the buffer with
        sentinel values. The cap is enforced by the deque, so old
        samples roll off the front as new ones arrive.
        """
        if rssi_dbm is None:
            return
        buf = self._samples.get(identifier)
        if buf is None:
            buf = self._deque(maxlen=self._maxlen)
            self._samples[identifier] = buf
        buf.append((ts, rssi_dbm))

    def get(self, identifier: str) -> list[tuple[datetime, int]]:
        """Return a copy of the history for ``identifier``.

        Empty list if we have nothing — the renderer treats that
        the same as "device just appeared, no signal yet".
        """
        return list(self._samples.get(identifier, ()))

    def expire(self, keep_ids: set[str]) -> None:
        """Drop history for identifiers not in ``keep_ids``.

        Called once per snapshot in the App. Without this a
        scenario where a busy office churns through 200 distinct
        random-MAC iPhones in an hour would accumulate 200
        deques worth of stale history we will never render.
        """
        for ident in list(self._samples.keys()):
            if ident not in keep_ids:
                del self._samples[ident]


def is_silent_device(d: BLEDevice) -> bool:
    """True iff the device's broadcast carries zero identifying info.

    A "silent" beacon transmits only RSSI and a connectable flag — no
    manufacturer_id, no service UUIDs, no localName, no Apple Continuity
    type byte, no Nearby-Info device class. There is literally nothing
    in the advertisement payload that any decoder can resolve, so the
    UI distinguishes ``(anonymous)`` (truly silent) from ``(unknown)``
    (vendor lookup chain failed but at least something was broadcast).
    """
    return (
        d.vendor is None
        and d.vendor_id is None
        and not d.services
        and not d.name
        and not d.type
        and not d.device_class
    )


@dataclass(frozen=True, slots=True)
class BLEScanUpdate:
    """One pass of currently-visible BLE devices.

    ``permission_state`` summarises the helper's reachability:

    - ``"granted"``  — at least one ad parsed successfully
    - ``"denied"``   — helper reported ``"bluetooth unauthorized"`` or
      exited with code 3
    - ``"unavailable"`` — the helper binary could not be spawned
    - ``"unknown"``  — initial state before the first event

    ``devices`` is the advertising list, post-merge, sorted by RSSI
    desc. ``connected`` is a parallel list of currently-connected
    peripherals (AirPods you're listening to, Magic Keyboard you're
    typing on) that the OS knows about but that are not advertising.
    Connected entries skip the fuzzy-merger (no RSSI, no UUID rotation).
    """

    devices: list[BLEDevice]
    permission_state: str
    connected: list[BLEDevice] = field(default_factory=list)


# ---------- vendor lookup ----------

_VENDORS_PATH = Path(__file__).resolve().parent / "data" / "bluetooth_vendors.json"


def load_vendors(path: Path | None = None) -> dict[int, str]:
    """Load the bundled Bluetooth-SIG company-ID → vendor-name map.

    The file ships in ``src/diting/data/bluetooth_vendors.json`` and
    is regenerated by ``make update-vendors``. ``_meta`` is filtered
    out. A missing or unreadable file yields an empty dict — vendor
    resolution then falls through to ``None`` and the UI shows the
    raw company ID.
    """
    if path is None:
        path = _VENDORS_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    for k, v in data.items():
        if k == "_meta":
            continue
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


def lookup_vendor(company_id: int | None, vendors: dict[int, str]) -> str | None:
    """Resolve a Bluetooth SIG company ID to a vendor name, or None."""
    if company_id is None:
        return None
    return vendors.get(company_id)


# ---------- IEEE OUI lookup (for connected peripherals) ----------
#
# Connected peripherals come from IOBluetoothDevice (system BT stack) and
# do not carry the manufacturer_data field that the advertising path
# uses for vendor resolution — we only have the device's BT MAC. Match
# the first 3 octets against a curated subset of the IEEE OUI registry
# instead. The bundled JSON covers Apple comprehensively (a Mac is most
# likely to have Apple peripherals connected) plus the major consumer
# Bluetooth vendors; anything else stays unknown.

_OUIS_PATH = Path(__file__).resolve().parent / "data" / "bluetooth_ouis.json"
_OUIS_MA_M_PATH = (
    Path(__file__).resolve().parent / "data" / "bluetooth_ouis_ma_m.json"
)
_OUIS_MA_S_PATH = (
    Path(__file__).resolve().parent / "data" / "bluetooth_ouis_ma_s.json"
)


def load_ouis(path: Path | None = None) -> dict[str, str]:
    """Load the bundled IEEE OUI prefix → vendor-name map.

    Keys are normalised to ``aa:bb:cc`` (lower-case, colon-separated 3
    octets). ``_meta`` is filtered out. A missing / unreadable file
    yields an empty dict; vendor lookup then falls through to None.
    """
    if path is None:
        path = _OUIS_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(k).lower(): str(v)
        for k, v in data.items()
        if k != "_meta" and isinstance(v, str)
    }


def load_ouis_layered(
    *,
    ma_l_path: Path | None = None,
    ma_m_path: Path | None = None,
    ma_s_path: Path | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Load all three IEEE OUI tiers as ``(ma_l, ma_m, ma_s)`` dicts.

    Each tier is loaded independently via ``load_ouis()``; missing
    or unreadable files yield empty dicts for that tier so the
    downstream lookup degrades gracefully through the remaining
    tiers.

    Key shapes:

    - MA-L: ``aa:bb:cc`` (24-bit, 3 colon-separated bytes)
    - MA-M: ``aa:bb:cc:d`` (28-bit, 3 bytes + 1 nibble)
    - MA-S: ``aa:bb:cc:dd:e`` (36-bit, 4 bytes + 1 nibble)
    """
    return (
        load_ouis(ma_l_path or _OUIS_PATH),
        load_ouis(ma_m_path or _OUIS_MA_M_PATH),
        load_ouis(ma_s_path or _OUIS_MA_S_PATH),
    )


def _split_mac_octets(identifier: str) -> list[str] | None:
    """Tokenize a MAC string into 6 zero-padded 2-hex-char octets.

    Handles all of:

    - colon-separated full form: ``38:09:fb:0b:be:60``
    - dash-separated full form: ``38-09-fb-0b-be-60``
    - colon-separated with stripped leading zeros (macOS ``arp -an``
      convention): ``24:f:9b:29:c:56`` → octets ``["24","0f","9b","29","0c","56"]``
    - no-separator: ``3809fb0bbe60``

    Returns ``None`` for inputs that don't parse cleanly. Callers
    rely on this normalisation to key into the IEEE registry, which
    is keyed by full 2-hex-char octets.
    """
    if not identifier:
        return None
    # Normalise separator to ":" so dash + colon both work.
    s = identifier.replace("-", ":").lower()
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 6:
            return None
        out: list[str] = []
        for p in parts:
            if not p or len(p) > 2:
                return None
            if any(c not in "0123456789abcdef" for c in p):
                return None
            out.append(p.zfill(2))
        return out
    # No-separator form: must be exactly 12 hex chars.
    if len(s) != 12 or any(c not in "0123456789abcdef" for c in s):
        return None
    return [s[i : i + 2] for i in range(0, 12, 2)]


def lookup_oui_vendor(
    identifier: str | None,
    ouis: dict[str, str] | None = None,
    *,
    ma_l: dict[str, str] | None = None,
    ma_m: dict[str, str] | None = None,
    ma_s: dict[str, str] | None = None,
) -> str | None:
    """Resolve a BT / LAN MAC to a vendor name via the IEEE registry.

    Two calling conventions are supported:

    - **Legacy single-tier**: ``lookup_oui_vendor(mac, ouis)`` — treats
      ``ouis`` as the MA-L (24-bit) map. Preserved so existing call
      sites and tests keep working.
    - **Layered**: ``lookup_oui_vendor(mac, ma_l=…, ma_m=…, ma_s=…)``
      tries the longest prefix first (36 → 28 → 24 bits). First
      match wins. Missing / empty dicts are skipped silently.

    Tolerant of all common MAC separators (``:``, ``-``, none) AND
    of stripped leading zeros per octet (macOS ``arp -an`` displays
    `00:19` as `0:19`, `0f:9b` as `f:9b`, etc.). The tokenizer pads
    every octet to 2 hex chars before keying.
    """
    octets = _split_mac_octets(identifier) if identifier else None
    if octets is None:
        return None

    # Legacy single-tier call: positional ``ouis`` was supplied AND
    # the layered kwargs were NOT used. Behave exactly as before
    # except for the now-correct zero-padded octet handling.
    if ouis is not None and ma_l is None and ma_m is None and ma_s is None:
        prefix = f"{octets[0]}:{octets[1]}:{octets[2]}"
        return ouis.get(prefix)

    # Layered lookup. Resolve ma_l from `ouis` if the caller passed
    # ouis positionally alongside layered kwargs (uncommon but legal).
    resolved_ma_l = ma_l if ma_l is not None else (ouis if ouis is not None else {})
    resolved_ma_m = ma_m if ma_m is not None else {}
    resolved_ma_s = ma_s if ma_s is not None else {}

    ma_l_key = f"{octets[0]}:{octets[1]}:{octets[2]}"
    if resolved_ma_s:
        key_36 = f"{ma_l_key}:{octets[3]}:{octets[4][0]}"
        hit = resolved_ma_s.get(key_36)
        if hit:
            return hit
    if resolved_ma_m:
        key_28 = f"{ma_l_key}:{octets[3][0]}"
        hit = resolved_ma_m.get(key_28)
        if hit:
            return hit
    return resolved_ma_l.get(ma_l_key)


# ---------- service category inference ----------

# 16-bit Bluetooth SIG GATT service UUIDs the user is likely to recognise.
# These hand-curated names take priority over the upstream SIG names —
# the SIG label for 0x1812 is "Human Interface Device" but every keyboard
# user we have ever met calls it "HID". Anything missed here falls
# through to the bundled SIG GATT-services map, then to the bundled
# member-UUID map, then to the raw UUID. The names route through
# i18n.t() at the call site so the Chinese UI translates them.
_SERVICE_CATEGORY: dict[str, str] = {
    "180D": "Heart Rate",
    "1812": "HID",
    "1124": "HID Keyboard",
    "1108": "Audio",
    "110A": "Audio",
    "110B": "Audio",
    "110C": "Audio",
    "110D": "Audio",
    "110E": "Audio",
    "110F": "Audio",
    "111E": "Audio",
    "FE9F": "Find My",
    "FD5A": "Find My",
}

# Standard Bluetooth SIG base UUID; 16-bit short codes embed at chars 4-7
# of the 32-char form. macOS sometimes reports the long form, sometimes
# the short — normalise so the lookup always sees the 16-bit code.
_BASE_TAIL = "00001000800000805F9B34FB"


def _normalize_uuid(uuid: str) -> str:
    u = uuid.upper().replace("-", "")
    if len(u) == 32 and u.endswith(_BASE_TAIL) and u.startswith("0000"):
        return u[4:8]
    return u


# ---------- bundled SIG UUID tables (GATT services + member UUIDs) ----------

_GATT_SERVICES_PATH = (
    Path(__file__).resolve().parent / "data" / "bluetooth_gatt_services.json"
)
_MEMBER_UUIDS_PATH = (
    Path(__file__).resolve().parent / "data" / "bluetooth_member_uuids.json"
)


def _load_uuid_table(path: Path) -> dict[str, str]:
    """Load a 4-char hex-keyed JSON table; ``_meta`` filtered out."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(k).upper(): str(v)
        for k, v in data.items()
        if k != "_meta" and isinstance(v, str)
    }


def load_gatt_services(path: Path | None = None) -> dict[str, str]:
    """Load the bundled SIG 16-bit GATT service UUID → name map.

    Source: ``assigned_numbers/uuids/service_uuids.yaml``. Regenerate
    with ``make update-vendors``. A missing file is tolerated and
    yields an empty dict; UUIDs then fall through to the raw value.
    """
    return _load_uuid_table(path or _GATT_SERVICES_PATH)


def load_member_uuids(path: Path | None = None) -> dict[str, str]:
    """Load the bundled SIG 16-bit member-assigned UUID → company map.

    Source: ``assigned_numbers/uuids/member_uuids.yaml``. Each entry
    is a UUID the SIG handed out to one company (e.g. FDAA → Xiaomi).
    Used both for the service column ("Xiaomi service") and as a
    vendor fallback when the device's advertisement omits the
    manufacturer-data company-ID.
    """
    return _load_uuid_table(path or _MEMBER_UUIDS_PATH)


# Name-pattern → vendor inference. Last-resort fallback for the
# real-world cases where a device broadcasts a recognisable brand
# string in its localName field but either (a) carries no
# manufacturer-data company-id, (b) uses a private / unassigned
# cid the SIG hasn't published, or (c) only carries vendor-private
# 128-bit service UUIDs we cannot map. Examples observed in real
# Mac scans: a Jabra Elite 8 Active broadcasting cid 14666 (not
# in SIG's public list); a Mi Smart Band 6 broadcasting only a
# private 128-bit service UUID; a MOMAX charger broadcasting only
# its localName. Patterns are anchored at the start of the name
# (^) for high-precision brand identification — substring match
# would over-claim ("Apple-Pie-Recipe" should not vendor-resolve
# to Apple).
_NAME_PATTERN_VENDORS: tuple[tuple[str, str], ...] = (
    # Audio
    (r"^LE-Jabra\b", "Jabra (GN Audio)"),
    (r"^Jabra\b", "Jabra (GN Audio)"),
    (r"^Galaxy Buds\b", "Samsung"),
    (r"^Galaxy Watch\b", "Samsung"),
    (r"^Galaxy ", "Samsung"),
    (r"^WH-\d", "Sony"),                 # Sony WH-1000XM, etc
    (r"^WF-\d", "Sony"),                 # Sony WF earbuds
    (r"^LE_WH-\d", "Sony"),              # LE-prefixed variant
    (r"^Bose\b", "Bose"),
    (r"^Beats\b", "Apple (Beats)"),
    (r"^Sennheiser\b", "Sennheiser"),
    (r"^JBL\b", "JBL (Harman)"),
    (r"^UGREEN\b", "UGREEN"),
    (r"^Anker\b", "Anker"),
    (r"^Soundcore\b", "Anker (Soundcore)"),
    # Wearables / fitness
    (r"^Mi (Smart )?Band\b", "Xiaomi"),
    (r"^Mi Watch\b", "Xiaomi"),
    (r"^Redmi (Watch|Buds)\b", "Xiaomi (Redmi)"),
    (r"^Polar\b", "Polar Electro Oy"),
    (r"^H10\b", "Polar Electro Oy"),
    (r"^Fitbit\b", "Google (Fitbit)"),
    (r"^Garmin\b", "Garmin"),
    (r"^OURA\b", "Oura"),
    (r"^Forerunner\b", "Garmin"),
    (r"^Versa\b", "Google (Fitbit)"),
    # Phones / tablets that surface a useful name
    (r"^iPhone\b", "Apple, Inc."),
    (r"^iPad\b", "Apple, Inc."),
    (r"^MacBook\b", "Apple, Inc."),
    (r"^Mac mini\b", "Apple, Inc."),
    # Apple peripherals — patterns are NOT anchored, so user-renamed
    # variants like "ccy's Magic Keyboard" still match. The tokens
    # are distinctive enough that false positives are unlikely.
    (r"\bMagic Keyboard\b", "Apple, Inc."),
    (r"\bMagic Mouse\b", "Apple, Inc."),
    (r"\bMagic Trackpad\b", "Apple, Inc."),
    (r"\bAirPods\b", "Apple, Inc."),
    (r"\bApple Watch\b", "Apple, Inc."),
    (r"\bApple TV\b", "Apple, Inc."),
    (r"\bAirPort\b", "Apple, Inc."),
    (r"\bHomePod\b", "Apple, Inc."),
    (r"^HUAWEI\b", "Huawei"),
    (r"^Honor\b", "Honor"),
    (r"^OPPO\b", "OPPO"),
    (r"^OnePlus\b", "OnePlus"),
    (r"^vivo\b", "vivo"),
    (r"^realme\b", "realme"),
    # Charging accessories
    (r"^MOMAX\b", "MOMAX"),
    (r"^Anker\b", "Anker"),
    (r"^UGREEN\b", "UGREEN"),
    (r"^Belkin\b", "Belkin"),
    # Printers
    (r"^HP-\w", "HP"),
    (r"^Printer_\w", "Printer (unknown)"),
    (r"^Brother\b", "Brother"),
    (r"^Canon\b", "Canon"),
    (r"^EPSON\b", "EPSON"),
    # Misc smart-home / IoT brands
    (r"^Tile\b", "Tile, Inc."),
    (r"^Chipolo\b", "Chipolo"),
    (r"^Tracker\b", None),  # too generic; placeholder for future curation
    (r"^Yeelight\b", "Xiaomi (Yeelight)"),
    (r"^Aqara\b", "Aqara (Lumi)"),
    (r"^Mijia\b", "Xiaomi (Mijia)"),
)


def lookup_name_vendor(name: str | None) -> str | None:
    """Heuristic vendor inference from a localName prefix.

    Last-resort path when manufacturer-data and member-UUID lookups
    have both abstained. Pattern-matching is fragile by definition
    — a renamed AirPods called ``"Mi Earbuds"`` would falsely
    resolve to Xiaomi — but in practice the patterns hit
    high-confidence brand-prefix conventions every audio /
    wearable / charging accessory follows. Returns None when no
    pattern fires.
    """
    if not name:
        return None
    for pattern, vendor in _NAME_PATTERN_VENDORS:
        if vendor is None:
            continue
        # Use search rather than match so patterns without a leading
        # ``^`` anchor can fire on substrings — `Magic Keyboard` shows
        # up in user-renamed peripherals like "ccy's Magic Keyboard"
        # which a strict prefix match would miss. Patterns that DO want
        # to anchor at the start keep their explicit ``^``.
        if re.search(pattern, name, re.IGNORECASE):
            return vendor
    return None


# Curated 128-bit member UUIDs that SIG has assigned to vendors but
# that we cannot collapse to a 4-char short form via _normalize_uuid
# (their tail is not the BLE base UUID). Without this table, Mi Band /
# Huami devices broadcasting `5A310100-0000-0000-0000-000000000000`
# would land in the (unknown) bucket because the bundled member-UUID
# JSON only carries 16-bit short keys.
_LONG_MEMBER_UUIDS: dict[str, str] = {
    # Anhui Huami — Mi Band 3+, Amazfit, Zepp
    "5A310100000000000000000000000000": "Anhui Huami Information Technology Co., Ltd.",
    "5A310200000000000000000000000000": "Anhui Huami Information Technology Co., Ltd.",
    "5A310300000000000000000000000000": "Anhui Huami Information Technology Co., Ltd.",
}


def lookup_member_vendor(
    services: tuple[str, ...] | list[str],
    member_uuids: dict[str, str],
) -> str | None:
    """Resolve a vendor name from the first member UUID in ``services``.

    Used as a fallback when ``manufacturer_id`` is absent. Returns the
    SIG-listed company name verbatim ("Xiaomi Inc.", "Sony Mobile
    Communications") so it sits next to manufacturer-derived vendors
    in the UI without flicker.
    """
    if not member_uuids:
        return None
    for s in services:
        if not isinstance(s, str):
            continue
        short = _normalize_uuid(s)
        # 16-bit shortform first (covers the bulk of SIG assignments)
        name = member_uuids.get(short)
        if name:
            return name
        # 128-bit fallback: a small handful of vendor-prefix UUIDs that
        # SIG assigned but bluetooth_member_uuids.json doesn't carry
        # because the file only contains 16-bit shortform keys.
        name = _LONG_MEMBER_UUIDS.get(short)
        if name:
            return name
    return None


# Protocol-utility GATT services advertised by virtually every BLE
# peripheral with bonding. They are legitimate per-row "Services"
# labels but pollute the aggregate Categories diagnostic — see
# bluetooth-scanning spec § "Categories diagnostic SHALL exclude
# protocol-utility GATT services" (caught by the 2026-05-11 audit
# run when "Device Information 20" led the office BLE Categories row).
_PROTOCOL_UTILITY_SERVICES = frozenset({
    "1800",  # Generic Access
    "1801",  # Generic Attribute
    "180A",  # Device Information
})


def _ble_service_categories(dev: "BLEDevice") -> tuple[str, ...]:
    """Resolve a BLEDevice's service UUIDs to friendly category labels.

    Used by the transition-event emitters so a `BLEDeviceSeenEvent`
    can carry `service_categories=("HID",)` or `("HID", "Battery")`.
    Filters out protocol-utility services (Generic Access etc.) the
    way the BLE diagnostics row does. Returns an empty tuple when
    the device advertises no resolvable services.
    """
    cats: list[str] = []
    for uuid in dev.services:
        cat = service_category(uuid, category_only=True)
        if cat and cat not in cats:
            cats.append(cat)
    return tuple(cats)


def service_category(
    uuid: str,
    *,
    gatt: dict[str, str] | None = None,
    member: dict[str, str] | None = None,
    category_only: bool = False,
) -> str | None:
    """Map a service UUID to a user-readable category, or pass through.

    Resolution order:
      1. Hand-curated ``_SERVICE_CATEGORY`` (project-specific friendly
         names like "HID" instead of "Human Interface Device").
      2. ``gatt`` (full SIG 16-bit GATT services list — Battery,
         Device Information, Environmental Sensing, etc.). When
         ``category_only`` is True, the three protocol-utility
         services in ``_PROTOCOL_UTILITY_SERVICES`` (Generic Access,
         Generic Attribute, Device Information) are filtered out —
         they aren't device kinds, so the Categories breakdown
         shouldn't count them.
      3. ``member`` (SIG-assigned member UUIDs — FDAA → Xiaomi,
         FD2A → Sony Corporation, etc.). Skipped when
         ``category_only`` is True; the member layer surfaces a
         vendor (company) name, not a service-class label, so
         callers building a "what kind of devices are around" list
         (the BLE diagnostics Categories row) should not consult
         it. Callers labelling the per-row services column DO want
         it as a last-resort vendor hint.
      4. Raw UUID as last resort, or ``None`` when ``category_only``
         is True and nothing in layers 1–2 matched.

    ``gatt`` and ``member`` default to the bundled tables when
    omitted; tests can pass empty dicts to verify the hand-curated
    layer in isolation.
    """
    short = _normalize_uuid(uuid)
    hit = _SERVICE_CATEGORY.get(short)
    if hit is not None:
        return hit
    if gatt is None:
        gatt = load_gatt_services()
    hit = gatt.get(short)
    if hit is not None:
        if category_only and short in _PROTOCOL_UTILITY_SERVICES:
            return None
        return hit
    if category_only:
        # Strict mode for the Categories breakdown: vendor names
        # from the member-UUID layer would dilute the count,
        # which is meant to read as device-class buckets only.
        return None
    if member is None:
        member = load_member_uuids()
    hit = member.get(short)
    if hit is not None:
        return hit
    return short


# ---------- public-format detection ----------

# Bluetooth SIG company IDs we branch on for deep identification.
_COMPANY_APPLE = 0x004C
_COMPANY_MICROSOFT = 0x0006
_COMPANY_SAMSUNG = 0x0075


def _normalize_service_uuids(obj: dict[str, Any]) -> set[str]:
    raw = obj.get("service_uuids") or []
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for s in raw:
        if isinstance(s, str):
            out.add(_normalize_uuid(s))
    return out


def _apple_nearby_info_device_class(action_byte: int) -> str | None:
    """Map the high nibble of the Apple Nearby Info action byte to a
    device class name. Lower-nibble bits are activity / status flags
    we ignore. Mapping comes from the public ``furiousMAC/continuity``
    reference; per-model precision is impossible from this byte alone.
    """
    nibble = (action_byte >> 4) & 0x0F
    return {
        0x1: "iPhone",
        0x2: "iPad",
        0x4: "Mac",
        0x6: "Apple TV",
        0x7: "HomePod",
        0x9: "Apple Watch",
    }.get(nibble)


# Apple Continuity protocol type-byte → human-readable label, sourced
# from the public ``furiousMAC/continuity`` reverse-engineering. We
# only label types whose meaning is stable across iOS versions; the
# encrypted payload tail is ignored. Resolves the bulk of the
# "Apple, Inc. (unknown)" rows users see in the BLE panel — Apple
# devices broadcast Continuity packets without ever populating the
# advertisement's local-name field, so without this map the row has
# no name to show.
_APPLE_CONTINUITY_TYPE: dict[int, str] = {
    0x05: "AirDrop",
    0x07: "AirPods",
    0x09: "AirPlay target",
    0x0A: "AirPlay source",
    0x0B: "Watch pairing",
    0x0C: "Handoff",
    0x0D: "Tethering target",
    0x0E: "Tethering source",
    0x0F: "Nearby Action",
    # 0x16 — "Proximity Pair Encrypted" / accessory proximity
    # broadcast, observed at high density in real Mac scans
    # (~30% of unlabelled Apple rows in the dogfood capture). The
    # exact semantics are not fully documented but the type byte
    # itself is stable; surface a generic label rather than
    # leaving the row blank.
    0x16: "Apple Proximity",
}


# Microsoft Cross Device Platform (CDP) protocol type byte. Public
# Microsoft docs and the broadcast-protocol reverse-engineering
# community describe at least these two types. We previously only
# decoded 0x03 (Swift Pair); 0x01 is the general device-discovery
# beacon used by Phone Link / Nearby Sharing — common in any
# office with Windows laptops nearby and significant in real-Mac
# captures (every Surface/Windows machine in earshot).
_MS_CDP_TYPE: dict[int, str] = {
    0x01: "MS device beacon",
    0x03: "Swift Pair",
}


def detect_advertisement(obj: dict[str, Any]) -> tuple[str | None, str | None]:
    """Classify an advertisement payload into (type, device_class).

    Mirrors ``helper/Sources/diting-tianer/main.swift:BLEAdParser.detect``.
    Used by :func:`update_from_line` as a fallback when the helper does
    not emit ``type`` / ``device_class`` (older schema-2 bundles), and
    as the deterministic, hermetic algorithm surface that the Python
    test suite exercises directly without needing a Swift toolchain.

    The detector is deliberately conservative — it only labels devices
    whose formats are publicly documented (Tier 1 in the spec). Anything
    outside those returns ``(None, None)``; the panel falls back to
    vendor + service-category for those rows.
    """
    services = _normalize_service_uuids(obj)
    company_id = obj.get("manufacturer_id")
    if isinstance(company_id, bool) or not isinstance(company_id, int):
        company_id = None

    mfg_hex = obj.get("manufacturer_hex")
    mfg_bytes: bytes | None = None
    if isinstance(mfg_hex, str):
        try:
            mfg_bytes = bytes.fromhex(mfg_hex)
        except ValueError:
            mfg_bytes = None

    # 1. Manufacturer-data branches first — disambiguates FD5A (Apple
    #    Find My vs Samsung SmartTag) before service-UUID rules fire.
    if mfg_bytes is not None and company_id is not None:
        if company_id == _COMPANY_APPLE and len(mfg_bytes) >= 3:
            type_byte = mfg_bytes[2]
            if type_byte == 0x02:
                return "iBeacon", None
            if type_byte == 0x10:
                dc = None
                if len(mfg_bytes) >= 6:
                    dc = _apple_nearby_info_device_class(mfg_bytes[5])
                return None, dc
            if type_byte == 0x12:
                # Owner-paired AirTag payloads are ~25 bytes, but
                # AirPods Pro and other Find My-capable peripherals
                # broadcast similar-length packets when away from
                # their owner. The cheap discriminator that holds:
                # AirTags never broadcast a localName (privacy-by-
                # design), while AirPods / Watches do. So if the
                # advertisement carries a name we drop to the more
                # general "Find My target" label rather than guessing
                # "AirTag" and getting it wrong on AirPods Pro.
                has_name = isinstance(obj.get("name"), str) and bool(
                    obj.get("name")
                )
                is_airtag = len(mfg_bytes) >= 25 and not has_name
                return ("AirTag" if is_airtag else "Find My target"), None
            label = _APPLE_CONTINUITY_TYPE.get(type_byte)
            if label is not None:
                return label, None
        if company_id == _COMPANY_MICROSOFT and len(mfg_bytes) >= 3:
            label = _MS_CDP_TYPE.get(mfg_bytes[2])
            if label is not None:
                return label, None
        if company_id == _COMPANY_SAMSUNG and "FD5A" in services:
            return "SmartTag", None

    # 2. Service-UUID-based detections (after manufacturer rules so a
    #    Samsung SmartTag advertising FD5A is labelled correctly).
    if "FEAA" in services:
        return "Eddystone", None
    if "FEED" in services or "FEEC" in services:
        return "Tile", None
    if "FD5A" in services:
        return "Find My target", None

    return None, None


# ---------- line parsing ----------

def _build_device(
    obj: dict[str, Any],
    *,
    vendors: dict[int, str],
    prior: BLEDevice | None,
    now: datetime | None = None,
    member_uuids: dict[str, str] | None = None,
) -> BLEDevice | None:
    """Promote one decoded advertisement object into a BLEDevice.

    ``prior`` carries forward ``first_seen`` and ``ad_count`` when the
    same identifier has been seen before; otherwise the device is new.
    Returns None if the object lacks a usable ``id`` field.
    """
    identifier = obj.get("id")
    if not isinstance(identifier, str):
        return None
    identifier = identifier.lower()

    name = obj.get("name") if isinstance(obj.get("name"), str) else None
    if name is None and prior is not None:
        # macOS sometimes drops the local-name field on subsequent
        # advertisements from the same device. Carry the prior name
        # forward rather than blanking the row mid-session.
        name = prior.name

    rssi_raw = obj.get("rssi_dbm")
    rssi: int | None
    if isinstance(rssi_raw, bool):
        rssi = None
    elif isinstance(rssi_raw, (int, float)):
        rssi = int(rssi_raw)
    else:
        rssi = None
    # CoreBluetooth's documented "RSSI unavailable" sentinel is 127, and
    # any non-negative value is implausible for received signal strength.
    # The new helper filters this out at the source, but we keep a
    # defensive check here so older helper bundles or unusual data paths
    # cannot leak the sentinel through and corrupt RSSI-sorted lists or
    # the diagnostic-panel Closest line.
    if rssi is not None and (rssi >= 0 or rssi < -200):
        rssi = None

    # Exponential moving average for the sort key. α = 0.4 weights the
    # latest packet enough to react to genuine movement (the user
    # walking with their phone) within ~3 advertisements, while
    # damping the 5–15 dB single-packet jitter that BLE radios produce
    # at rest. The first observed RSSI seeds the smoothed value so a
    # device's first appearance sorts in its real bucket immediately.
    if rssi is None:
        rssi_smooth = prior.rssi_smooth if prior is not None else None
    elif prior is not None and prior.rssi_smooth is not None:
        rssi_smooth = int(round(0.4 * rssi + 0.6 * prior.rssi_smooth))
    else:
        rssi_smooth = rssi

    is_connectable = bool(obj.get("is_connectable", False))

    services_raw = obj.get("service_uuids") or []
    if isinstance(services_raw, list):
        services = tuple(s for s in services_raw if isinstance(s, str))
    else:
        services = ()
    if not services and prior is not None:
        services = prior.services

    vendor_id_raw = obj.get("manufacturer_id")
    vendor_id: int | None
    if isinstance(vendor_id_raw, bool):
        vendor_id = None
    elif isinstance(vendor_id_raw, (int, float)):
        vendor_id = int(vendor_id_raw)
    else:
        vendor_id = None
    # macOS / CoreBluetooth interleaves primary advertisements (which
    # carry manufacturer-specific data) with scan-response packets that
    # commonly omit it. Without this carry-forward the vendor_id flickers
    # between e.g. 76 (Apple) and None across consecutive callbacks for
    # the same device, which makes the vendor column flap and — more
    # importantly — fragments merge_for_display's (vendor_id, name)
    # bucketing across UUID rotations, breaking the (merged N) feature
    # in the exact case it is meant to address.
    if vendor_id is None and prior is not None:
        vendor_id = prior.vendor_id
    vendor = lookup_vendor(vendor_id, vendors)
    # Fallback: if the advertisement has no manufacturer ID but does
    # carry a SIG-assigned member UUID, use the company that owns
    # that UUID. Resolves rows that would otherwise show "(unknown)"
    # for known vendors like SIANA Systems / Audiodo / etc.
    if vendor is None and services:
        if member_uuids is None:
            member_uuids = load_member_uuids()
        vendor = lookup_member_vendor(services, member_uuids)
    # Schema-4 fallback: many vendors (Xiaomi MiBeacon FE95, Google
    # Fast Pair FCF1, Microsoft Find My FDEE) advertise their UUID
    # only inside ``service_data`` keys, leaving ``service_uuids``
    # empty. Those devices were unresolvable until we plumbed
    # service_data through. The dict keys ARE service UUIDs in the
    # SIG sense, so the same member-UUID table applies.
    if vendor is None:
        sd_keys: list[str] = []
        raw_sd = obj.get("service_data")
        if isinstance(raw_sd, dict):
            sd_keys = [k for k in raw_sd.keys() if isinstance(k, str)]
        if sd_keys:
            if member_uuids is None:
                member_uuids = load_member_uuids()
            vendor = lookup_member_vendor(tuple(sd_keys), member_uuids)
    if vendor is None and name:
        # Last resort before giving up: pattern-match the localName
        # against known brand prefixes. Catches the common real-Mac
        # cases where a device broadcasts a recognisable name but
        # either uses a private cid (Jabra Elite 8 Active broadcasts
        # cid 14666 which SIG hasn't published) or carries no
        # manufacturer-data at all (Mi Smart Band only emits a
        # localName + vendor-private 128-bit service UUID).
        vendor = lookup_name_vendor(name)
    if vendor is None and prior is not None:
        # Same flicker-protection as vendor_id: a scan-response packet
        # without manufacturer data should not blank out a name we
        # already established for this device on a prior advertisement.
        vendor = prior.vendor

    if now is None:
        now = datetime.now(timezone.utc)
    first_seen = prior.first_seen if prior is not None else now
    ad_count = prior.ad_count + 1 if prior is not None else 1

    # Schema-3 fields (helper-supplied) win over Python-side detection;
    # the latter exists for back-compat with schema-2 bundles and as a
    # testable mirror of the Swift parser. Carry forward from prior so
    # that a scan-response line that omits these fields does not blank
    # out a label we already established.
    raw_type = obj.get("type")
    raw_dc = obj.get("device_class")
    detect_type: str | None = raw_type if isinstance(raw_type, str) else None
    detect_dc: str | None = raw_dc if isinstance(raw_dc, str) else None
    if detect_type is None and detect_dc is None:
        detect_type, detect_dc = detect_advertisement(obj)
    if detect_type is None and prior is not None:
        detect_type = prior.type
    if detect_dc is None and prior is not None:
        detect_dc = prior.device_class

    # Schema-4 raw passthrough fields. Same flicker-protection as the
    # other optional fields: a scan-response packet that omits these
    # carries the prior values forward rather than blanking them.
    raw_mfg_hex = obj.get("manufacturer_hex")
    if isinstance(raw_mfg_hex, str) and raw_mfg_hex:
        mfg_hex: str | None = raw_mfg_hex
    else:
        mfg_hex = prior.manufacturer_hex if prior is not None else None

    raw_svc_data = obj.get("service_data")
    if isinstance(raw_svc_data, dict):
        service_data = tuple(
            (k, v) for k, v in raw_svc_data.items()
            if isinstance(k, str) and isinstance(v, str)
        )
    else:
        service_data = ()
    if not service_data and prior is not None:
        service_data = prior.service_data

    raw_tx = obj.get("tx_power_dbm")
    if isinstance(raw_tx, bool):
        tx_power: int | None = None
    elif isinstance(raw_tx, (int, float)):
        tx_power = int(raw_tx)
    else:
        tx_power = None
    if tx_power is None and prior is not None:
        tx_power = prior.tx_power_dbm

    raw_solicited = obj.get("solicited_service_uuids")
    if isinstance(raw_solicited, list):
        solicited = tuple(s for s in raw_solicited if isinstance(s, str))
    else:
        solicited = ()
    if not solicited and prior is not None:
        solicited = prior.solicited_service_uuids

    raw_overflow = obj.get("overflow_service_uuids")
    if isinstance(raw_overflow, list):
        overflow = tuple(s for s in raw_overflow if isinstance(s, str))
    else:
        overflow = ()
    if not overflow and prior is not None:
        overflow = prior.overflow_service_uuids

    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor=vendor,
        vendor_id=vendor_id,
        services=services,
        rssi_dbm=rssi,
        rssi_smooth=rssi_smooth,
        is_connectable=is_connectable,
        first_seen=first_seen,
        last_seen=now,
        ad_count=ad_count,
        type=detect_type,
        device_class=detect_dc,
        manufacturer_hex=mfg_hex,
        service_data=service_data,
        tx_power_dbm=tx_power,
        solicited_service_uuids=solicited,
        overflow_service_uuids=overflow,
    )


def _build_connected_device(
    obj: dict[str, Any],
    *,
    prior: BLEDevice | None,
    ouis: dict[str, str] | None = None,
    now: datetime | None = None,
) -> BLEDevice | None:
    """Promote a `{"connected": true, ...}` line into a BLEDevice.

    The advertisement-side ``manufacturer_id`` is unavailable here (the
    helper sources connected rows from IOBluetoothDevice, not from a
    BLE scan), so ``vendor_id`` always stays None. Vendor itself is
    looked up from the BT MAC's OUI prefix when we can — that's the
    only public-data path we have, and it cleanly identifies Apple's
    own peripherals (Magic Keyboard / Trackpad / Mouse / AirPods) plus
    the major third-party headphone / accessory vendors. ``type`` /
    ``device_class`` stay blank — those come from advertisement byte
    parsing which is not run on connected entries.
    """
    identifier = obj.get("id")
    if not isinstance(identifier, str):
        return None
    identifier = identifier.lower()

    name = obj.get("name") if isinstance(obj.get("name"), str) else None
    if name is None and prior is not None:
        name = prior.name

    services_raw = obj.get("service_uuids") or []
    if isinstance(services_raw, list):
        services = tuple(s for s in services_raw if isinstance(s, str))
    else:
        services = ()
    if not services and prior is not None:
        services = prior.services

    vendor: str | None = None
    if ouis:
        vendor = lookup_oui_vendor(identifier, ouis)
    # Connected-side name-pattern fallback. Magic Keyboard / AirPods /
    # MX Master / etc. arriving over IOBluetooth with a name but no
    # OUI-table hit can still resolve via brand-prefix matching.
    if vendor is None and name:
        vendor = lookup_name_vendor(name)
    if vendor is None and prior is not None:
        vendor = prior.vendor

    if now is None:
        now = datetime.now(timezone.utc)
    first_seen = prior.first_seen if prior is not None else now

    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor=vendor,
        vendor_id=None,
        services=services,
        rssi_dbm=None,
        is_connectable=True,
        first_seen=first_seen,
        last_seen=now,
        ad_count=0,
        is_connected=True,
    )


def update_from_line(
    devices: dict[str, BLEDevice],
    line: str,
    *,
    vendors: dict[int, str],
    now: datetime | None = None,
    connected: dict[str, BLEDevice] | None = None,
    ouis: dict[str, str] | None = None,
    member_uuids: dict[str, str] | None = None,
) -> str | None:
    """Apply one JSONL line to the device map, in place.

    The optional ``connected`` dict, when supplied, is a parallel store
    for ``retrieveConnectedPeripherals`` snapshots. Connected entries
    skip ``devices`` entirely — they have no RSSI, no UUID rotation, no
    fuzzy-merge involvement, and a different lifecycle (pruned by the
    helper's ``connected_snapshot`` sentinel rather than by TTL). When
    ``connected`` is None, ``connected:true`` and ``connected_snapshot``
    lines are silently dropped — preserves the schema-2 caller surface.

    Returns:
        - ``"permission_denied"`` if the line was a permission error
          from the helper.
        - ``"error"`` if the line was a non-permission error.
        - ``None`` for any other case (valid advertisement, valid
          connected line, valid snapshot sentinel, or malformed line).
    """
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if "error" in obj:
        err = str(obj.get("error", "")).lower()
        if "unauthor" in err:
            return "permission_denied"
        return "error"

    # Connected-snapshot sentinel: the helper just finished one round
    # of retrieveConnectedPeripherals; prune entries whose IDs are not
    # in the supplied id list. An empty list means "no connected
    # peripherals right now" — clear the dict entirely.
    if obj.get("connected_snapshot") is True:
        if connected is None:
            return None
        ids_raw = obj.get("ids") or []
        if not isinstance(ids_raw, list):
            return None
        keep = {str(i).lower() for i in ids_raw if isinstance(i, str)}
        for key in list(connected.keys()):
            if key not in keep:
                del connected[key]
        return None

    # Connected-peripheral row: route to the parallel dict and never
    # the advertising one.
    if obj.get("connected") is True:
        if connected is None:
            return None
        identifier = obj.get("id")
        if not isinstance(identifier, str):
            return None
        key = identifier.lower()
        prior = connected.get(key)
        device = _build_connected_device(obj, prior=prior, ouis=ouis, now=now)
        if device is not None:
            connected[key] = device
        return None

    identifier = obj.get("id")
    if not isinstance(identifier, str):
        return None
    key = identifier.lower()
    prior = devices.get(key)
    device = _build_device(
        obj, vendors=vendors, prior=prior, now=now,
        member_uuids=member_uuids,
    )
    if device is not None:
        devices[key] = device
    return None


# ---------- expiry + fuzzy merge ----------

def expire_devices(
    devices: dict[str, BLEDevice],
    *,
    now: datetime,
    ttl_s: float,
) -> dict[str, BLEDevice]:
    """Return a new map with entries last-seen earlier than ``ttl_s``
    seconds before ``now`` removed.
    """
    return {
        k: v for k, v in devices.items()
        if (now - v.last_seen).total_seconds() <= ttl_s
    }


def merge_for_display(
    devices: list[BLEDevice],
    *,
    rssi_window_db: int = 10,
) -> list[BLEDevice]:
    """Fold rotated-UUID duplicates per the spec's fuzzy-merge rule.

    Two records with the same ``(vendor_id, name)`` whose RSSIs sit
    within ``±rssi_window_db`` of one another are merged into a single
    representative device. ``ad_count`` is summed; ``merged_count``
    records how many entries collapsed.

    Devices with both ``vendor_id`` and ``name`` blank are never
    merged — the heuristic is too risky on anonymous advertisers (the
    spec calls this out under "lightweight, transparent").
    """
    out: list[BLEDevice] = []
    bucket_groups: dict[tuple[int | None, str | None], list[BLEDevice]] = {}
    unmergeable: list[BLEDevice] = []
    for d in devices:
        if d.vendor_id is None and d.name is None:
            unmergeable.append(d)
            continue
        bucket_groups.setdefault((d.vendor_id, d.name), []).append(d)

    # Use the smoothed RSSI for both clustering and final sort so the
    # row order is stable across snapshots. Falling back to rssi_dbm
    # keeps tests written against a single-packet device working,
    # since they never observe the EMA seed-and-update cycle.
    def _key(d: BLEDevice) -> int:
        if d.rssi_smooth is not None:
            return d.rssi_smooth
        if d.rssi_dbm is not None:
            return d.rssi_dbm
        return -200

    for group in bucket_groups.values():
        remaining = sorted(group, key=_key, reverse=True)
        while remaining:
            anchor = remaining[0]
            anchor_rssi = _key(anchor)
            cluster = [anchor]
            kept: list[BLEDevice] = []
            for d in remaining[1:]:
                if abs(_key(d) - anchor_rssi) <= rssi_window_db:
                    cluster.append(d)
                else:
                    kept.append(d)
            out.append(_fold_cluster(cluster) if len(cluster) > 1 else anchor)
            remaining = kept

    out.extend(unmergeable)
    out.sort(key=_key, reverse=True)
    return out


def _fold_cluster(cluster: list[BLEDevice]) -> BLEDevice:
    """Combine cluster members into one merged BLEDevice.

    The strongest-RSSI entry serves as the representative; service
    UUIDs are unioned in first-seen order, ad_count is summed, and
    first/last seen span the union. Identifier is taken from the
    strongest entry — the rest are by definition rotated views of
    "the same thing", so any of them is as good as another.
    """
    primary = max(
        cluster,
        key=lambda d: (
            d.rssi_smooth if d.rssi_smooth is not None
            else (d.rssi_dbm if d.rssi_dbm is not None else -200)
        ),
    )
    seen: set[str] = set()
    services: list[str] = []
    for d in cluster:
        for s in d.services:
            if s not in seen:
                seen.add(s)
                services.append(s)
    return replace(
        primary,
        services=tuple(services),
        ad_count=sum(d.ad_count for d in cluster),
        merged_count=len(cluster),
        first_seen=min(d.first_seen for d in cluster),
        last_seen=max(d.last_seen for d in cluster),
    )


# ---------- poller ----------

class BLEPoller:
    """Background driver around ``diting-tianer ble-scan``.

    Single-use: call :meth:`events` once and iterate the resulting
    async generator. On generator close (consumer breaks out, or the
    surrounding asyncio task is cancelled) the helper subprocess is
    terminated and the internal tasks are awaited.

    The optional ``_spawn`` constructor argument is a test seam: when
    set, it replaces the production ``asyncio.create_subprocess_exec``
    call with a callable that returns a process-shaped object whose
    ``stdout`` is an async-iterable of bytes lines and whose ``wait``
    coroutine resolves to a return code.
    """

    def __init__(
        self,
        helper_path: str,
        *,
        ttl_s: float = 30.0,
        # 2 s strikes a balance: long enough that BLE's per-packet 5–
        # 15 dB RSSI jitter can be smoothed away by the EMA in
        # _build_device, short enough that a new device shows up
        # within "feels live". 1 s caused neighbouring rows to swap
        # on every render even when nothing real had changed.
        snapshot_interval_s: float = 2.0,
        # Anonymous-advert presence gate. An identifier whose first
        # observation has no helper-given `name` must be observed
        # for at least this many seconds (i.e. graduate from PENDING
        # to PRESENT) before BLEDeviceSeenEvent fires. 5 s default
        # kills single-packet ghost flicker (the dominant source of
        # `seen_for=0s` events in dense RF) while keeping legitimate
        # walk-bys (5-30 s typical) and static nearby devices.
        # Named adverts and connected peripherals bypass the gate
        # — they're already high-confidence. 0 disables the gate
        # entirely, restoring the original record-everything contract.
        presence_gate_s: float = 5.0,
        vendors: dict[int, str] | None = None,
        ouis: dict[str, str] | None = None,
        member_uuids: dict[str, str] | None = None,
        _spawn: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._helper_path = helper_path
        self._ttl_s = ttl_s
        self._snapshot_interval_s = snapshot_interval_s
        self._presence_gate_s = presence_gate_s
        self._vendors = vendors if vendors is not None else load_vendors()
        # OUI lookup is only consulted for connected peripherals (which
        # arrive without manufacturer_data). Lazy-load on first use; the
        # bundled JSON parses in well under a millisecond.
        self._ouis = ouis if ouis is not None else load_ouis()
        # SIG-assigned member service UUIDs. Used as a vendor fallback
        # when the advertisement omits manufacturer_data, plus for
        # service-column labelling.
        self._member_uuids = (
            member_uuids if member_uuids is not None else load_member_uuids()
        )
        self._devices: dict[str, BLEDevice] = {}
        # Currently-connected peripherals from the helper's
        # retrieveConnectedPeripherals snapshot. Lives in a parallel
        # dict because (a) entries have no RSSI / UUID-rotation, (b)
        # they are pruned by the helper's "connected_snapshot" sentinel
        # rather than the advertising-side TTL, and (c) merge_for_display
        # never sees them — they have stable identities.
        self._connected: dict[str, BLEDevice] = {}
        # Identifiers we've already emitted a `seen` event for this
        # session. Used to gate `BLEDeviceSeenEvent` so a single
        # advertisement → exactly one seen event regardless of how
        # many subsequent snapshot ticks observe the same device.
        # Includes BOTH the advertising path and the connected path
        # so a peripheral that connects then disappears doesn't
        # double-emit.
        self._seen_identifiers: set[str] = set()
        # Identifiers in PENDING — observed at least once, but their
        # first observation was anonymous (no helper-given `name`)
        # so they're holding for the presence-gate window before
        # graduating to PRESENT. Maps identifier → wall-clock time of
        # the first observation. Entries are removed on graduation
        # (moved to `_seen_identifiers`) OR on silent eviction
        # (identifier disappears from `_devices` before the gate
        # matures — no events emitted, identifier returns to INIT).
        self._pending_seen: dict[str, datetime] = {}
        # Identifiers we've already emitted a `left` event for this
        # session. Used to gate `BLEDeviceLeftEvent` so an identifier
        # that flaps in and out of `_devices` (edge-of-range device
        # whose adverts the macOS stack briefly stops delivering)
        # emits at most one left per session, not one per TTL cycle.
        # Re-appearance after departure does NOT fire a fresh seen
        # either — `_seen_identifiers` still gates that. An
        # identifier is terminal-departed for the rest of the session.
        self._departed_identifiers: set[str] = set()
        # Transition events (BLEDeviceSeenEvent / BLEDeviceLeftEvent)
        # accumulated during a tick. Consumers call `drain_transitions()`
        # after receiving each `BLEScanUpdate` to pull them — keeps
        # `events()` mono-typed (snapshots only) so existing tests /
        # consumers don't have to filter the iterator.
        self._pending_transitions: list[Any] = []
        self._queue: asyncio.Queue[BLEScanUpdate] = asyncio.Queue()
        self._proc: Any = None
        self._permission_state: str = "unknown"
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopped = False
        self._spawn_override = _spawn

    def drain_transitions(self) -> list[Any]:
        """Pop the transition events accumulated during the most-recent
        tick (or any unconsumed earlier ticks). Consumer calls this
        after each `BLEScanUpdate` to pull `BLEDeviceSeenEvent` /
        `BLEDeviceLeftEvent` for routing to the EventRing + JSONL
        log. Returning a list (not an iterator) makes the contract
        explicit: each call empties the queue."""
        out = self._pending_transitions
        self._pending_transitions = []
        return out

    async def events(self) -> AsyncIterator[BLEScanUpdate]:
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._reader_loop(), name="ble-reader"),
            loop.create_task(self._snapshot_loop(), name="ble-snapshot"),
        ]
        try:
            while True:
                yield await self._queue.get()
        finally:
            self.stop()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stopped = True
        for t in self._tasks:
            t.cancel()
        proc = self._proc
        if proc is not None and getattr(proc, "returncode", None) is None:
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                pass

    async def _reader_loop(self) -> None:
        try:
            if self._spawn_override is not None:
                self._proc = await self._spawn_override()
            else:
                self._proc = await asyncio.create_subprocess_exec(
                    self._helper_path, "ble-scan",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
        except (OSError, FileNotFoundError):
            self._permission_state = "unavailable"
            return

        stdout = getattr(self._proc, "stdout", None)
        if stdout is None:
            return

        try:
            async for raw in stdout:
                if self._stopped:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                state = update_from_line(
                    self._devices, line, vendors=self._vendors,
                    connected=self._connected, ouis=self._ouis,
                    member_uuids=self._member_uuids,
                )
                if state == "permission_denied":
                    self._permission_state = "denied"
                elif state == "error" and self._permission_state == "unknown":
                    self._permission_state = "error"
                elif state is None and self._permission_state in ("unknown", "error"):
                    # A successful parse implies we are getting real
                    # advertisements — flip to granted exactly once.
                    # Connected entries also count: a Mac with all BLE
                    # devices already paired (no fresh ads) would
                    # otherwise stay "unknown" forever.
                    if any(self._devices) or any(self._connected):
                        self._permission_state = "granted"
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            # Any unexpected stream error: stop reading. The snapshot
            # loop continues yielding empty snapshots (per spec) until
            # the consumer breaks.
            pass

        try:
            rc = await self._proc.wait()
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            rc = None
        # The Swift helper exits with documented codes that each carry
        # different meaning, so map every non-success rc to the most
        # specific permission_state the panel can render. Without this
        # the user sees "scanning…" indefinitely whenever the helper
        # actually died — silently masking Bluetooth-off, unsupported
        # hardware, and stale-installed-bundle scenarios.
        if rc == 3:
            self._permission_state = "denied"
        elif rc == 64:
            # 0.4.0-era helper bundles still in /Applications/ from
            # before this release reach the Swift `default:` case for
            # the unknown `ble-scan` subcommand and exit 64. Surface a
            # distinct "incompatible" state so the panel can suggest a
            # rebuild.
            self._permission_state = "incompatible"
        elif rc in (4, 5):
            # 4 = Bluetooth powered off, 5 = unsupported hardware.
            self._permission_state = "error"
        elif rc not in (None, 0):
            # Any other non-zero exit: assume something went wrong and
            # tell the user, rather than letting "granted" or "unknown"
            # linger while the panel is in fact stale.
            if self._permission_state in ("granted", "unknown"):
                self._permission_state = "error"

    def _detect_transitions(self, now: datetime) -> None:
        """Compute BLE seen / left transitions for this tick.

        Pure sync helper extracted from `_snapshot_loop` so unit tests
        can exercise the transition logic by populating `_devices`
        directly and calling this method, without spinning up the
        full async events() pipeline.

        Side effects: appends transition events to
        `_pending_transitions`, expires stale entries from
        `_devices` (via `expire_devices`), updates `_seen_identifiers`
        with graduated observations, and threads new anonymous
        identifiers through `_pending_seen` until the presence-gate
        elapses (or until they vanish, in which case they're dropped
        silently — no seen, no left).

        Identifiers already in `_seen_identifiers` or
        `_departed_identifiers` are not re-evaluated.
        """
        # Advertising-path graduation. Walk BEFORE the expire pass so
        # an identifier that graduates on this tick can still fire its
        # left event if TTL evicts it in the same tick (sub-snapshot
        # race; preserves the seen-then-left ordering invariant).
        for ident in list(self._devices.keys()):
            if ident in self._seen_identifiers:
                continue
            if ident in self._departed_identifiers:
                continue
            dev = self._devices[ident]
            # Bypass conditions: named device, OR gate disabled.
            # Named adverts are almost always real devices with
            # stable identity (Magic Keyboard, Z-GM0YXG5J, etc.) —
            # waiting on them would make the events log lag the BLE
            # list. Anonymous adverts (vendor + RSSI only) are the
            # noise source we're gating.
            bypass = dev.name is not None or self._presence_gate_s <= 0
            first_seen_at = self._pending_seen.get(ident)
            if first_seen_at is None:
                # First observation. Remember the wall-clock so a
                # later tick can graduate this identifier.
                first_seen_at = now
                if not bypass:
                    self._pending_seen[ident] = first_seen_at
            graduates = bypass or (
                (now - first_seen_at).total_seconds() >= self._presence_gate_s
            )
            if not graduates:
                continue
            # Emit seen with the device's own first_seen timestamp,
            # NOT the graduation wall-clock — the JSONL log should
            # answer "when did the device appear", not "when did the
            # poller become confident".
            ts = dev.first_seen or first_seen_at
            self._pending_transitions.append(BLEDeviceSeenEvent(
                timestamp=ts,
                identifier=ident,
                name=dev.name,
                vendor=dev.vendor,
                rssi_dbm=dev.rssi_dbm,
                service_categories=_ble_service_categories(dev),
            ))
            self._seen_identifiers.add(ident)
            self._pending_seen.pop(ident, None)
        # Connected peripherals always bypass the gate — they're
        # bonded by definition.
        for ident in list(self._connected.keys()):
            if ident not in self._seen_identifiers:
                dev = self._connected[ident]
                self._pending_transitions.append(BLEDeviceSeenEvent(
                    timestamp=now,
                    identifier=ident,
                    name=dev.name,
                    vendor=dev.vendor,
                    rssi_dbm=dev.rssi_dbm,
                    service_categories=_ble_service_categories(dev),
                ))
                self._seen_identifiers.add(ident)
        # Expire TTL'd advertising entries. Emit left ONLY for
        # identifiers that previously graduated to PRESENT — a
        # PENDING identifier that never made it past the gate
        # leaves silently (no seen, no left).
        before = self._devices
        self._devices = expire_devices(
            self._devices, now=now, ttl_s=self._ttl_s,
        )
        # Drop PENDING entries whose underlying _devices entry has
        # gone away before the gate matured. Silent — no seen event
        # ever fired for these, so no left event either. Done after
        # expire so newly-aged-out entries are caught.
        for ident in list(self._pending_seen):
            if ident not in self._devices:
                self._pending_seen.pop(ident)
        for ident, dev in before.items():
            if ident in self._devices:
                continue
            if ident not in self._seen_identifiers:
                # Never graduated to PRESENT (still in PENDING or
                # silently dropped). No paired seen exists, so no
                # left either.
                continue
            if ident in self._departed_identifiers:
                continue
            self._pending_transitions.append(BLEDeviceLeftEvent(
                timestamp=now,
                identifier=ident,
                name=dev.name,
                vendor=dev.vendor,
                last_rssi_dbm=dev.rssi_dbm,
                service_categories=_ble_service_categories(dev),
                seen_for_seconds=(
                    (dev.last_seen - dev.first_seen).total_seconds()
                    if dev.last_seen and dev.first_seen
                    else 0.0
                ),
            ))
            self._departed_identifiers.add(ident)

    async def _snapshot_loop(self) -> None:
        # Always emit at least one snapshot promptly so consumers see
        # the initial "(scanning…)" state without waiting a full
        # interval.
        try:
            while not self._stopped:
                now = datetime.now(timezone.utc)
                self._detect_transitions(now)
                merged = merge_for_display(list(self._devices.values()))
                # Connected entries sort alphabetically by name (per spec
                # layout B); RSSI sort would be meaningless given they
                # have no signal reading. Stable, predictable order.
                connected = sorted(
                    self._connected.values(),
                    key=lambda d: ((d.name or "").lower(), d.identifier),
                )
                await self._queue.put(BLEScanUpdate(
                    devices=merged,
                    permission_state=self._permission_state,
                    connected=connected,
                ))
                await asyncio.sleep(self._snapshot_interval_s)
        except asyncio.CancelledError:
            raise
