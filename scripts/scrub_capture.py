#!/usr/bin/env python3
"""Scrub a real diting JSONL capture into a committable, anonymized
fixture.

Real captures carry BSSIDs / SSIDs / IPs / MACs / device names /
hostnames — they doxx a physical location and are PII, so the repo
git-ignores `diting-*.jsonl` and never commits them. This tool produces
an anonymized copy safe to commit as an `analyze` test asset: stable
per-kind handles replace the sensitive fields, while EVERYTHING the
analyser reasons over is preserved verbatim — vendor names (public
manufacturer strings, not PII), timestamps (so the temporal rhythm is
unchanged), `seen_for_seconds` (dwell), `familiarity`, magnitudes,
counts, and — critically — the DISTINCTNESS of names / identifiers, so
the stable-key device population reproduces exactly.

Deterministic: same input → same output, first-seen handle order.

    python scripts/scrub_capture.py diting-YYYYMMDD-HHMMSS.jsonl > out.jsonl
"""
from __future__ import annotations

import json
import sys

# Fields scrubbed to a stable handle, keyed by the namespace the handle
# lives in (so an SSID and a hostname never collide on a number).
_STRING_FIELDS = {
    "ssid": "ssid",
    "bssid": "mac",
    "new_bssid": "mac",
    "previous_bssid": "mac",
    "mac": "mac",
    "gateway_ip": "ip",
    "target_ip": "ip",
    "router_ip": "ip",
    "new_router_ip": "ip",
    "previous_router_ip": "ip",
    "ip": "ip",
    "hostname": "host",
    "host": "host",
    "bonjour_name": "host",
    "name": "name",
    "identifier": "id",
}
# Everything else flows through verbatim — vendor / category / state /
# security / familiarity / salience / device_type / device_class /
# service_categories / service_type / rssi / dwell / loss / counts /
# timestamps / scene / version / insight code+detail.


class _Handles:
    """Stable first-seen handle per (kind, value)."""

    _FMT = {
        "ssid": "SSID-{n}",
        "host": "host-{n}",
        "name": "dev-{n}",
        "id": "id-{n}",
    }

    def __init__(self) -> None:
        self._maps: dict[str, dict[str, str]] = {}
        self._n: dict[str, int] = {}

    def get(self, kind: str, value: str) -> str:
        bucket = self._maps.setdefault(kind, {})
        if value in bucket:
            return bucket[value]
        self._n[kind] = self._n.get(kind, 0) + 1
        n = self._n[kind]
        if kind == "mac":
            handle = f"02:00:00:{(n >> 16) & 0xFF:02x}:{(n >> 8) & 0xFF:02x}:{n & 0xFF:02x}"
        elif kind == "ip":
            # IPv6 addresses keep their shape; IPv4 maps into 10.x.
            handle = f"fe80::{n:x}" if value and ":" in value else f"10.0.{(n >> 8) & 0xFF}.{n & 0xFF}"
        else:
            handle = self._FMT[kind].format(n=n)
        bucket[value] = handle
        return handle


def scrub_row(row: dict, handles: _Handles) -> dict:
    out = dict(row)
    for field, kind in _STRING_FIELDS.items():
        v = out.get(field)
        if isinstance(v, str) and v:
            out[field] = handles.get(kind, v)
    addrs = out.get("addresses")
    if isinstance(addrs, list):
        out["addresses"] = [
            handles.get("ip", a) if isinstance(a, str) else a for a in addrs
        ]
    return out


def scrub_lines(lines) -> list[str]:
    handles = _Handles()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # drop garbage, same as the analyser
        out.append(json.dumps(scrub_row(row, handles), ensure_ascii=False))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        for line in scrub_lines(fh):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
