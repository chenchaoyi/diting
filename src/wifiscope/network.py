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

YAML schema (~/.config/wifiscope/aps.yaml; override with the
WIFISCOPE_INVENTORY environment variable):

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
        # Primary: first five octets match. Catches all radios / VAPs
        # that come out of the same NIC OUI pool (the most common case).
        prefix = _prefix5(b)
        for ap in self.aps:
            if ap.prefix == prefix:
                return ap.name
        # Secondary: middle four octets match (octets 2..5). Some
        # vendors — H3C in particular — assign a chip's "user" SSIDs
        # to one OUI block (e.g. 40:fe:95:...) and the same chip's
        # "vendor-internal" SSIDs to a sibling OUI block (44:fe:95:...).
        # Octets 2..5 carry the chip's serial bits and are the same
        # across both blocks, so this rule reliably groups them while
        # the chance of a false match against an unrelated nearby AP
        # is ~1/2^32. If a real deployment hits a conflict, the user
        # can pin specific BSSIDs in radio_overrides which wins above.
        mid = _mid4(b)
        for ap in self.aps:
            if _mid4(ap.mgmt_mac) == mid:
                return ap.name
        return None

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


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "wifiscope" / "aps.yaml"


def resolve_config_path() -> Path:
    override = os.environ.get("WIFISCOPE_INVENTORY")
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
