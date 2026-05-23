"""Active LAN discovery probes — NBNS / SSDP / UPnP / mDNS-meta.

Layered on top of the passive `lan.py` poller and called from
`_do_sweep_and_emit()` ONLY when the active scene's `lan_active_probe`
knob is true (home / office / audit by default), or when the
public-scene one-shot user-consent override has armed
`_one_shot_probe_armed`.

Three probe phases:

1. **NBNS Name Query** (RFC 1002 §4.2.18) — unicast UDP 137 per
   silent host. Each Windows / Samba / NAS device answers with its
   NetBIOS name table within ~10 ms on LAN. We pull the
   WORKSTATION (`0x00`) name as `LANHost.nbns_name`.
2. **SSDP M-SEARCH** — one multicast UDP packet to
   ``239.255.255.250:1900``. UPnP devices (smart TVs, printers,
   NAS, IoT bridges) reply with HTTP-style headers carrying
   ``SERVER:`` and ``LOCATION:``. Optionally fetches the LOCATION
   XML for friendlyName + modelName.
3. **Active mDNS browse query** — handled in `mdns.py` via
   ``BonjourPoller.send_meta_query()``, not in this module; the
   passive listener captures responses through the normal path.

Design tenets:

- Pure functions for all encoding / parsing so the wire payloads
  are unit-testable without a network.
- Fail-soft: any exception in one host's probe must not propagate;
  the next phase / next host still runs.
- Bounded resources: 30-way semaphore (matching the sweep
  concurrency), 100 ms NBNS per-host budget, 3 s SSDP listen,
  500 ms / 4 KB UPnP LOCATION fetch cap.
- No new third-party deps. Stdlib ``socket`` + ``asyncio`` +
  ``urllib`` + ``xml.etree.ElementTree``.
"""
from __future__ import annotations

import asyncio
import os
import re
import socket
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from xml.etree import ElementTree as ET


# ---------- shared budget knobs ----------

NBNS_PORT = 137
SSDP_MCAST_ADDR = "239.255.255.250"
SSDP_PORT = 1900

_NBNS_TIMEOUT_MS_DEFAULT = 100
_NBNS_CONCURRENCY = 30
_SSDP_LISTEN_S_DEFAULT = 3.0
_SSDP_MX_DEFAULT = 2  # advertised max-wait in MX header, seconds
_UPNP_FETCH_TIMEOUT_S = 0.5
_UPNP_FETCH_MAX_BYTES = 4096


# ---------- NBNS Name Query ----------

# Wildcard NetBIOS name "*" padded to 16 bytes with NUL, level-2
# encoded. Level-2 encodes each byte X as the two ASCII characters
# 'A'+(X>>4) and 'A'+(X&0xF). 0x2A ("*") → "CK", 0x00 → "AA".
_NBNS_WILDCARD_ENCODED = b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

_NBSTAT_TYPE = 0x0021
_NBNS_CLASS_IN = 0x0001
_NBNS_FLAGS_STANDARD_QUERY = 0x0000


def encode_nbns_status_query(txn_id: int) -> bytes:
    """Build a 50-byte NBNS Status Query (NBSTAT, RFC 1002 §4.2.18).

    The query targets the wildcard name "*" with type NBSTAT — every
    NetBIOS-speaking host on the LAN responds with its full name
    table.
    """
    if not 0 <= txn_id <= 0xFFFF:
        raise ValueError(f"txn_id out of 16-bit range: {txn_id}")
    header = struct.pack(
        ">HHHHHH",
        txn_id,
        _NBNS_FLAGS_STANDARD_QUERY,
        0x0001,  # questions
        0x0000,  # answers
        0x0000,  # authority
        0x0000,  # additional
    )
    # Question section: length-prefixed encoded name + null + type + class.
    question = (
        bytes([len(_NBNS_WILDCARD_ENCODED)])  # 0x20 == 32
        + _NBNS_WILDCARD_ENCODED
        + b"\x00"
        + struct.pack(">HH", _NBSTAT_TYPE, _NBNS_CLASS_IN)
    )
    return header + question


@dataclass(frozen=True, slots=True)
class NBNSNameEntry:
    """One row from a NBNS Status Response name table.

    ``name`` is right-stripped of trailing spaces (NetBIOS pads to 15
    chars with spaces). ``suffix`` is the 1-byte service-type byte
    (``0x00`` = workstation, ``0x20`` = file server, ``0x1F`` =
    NetDDE, etc.). ``group`` is True when the high bit of the flags
    word is set (group name vs unique name).
    """

    name: str
    suffix: int
    group: bool


def parse_nbns_status_response(data: bytes) -> list[NBNSNameEntry]:
    """Pull the name table out of an NBNS Status Response.

    Returns ``[]`` on any structural error — caller should treat an
    empty list as "no name found". The function NEVER raises; this
    is the wire protocol's response-handler position so failure
    must be confined.
    """
    try:
        if len(data) < 12:
            return []
        # Skip the 12-byte header.
        offset = 12
        # Skip the question section: length-prefixed name + null +
        # type + class. The first byte gives the encoded-name length.
        if offset >= len(data):
            return []
        name_len = data[offset]
        # The encoded name is `name_len` bytes long. Standard form is
        # 0x20 (32). Skip name_len + 1 (for the terminating null byte)
        # + 4 (type + class).
        offset += 1 + name_len + 1 + 4
        if offset >= len(data):
            return []
        # Skip the answer record's name. It's either a 2-byte
        # compression pointer (high bits 0xC0) or another length-
        # prefixed sequence. Common case: 0xC0 0x0C → compressed
        # pointer to offset 0x0C (the question name).
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        else:
            # Length-prefixed form. Read length byte and skip.
            answer_name_len = data[offset]
            offset += 1 + answer_name_len + 1
        # Skip type (2) + class (2) + TTL (4) + RDLENGTH (2).
        offset += 10
        if offset > len(data):
            return []
        # RDATA: NUM_NAMES (1 byte) + NUM_NAMES * 18 bytes (15 byte name + 1 byte suffix + 2 byte flags).
        num_names = data[offset]
        offset += 1
        entries: list[NBNSNameEntry] = []
        for _ in range(num_names):
            if offset + 18 > len(data):
                break
            raw_name = data[offset : offset + 15]
            suffix = data[offset + 15]
            flags = struct.unpack(">H", data[offset + 16 : offset + 18])[0]
            offset += 18
            name = raw_name.decode("ascii", errors="replace").rstrip(" \x00")
            entries.append(
                NBNSNameEntry(
                    name=name,
                    suffix=suffix,
                    group=bool(flags & 0x8000),
                )
            )
        return entries
    except (struct.error, IndexError, ValueError):
        return []


def workstation_name(entries: list[NBNSNameEntry]) -> str | None:
    """Pick the WORKSTATION (suffix 0x00, unique) entry's name.

    NetBIOS lets a host register multiple names; the workstation
    suffix is the one that matches the user's mental model of the
    machine's name. Group entries are skipped (those are domain /
    workgroup names, not host names).
    """
    for e in entries:
        if e.suffix == 0x00 and not e.group and e.name:
            return e.name
    return None


async def _nbns_one(
    ip: str, *, timeout_s: float, semaphore: asyncio.Semaphore,
) -> tuple[str, str | None]:
    """Send one NBNS query to ``ip`` and parse the reply.

    Returns ``(ip, workstation_name_or_None)``. Fails soft — any
    exception or timeout yields ``(ip, None)``.
    """
    async with semaphore:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setblocking(False)
            txn_id = int.from_bytes(os.urandom(2), "big")
            packet = encode_nbns_status_query(txn_id)
            try:
                sock.sendto(packet, (ip, NBNS_PORT))
            except OSError:
                return ip, None
            try:
                data, _addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 4096), timeout=timeout_s,
                )
            except (asyncio.TimeoutError, OSError):
                return ip, None
            entries = parse_nbns_status_response(data)
            return ip, workstation_name(entries)
        finally:
            sock.close()


async def probe_nbns(
    ips: list[str],
    *,
    timeout_ms: int = _NBNS_TIMEOUT_MS_DEFAULT,
    concurrency: int = _NBNS_CONCURRENCY,
) -> dict[str, str | None]:
    """Run NBNS Status Query against every IP in ``ips``.

    Returns ``{ip: nbns_name_or_None}``. Hosts that didn't reply
    (most of a typical LAN) appear with ``None`` so callers can
    distinguish "we asked and got nothing" from "we never asked".
    """
    if not ips:
        return {}
    sem = asyncio.Semaphore(concurrency)
    timeout_s = timeout_ms / 1000.0
    results = await asyncio.gather(
        *[_nbns_one(ip, timeout_s=timeout_s, semaphore=sem) for ip in ips],
        return_exceptions=True,
    )
    out: dict[str, str | None] = {ip: None for ip in ips}
    for r in results:
        if isinstance(r, tuple) and len(r) == 2:
            ip, name = r
            out[ip] = name
    return out


# ---------- SSDP M-SEARCH ----------

SSDP_MSEARCH_PACKET = (
    b"M-SEARCH * HTTP/1.1\r\n"
    b"HOST: 239.255.255.250:1900\r\n"
    b'MAN: "ssdp:discover"\r\n'
    b"MX: 2\r\n"
    b"ST: ssdp:all\r\n"
    b"\r\n"
)


@dataclass(frozen=True, slots=True)
class SSDPResponse:
    """One row from a parsed SSDP M-SEARCH reply.

    ``ip`` is the source address of the UDP packet (we don't trust
    headers for the host identity). ``server`` is the raw ``Server:``
    header; ``location`` is the URL of the device description XML;
    ``usn`` and ``st`` are the response's identifiers. ``friendly_name``
    and ``model_name`` are populated only when the LOCATION fetch ran.
    """

    ip: str
    server: str | None
    location: str | None
    usn: str | None
    st: str | None
    friendly_name: str | None = None
    model_name: str | None = None


_HTTP_HEADER_RE = re.compile(rb"^([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")


def parse_ssdp_response(data: bytes, *, ip: str) -> SSDPResponse | None:
    """Pull headers out of an SSDP HTTP-style response.

    Returns ``None`` when the payload isn't a valid HTTP/1.1 200
    response. NEVER raises — wire-protocol response handling must
    be confined.
    """
    try:
        lines = data.split(b"\r\n")
        if not lines or not lines[0].upper().startswith(b"HTTP/1"):
            return None
        if b" 200" not in lines[0]:
            return None
        headers: dict[str, str] = {}
        for raw in lines[1:]:
            m = _HTTP_HEADER_RE.match(raw)
            if not m:
                continue
            key = m.group(1).decode("ascii", "replace").upper()
            val = m.group(2).decode("utf-8", "replace")
            # First occurrence wins; SSDP headers are not multi-valued
            # for our purposes.
            if key not in headers:
                headers[key] = val
        return SSDPResponse(
            ip=ip,
            server=headers.get("SERVER"),
            location=headers.get("LOCATION"),
            usn=headers.get("USN"),
            st=headers.get("ST"),
        )
    except (UnicodeDecodeError, ValueError):
        return None


async def probe_ssdp(
    *,
    listen_s: float = _SSDP_LISTEN_S_DEFAULT,
    mx: int = _SSDP_MX_DEFAULT,
) -> dict[str, SSDPResponse]:
    """Send one M-SEARCH multicast and collect replies for ``listen_s``.

    Returns ``{ip: SSDPResponse}`` keyed by source IP of the reply.
    Multiple responses from one IP collapse to first-wins (a single
    UPnP root device is enough to identify the host).

    Fails soft: a socket-creation or bind failure yields ``{}``; per-
    response parse failures are dropped silently.
    """
    loop = asyncio.get_running_loop()
    out: dict[str, SSDPResponse] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setblocking(False)
        packet = SSDP_MSEARCH_PACKET.replace(
            b"MX: 2\r\n", f"MX: {int(mx)}\r\n".encode("ascii"),
        )
        try:
            sock.sendto(packet, (SSDP_MCAST_ADDR, SSDP_PORT))
        except OSError:
            return out
        deadline = loop.time() + listen_s
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 4096), timeout=remaining,
                )
            except asyncio.TimeoutError:
                break
            except OSError:
                continue
            ip = addr[0]
            if ip in out:
                continue
            resp = parse_ssdp_response(data, ip=ip)
            if resp is not None:
                out[ip] = resp
        return out
    finally:
        sock.close()


# ---------- UPnP LOCATION fetch + XML parse ----------

# UPnP device descriptions live in a `urn:schemas-upnp-org:device-1-0`
# namespace. Find friendlyName / modelName by local-name match so we
# don't have to thread the exact namespace URI through every call.
def _find_local(elem: ET.Element, local_name: str) -> ET.Element | None:
    for child in elem.iter():
        tag = child.tag
        # Tags look like `{namespace}localname` — strip the brace block.
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == local_name:
            return child
    return None


def parse_upnp_location_xml(
    xml_bytes: bytes,
) -> tuple[str | None, str | None]:
    """Pull ``(friendly_name, model_name)`` from a UPnP description XML.

    Uses stdlib ``ElementTree`` — which by default does NOT resolve
    external entities (DOCTYPE-based attacks are inert) — and bounds
    its work via the caller-supplied 4 KB byte cap.
    """
    try:
        # Use XMLParser explicitly so a future stdlib change can't
        # accidentally enable entity expansion.
        parser = ET.XMLParser()
        root = ET.fromstring(xml_bytes, parser=parser)
    except ET.ParseError:
        return None, None
    friendly = _find_local(root, "friendlyName")
    model = _find_local(root, "modelName")
    return (
        friendly.text.strip() if friendly is not None and friendly.text else None,
        model.text.strip() if model is not None and model.text else None,
    )


def _fetch_upnp_location_sync(
    url: str, *, timeout_s: float, max_bytes: int,
) -> bytes:
    """Blocking HTTP GET capped at ``max_bytes`` bytes / ``timeout_s``.

    Returns the (truncated) response body on success. Raises on
    any urllib error or timeout — caller wraps in ``asyncio.to_thread``
    + exception swallow.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "diting-lan-probes/1.0",
            "Accept": "application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read(max_bytes + 1)[:max_bytes]


async def fetch_upnp_location(
    url: str | None,
    *,
    timeout_s: float = _UPNP_FETCH_TIMEOUT_S,
    max_bytes: int = _UPNP_FETCH_MAX_BYTES,
) -> tuple[str | None, str | None]:
    """Fetch the UPnP description XML at ``url`` and parse it.

    Returns ``(friendly_name, model_name)``. Fails soft to
    ``(None, None)`` on any HTTP error, timeout, or parse error.
    Returns ``(None, None)`` immediately when ``url`` is falsy.
    """
    if not url:
        return None, None
    try:
        body = await asyncio.to_thread(
            _fetch_upnp_location_sync,
            url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
        )
    except (
        urllib.error.URLError,
        ValueError,
        OSError,
        TimeoutError,
    ):
        return None, None
    return parse_upnp_location_xml(body)


# ---------- env var resolution ----------


def _truthy_env(value: str | None) -> bool | None:
    """Return True / False / None matching the documented schema:

    - ``"1"`` → True
    - ``"0"`` → False
    - unset / empty → None (fall through to scene default)
    - anything else → None (and the caller logs a stderr warning)
    """
    if value is None:
        return None
    v = value.strip()
    if v == "":
        return None
    if v == "1":
        return True
    if v == "0":
        return False
    return None


def resolve_lan_active_probe(
    *,
    env: dict[str, str] | None = None,
    scene_default: bool,
) -> bool:
    """Resolve the at-startup active-probe flag.

    ``DITING_LAN_PROBE`` overrides the scene default; an invalid
    value (already warned by the caller) falls through to the
    scene default.
    """
    env = env if env is not None else os.environ  # type: ignore[assignment]
    parsed = _truthy_env(env.get("DITING_LAN_PROBE"))
    if parsed is None:
        return scene_default
    return parsed


def resolve_upnp_fetch_enabled(
    *,
    env: dict[str, str] | None = None,
) -> bool:
    """``DITING_LAN_UPNP_FETCH`` toggle. Defaults to True."""
    env = env if env is not None else os.environ  # type: ignore[assignment]
    parsed = _truthy_env(env.get("DITING_LAN_UPNP_FETCH"))
    if parsed is None:
        return True
    return parsed
