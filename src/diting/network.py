"""Network inventory: derive AP names and band labels from controller data.

Most WiFi controllers (H3C, Aruba, Ubiquiti, Cisco, ...) expose only
the **management MAC** of each AP, not the per-radio BSSIDs the AP
actually broadcasts. This module accepts the AP-level information the
user can realistically read off their controller and derives radio
attribution at scan time:

1. `radio_overrides` (BSSID → name) — explicit per-radio mapping for
   vendors that do not follow the same-prefix convention. Checked first
   so a hand-edited override always wins.
2. **First-five-octet rule** — if a BSSID and a known AP's mgmt MAC
   share the first five octets, they are the same physical AP. This
   works because most chipsets allocate radio / VAP MACs from one NIC
   by varying only the last octet (verified empirically across H3C
   AX51-E and AX60 families; widely reported for Aruba, Ubiquiti, most
   ASUS / TP-Link / Netgear consumer gear).

Band labels come from the channel number alone, never from the MAC:
- 1..14   -> 2.4G
- 32..177 -> 5G

YAML schema (./aps.yaml in the current working directory; override
with the DITING_INVENTORY environment variable):

    aps:
      - name: 1F-bedroom
        mgmt_mac: 40:fe:95:8a:3c:07
      - name: 2F-living
        mgmt_mac: 40:fe:95:8a:3c:54

    radio_overrides:                # optional, default {}
      bc:22:47:ca:79:4a: 3F-attic
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class APEntry:
    name: str
    mgmt_mac: str

    @property
    def prefix(self) -> str:
        return _prefix5(self.mgmt_mac)


@dataclass(frozen=True, slots=True)
class NetworkInventory:
    aps: tuple[APEntry, ...] = ()
    radio_overrides: dict[str, str] = field(default_factory=dict)

    def resolve(self, bssid: str | None) -> str | None:
        if bssid is None:
            return None
        b = bssid.lower()
        if b in self.radio_overrides:
            return self.radio_overrides[b]
        last = _last_byte(b)

        # Primary: first five octets match AND the BSSID's last byte is
        # within a small window above the AP's mgmt MAC last byte.
        # Radios and VAPs of one chip are allocated as `mgmt + N` for
        # small N (typically 1..6), and prefix5 alone is not enough to
        # disambiguate when the user's controller hands out APs with
        # adjacent mgmt MACs from one OUI pool — e.g. an H3C AC with
        # APs at 40:fe:95:8a:3c:07, :15, :54 all share prefix5 and
        # would all map to the first list entry without this rule.
        best = self._closest_in_window(
            last, predicate=lambda ap: ap.prefix == _prefix5(b)
        )
        if best is not None:
            return best.name

        # Secondary: octets 2..5 match (covers vendors that allocate a
        # chip's "user" radios from one OUI block and "vendor-internal"
        # radios from a sibling OUI block, e.g. H3C 40:.../ 44:...).
        # Same proximity rule keeps closely-spaced mgmt MACs separated.
        best = self._closest_in_window(
            last, predicate=lambda ap: _mid4(ap.mgmt_mac) == _mid4(b)
        )
        if best is not None:
            return best.name
        return None

    def _closest_in_window(
        self, bssid_last: int, *, predicate, window: int = 8
    ) -> APEntry | None:
        """Of the APs satisfying `predicate`, return the one whose mgmt
        MAC last byte is the largest value not exceeding `bssid_last`,
        within `window` of it. Returns None if no AP qualifies.
        """
        best_ap: APEntry | None = None
        best_distance = window + 1
        for ap in self.aps:
            if not predicate(ap):
                continue
            distance = bssid_last - _last_byte(ap.mgmt_mac)
            if 0 <= distance < best_distance:
                best_distance = distance
                best_ap = ap
        return best_ap

    def is_same_ap(self, a: str | None, b: str | None) -> bool:
        """True if two BSSIDs are radios of the same physical AP."""
        if a is None or b is None:
            return False
        name_a = self.resolve(a)
        name_b = self.resolve(b)
        if name_a is not None and name_b is not None:
            return name_a == name_b
        if name_a is None and name_b is None:
            # Apply both rules from `resolve` for consistency.
            return _prefix5(a) == _prefix5(b) or _mid4(a) == _mid4(b)
        return False


def _prefix5(mac: str) -> str:
    return mac.lower().rsplit(":", 1)[0]


def _mid4(mac: str) -> str:
    """Octets 2..5 of a MAC string (skips the leading byte and trailing byte)."""
    parts = mac.lower().split(":")
    if len(parts) != 6:
        return mac.lower()
    return ":".join(parts[1:5])


def _last_byte(mac: str) -> int:
    """Last octet of a MAC as int. Returns -1 on malformed input."""
    try:
        return int(mac.lower().rsplit(":", 1)[-1], 16)
    except (ValueError, IndexError):
        return -1


def default_config_path() -> Path:
    """Default AP-aliases location: ``./aps.yaml`` in the current working
    directory. Resolved against CWD at lookup time (not at import time)
    so users running diting from inside the cloned repo find the file
    next to ``aps.example.yaml`` without having to ``mkdir -p
    ~/.config/diting/`` first. Set ``DITING_INVENTORY=/path`` to
    point elsewhere.
    """
    return Path("aps.yaml")


def resolve_config_path() -> Path:
    override = os.environ.get("DITING_INVENTORY")
    return Path(override).expanduser() if override else default_config_path()


def load_inventory(path: Path | None = None) -> NetworkInventory:
    p = path or resolve_config_path()
    if not p.exists():
        return NetworkInventory()
    with p.open() as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{p}: top-level YAML must be a mapping, got {type(raw).__name__}"
        )
    aps_raw = raw.get("aps") or []
    if not isinstance(aps_raw, list):
        raise ValueError(f"{p}: 'aps' must be a list")
    aps: list[APEntry] = []
    for i, item in enumerate(aps_raw):
        if not isinstance(item, dict) or "name" not in item or "mgmt_mac" not in item:
            raise ValueError(
                f"{p}: aps[{i}] must have 'name' and 'mgmt_mac' keys"
            )
        aps.append(
            APEntry(name=str(item["name"]), mgmt_mac=str(item["mgmt_mac"]).lower())
        )
    overrides_raw = raw.get("radio_overrides") or {}
    if not isinstance(overrides_raw, dict):
        raise ValueError(f"{p}: 'radio_overrides' must be a mapping")
    overrides = {str(k).lower().strip(): str(v) for k, v in overrides_raw.items()}
    return NetworkInventory(aps=tuple(aps), radio_overrides=overrides)


def format_bssid(
    bssid: str | None,
    channel: int | None,
    inventory: NetworkInventory,
) -> str:
    """Render `<AP-name> (<band>) (<bssid>)` when known, else raw BSSID."""
    if bssid is None:
        return "n/a"
    name = inventory.resolve(bssid)
    band = band_label(channel)
    if name is None:
        return bssid
    if band is None:
        return f"{name} ({bssid})"
    return f"{name} ({band}) ({bssid})"


def band_label(channel: int | None) -> str | None:
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2.4G"
    if 32 <= channel <= 177:
        return "5G"
    return None


def cluster_label(bssid: str | None) -> str:
    """Synthetic AP label for a BSSID not present in any inventory entry.

    Uses octets 3..5 of the MAC (the chip's serial bits inside its OUI
    block). All radios / VAPs of the same physical AP share these
    three octets regardless of which OUI block the vendor allocates
    each radio from, so this label groups them under one identifier
    without any prior knowledge from the user. False collisions
    against unrelated nearby APs require ~24 bits of coincidence —
    effectively never in practice.

    Format ``?AA:BB:CC``. The leading ``?`` and dim styling at the
    call site signal that this is auto-derived, not a user-provided
    name.
    """
    if not bssid:
        return "?"
    parts = bssid.lower().split(":")
    if len(parts) != 6:
        return "?"
    return "?" + ":".join(parts[2:5])


# ---- AP vendor lookup (Wi-Fi OUI → manufacturer) ----

import json as _json

_WIFI_OUIS_PATH = (
    Path(__file__).resolve().parent / "data" / "wifi_ouis.json"
)


def load_wifi_ouis(path: Path | None = None) -> dict[str, str]:
    """Load the bundled Wi-Fi AP OUI → vendor map.

    Curated subset of the IEEE OUI registry covering common router
    and AP vendors (Xiaomi / TP-Link / Cisco / Aruba / Netgear /
    ASUS / etc.). Missing or unreadable file yields an empty dict
    so the connection panel falls through to "(unknown)" rather
    than crashing. Extending the map is a one-file edit; users
    can drop new ``OUI: name`` entries into the JSON without code
    changes.
    """
    if path is None:
        path = _WIFI_OUIS_PATH
    if not path.is_file():
        return {}
    try:
        data = _json.loads(path.read_text())
    except (OSError, _json.JSONDecodeError):
        return {}
    return {
        str(k).lower(): str(v)
        for k, v in data.items()
        if k != "_meta" and isinstance(v, str)
    }


def lookup_ap_vendor(
    bssid: str | None, ouis: dict[str, str] | None = None,
) -> str | None:
    """Return the manufacturer name for a BSSID's OUI, or ``None``.

    Pure function. ``ouis`` defaults to the bundled map; tests
    pass a custom dict. Coverage is intentionally a curated
    subset, not the full IEEE registry — anything missing is
    returned as ``None`` so the call site can fall back to
    ``cluster_label`` or the raw BSSID.
    """
    if not bssid:
        return None
    parts = bssid.lower().split(":")
    if len(parts) < 3:
        return None
    prefix = ":".join(parts[:3])
    if ouis is None:
        ouis = load_wifi_ouis()
    return ouis.get(prefix)
