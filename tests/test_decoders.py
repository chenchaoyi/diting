"""Decoder framework + per-protocol decoder behaviour tests.

Each protocol gets a happy-path test (canonical advertisement decodes
into the documented fields) plus negative coverage (wrong cid, wrong
service-UUID, malformed bytes, schema-3 device with no service_data).
"""
from __future__ import annotations

from datetime import datetime, timezone

from diting.ble import BLEDevice
from diting.decoders import decode_all, decoders


def _dev(
    *,
    manufacturer_hex: str | None = None,
    service_data: tuple[tuple[str, str], ...] = (),
    vendor_id: int | None = None,
) -> BLEDevice:
    """Minimal BLEDevice for decoder tests."""
    now = datetime(2026, 5, 9, 13, 0, 0, tzinfo=timezone.utc)
    return BLEDevice(
        identifier="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        name=None,
        vendor=None,
        vendor_id=vendor_id,
        services=(),
        rssi_dbm=-60,
        is_connectable=True,
        first_seen=now,
        last_seen=now,
        ad_count=1,
        manufacturer_hex=manufacturer_hex,
        service_data=service_data,
    )


# ----------------------------------------------------------------------
# Framework
# ----------------------------------------------------------------------

def test_registry_has_built_in_decoders():
    """Importing the package should auto-register the bundled iBeacon
    and Eddystone decoders. A regression here means a decoder file
    failed to import or skipped its ``@register`` decorator."""
    assert len(decoders()) >= 2


def test_decode_all_swallows_decoder_exceptions(monkeypatch):
    """One buggy decoder should not blank the whole panel."""
    from diting import decoders as pkg

    def boom(_d):
        raise RuntimeError("decoder bug")

    pkg._DECODERS.append(boom)
    try:
        # Real iBeacon should still come through despite ``boom``.
        d = _dev(
            vendor_id=0x004C,
            manufacturer_hex=(
                "4c00"            # cid
                "0215"            # iBeacon type + length
                + "00" * 16       # UUID
                + "0001"          # major
                + "0002"          # minor
                + "c5"            # tx_power -59
            ),
        )
        out = decode_all(d)
        assert out["ibeacon.major"] == 1
    finally:
        pkg._DECODERS.remove(boom)


# ----------------------------------------------------------------------
# iBeacon
# ----------------------------------------------------------------------

def test_ibeacon_canonical_decode():
    """A textbook iBeacon advertisement decodes into its four fields."""
    uuid_hex = "550e8400e29b41d4a716446655440000"
    d = _dev(
        vendor_id=0x004C,
        manufacturer_hex=(
            "4c00"            # cid (Apple)
            "0215"            # iBeacon: type 0x02, length 0x15
            + uuid_hex
            + "0001"          # major = 1
            + "002a"          # minor = 42
            + "c5"            # tx_power = -59 dBm
        ),
    )
    out = decode_all(d)
    assert out["ibeacon.uuid"] == "550e8400-e29b-41d4-a716-446655440000"
    assert out["ibeacon.major"] == 1
    assert out["ibeacon.minor"] == 42
    assert out["ibeacon.tx_power"] == -59


def test_ibeacon_skips_non_apple_cid():
    """Microsoft cid + iBeacon-shaped bytes should not match."""
    d = _dev(
        vendor_id=0x0006,
        manufacturer_hex="0600" + "0215" + "00" * 16 + "0001" + "0002" + "c5",
    )
    out = decode_all(d)
    assert "ibeacon.uuid" not in out


def test_ibeacon_skips_apple_continuity_nearby_info():
    """A real iPhone Nearby Info advertisement (type 0x10, not 0x02)
    must not falsely match the iBeacon decoder."""
    d = _dev(
        vendor_id=0x004C,
        manufacturer_hex="4c001006271efe0b8af9",  # Nearby Info, length 6
    )
    out = decode_all(d)
    assert "ibeacon.uuid" not in out


def test_ibeacon_skips_truncated_payload():
    """A frame too short to fit the iBeacon record returns nothing."""
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c000215aabb")
    out = decode_all(d)
    assert "ibeacon.uuid" not in out


# ----------------------------------------------------------------------
# Eddystone
# ----------------------------------------------------------------------

def test_eddystone_url_canonical_decode():
    """Eddystone-URL frame for ``https://example.com`` decodes back to
    the original URL."""
    # Frame 0x10 + tx_power 0xeb (-21) + scheme 0x03 (https://) +
    # "example" ASCII + 0x00 (".com/" expansion).
    payload = "10eb03" + "example".encode().hex() + "00"
    d = _dev(service_data=(("FEAA", payload),))
    out = decode_all(d)
    assert out["eddystone.frame"] == "URL"
    assert out["eddystone.url"] == "https://example.com/"
    assert out["eddystone.tx_power_at_0m"] == -21


def test_eddystone_url_decoding_handles_long_form_uuid_key():
    """Some helpers / stacks emit the FEAA key in 128-bit canonical
    form. The decoder should still recognise it."""
    payload = "10eb03" + "x".encode().hex() + "00"  # https://x.com/
    d = _dev(service_data=(("0000FEAA-0000-1000-8000-00805F9B34FB", payload),))
    out = decode_all(d)
    assert out["eddystone.frame"] == "URL"
    assert out["eddystone.url"] == "https://x.com/"


def test_eddystone_uid_decode():
    """UID frame: 10-byte namespace + 6-byte instance after the
    frame-type and tx-power bytes."""
    namespace = "00112233445566778899"
    instance = "aabbccddeeff"
    payload = "00ec" + namespace + instance + "0000"  # tx_power = -20
    d = _dev(service_data=(("FEAA", payload),))
    out = decode_all(d)
    assert out["eddystone.frame"] == "UID"
    assert out["eddystone.namespace"] == namespace
    assert out["eddystone.instance"] == instance
    assert out["eddystone.tx_power_at_0m"] == -20


def test_eddystone_tlm_decode():
    """TLM frame: battery mV + signed 8.8 °C + 32-bit ad count + 32-bit
    sec count (in 0.1 s units)."""
    # battery_mv = 0x0c1c = 3100 mV
    # temp = 0x16 0x80 → 22.5 °C  (0x16 = 22, 0x80 = 0.5)
    # ad_count = 0x0000_0042 = 66
    # sec_count = 0x0000_0190 = 400 → 40 s uptime
    payload = "20" "00" "0c1c" "1680" "00000042" "00000190"
    d = _dev(service_data=(("FEAA", payload),))
    out = decode_all(d)
    assert out["eddystone.frame"] == "TLM"
    assert out["eddystone.battery_mv"] == 3100
    assert abs(out["eddystone.temperature_c"] - 22.5) < 0.01
    assert out["eddystone.ad_count"] == 66
    assert out["eddystone.uptime_s"] == 40


def test_eddystone_eid_frame_recognised_but_not_decoded():
    """EID frames are encrypted; we recognise the type but emit no
    other fields. The label alone is useful for users wondering why
    a beacon shows no info."""
    d = _dev(service_data=(("FEAA", "30" + "00" * 9),))
    out = decode_all(d)
    assert out["eddystone.frame"] == "EID"
    assert "eddystone.url" not in out


def test_eddystone_skips_non_feaa_service_data():
    """Service-data on a different UUID (Xiaomi FE95, MS FDEE, etc.)
    must not be misread as Eddystone."""
    d = _dev(service_data=(("FE95", "1059635400e0c7121cfa34"),))
    out = decode_all(d)
    assert "eddystone.frame" not in out


def test_eddystone_skips_empty_service_data():
    """Defensive: malformed adv with empty service_data hex."""
    d = _dev(service_data=(("FEAA", ""),))
    out = decode_all(d)
    assert "eddystone.frame" not in out


def test_decode_all_returns_empty_for_truly_uninteresting_device():
    """A device with no manufacturer-data and no service-data should
    decode to nothing."""
    d = _dev()  # no payload at all
    assert decode_all(d) == {}


# ----------------------------------------------------------------------
# Apple Continuity Nearby Info (type 0x10)
# ----------------------------------------------------------------------

def test_nearby_info_canonical_short_form():
    """6-byte payload variant captured in the user's helper output."""
    # cid 4c00 + type 0x10 + length 0x06 + status 0x27 + class_os 0x1e
    # + 4-byte AppleID hash fe0b8af9
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c001006271efe0b8af9")
    out = decode_all(d)
    assert out["nearby_info.status_hex"] == "0x27"
    assert out["nearby_info.action_code_hi"] == 0x2
    assert out["nearby_info.flags_lo"] == 0x7
    assert out["nearby_info.class_byte_hex"] == "0x1e"
    assert out["nearby_info.os_hint_hi"] == 0x1
    assert out["nearby_info.device_class_lo"] == 0xe
    assert out["nearby_info.appleid_hash"] == "fe0b8af9"


def test_nearby_info_long_form_with_5_byte_hash():
    """7-byte length variant (also captured live)."""
    # cid + 1007 + status 0x34 + class_os 0x1f + 5-byte hash
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c001007341fca64aa5018")
    out = decode_all(d)
    assert out["nearby_info.appleid_hash"] == "ca64aa5018"


def test_nearby_info_skips_non_apple_cid():
    d = _dev(vendor_id=0x0006, manufacturer_hex="06001006271efe0b8af9")
    out = decode_all(d)
    assert "nearby_info.status_hex" not in out


def test_nearby_info_skips_when_type_byte_is_different():
    """A Find My broadcast must not be misread as Nearby Info."""
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c0012020002")
    out = decode_all(d)
    assert "nearby_info.status_hex" not in out


# ----------------------------------------------------------------------
# Apple Continuity Find My (type 0x12)
# ----------------------------------------------------------------------

def test_find_my_short_form_minimum_payload():
    """The most common Find My short broadcast: status + 1-byte hint."""
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c0012020002")
    out = decode_all(d)
    assert out["find_my.status_hex"] == "0x00"
    assert out["find_my.hint_hex"] == "0x02"


def test_find_my_short_form_with_nonzero_status():
    """The 0x6c status pattern showed up live; verify byte hex passes
    through verbatim."""
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c0012026c02")
    out = decode_all(d)
    assert out["find_my.status_hex"] == "0x6c"


def test_find_my_skips_when_too_short():
    """A frame missing the hint byte is malformed; abstain."""
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c00120100")
    out = decode_all(d)
    assert "find_my.status_hex" not in out


# ----------------------------------------------------------------------
# Apple Continuity Handoff (type 0x0C)
# ----------------------------------------------------------------------

def test_handoff_canonical_decode():
    """Real Handoff payload from the helper output (length 0x0e):
    flags + seq + 2-byte tag + 10-byte encrypted activity."""
    # cid 4c00 + 0c 0e flags=0x00 seq=0x08 tag=2eb8 activity=ce5ae1...
    # Note: this real packet ALSO chains a Nearby Info subframe at the
    # end (1006...), exercising the multi-subtype walker.
    d = _dev(
        vendor_id=0x004C,
        manufacturer_hex="4c000c0e00082eb8ce5ae1dbc2dfa97917631006731d54f15038",
    )
    out = decode_all(d)
    assert out["handoff.clipboard_present"] is False
    assert out["handoff.flags_hex"] == "0x00"
    assert out["handoff.seq"] == 0x08
    assert out["handoff.auth_tag"] == "2eb8"
    assert out["handoff.activity_id"] == "ce5ae1dbc2dfa9791763"


def test_handoff_with_clipboard_flag_set():
    """Clipboard-share advertisements set bit 0 of the flags byte."""
    d = _dev(
        vendor_id=0x004C,
        # flags = 0x01 (clipboard present), seq=0x08
        manufacturer_hex="4c000c0e01082eb8ce5ae1dbc2dfa97917631006731d54f15038",
    )
    out = decode_all(d)
    assert out["handoff.clipboard_present"] is True
    assert out["handoff.flags_hex"] == "0x01"


def test_handoff_chained_with_nearby_info_decodes_both():
    """The chained packet from the live capture should decode BOTH
    subframes — Handoff (the leading 0x0c subtype) and the trailing
    Nearby Info (0x10) — in one call."""
    d = _dev(
        vendor_id=0x004C,
        manufacturer_hex="4c000c0e00082eb8ce5ae1dbc2dfa97917631006731d54f15038",
    )
    out = decode_all(d)
    assert "handoff.activity_id" in out
    assert "nearby_info.status_hex" in out
    assert out["nearby_info.status_hex"] == "0x73"  # status byte of trailing 0x10
    assert out["nearby_info.appleid_hash"] == "54f15038"


def test_continuity_payload_walker_handles_truncated_tail():
    """A subframe whose declared length runs past the buffer should
    not crash the decoder, just abstain on that subframe."""
    # Length claims 0x10 (16 bytes) but only 4 follow.
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c0010104142434445")
    # Decoder should silently abstain rather than raising.
    out = decode_all(d)
    assert "nearby_info.status_hex" not in out


# ----------------------------------------------------------------------
# Microsoft CDP — device beacon (0x01)
# ----------------------------------------------------------------------

def test_ms_device_beacon_real_capture():
    """Exact bytes pulled from the helper's live output: a Surface /
    Windows machine emitting a CDP discovery beacon."""
    # cid=0x0006 LE + subtype 0x01 + device_type 0x0f + version 0x20
    # + flags 0x22 + salt 0aa05303 + device_hash 1aa3...43
    raw = "0600" "01" "0f" "20" "22" "0aa05303" "1aa38a734c9c14e7e55300d7e24b2bff811843"
    d = _dev(vendor_id=0x0006, manufacturer_hex=raw)
    out = decode_all(d)
    assert out["ms_cdp.subtype"] == "device beacon"
    assert out["ms_cdp.device_type"] == "0x0f"
    assert out["ms_cdp.version"] == "0x20"
    assert out["ms_cdp.flags"] == "0x22"
    assert out["ms_cdp.salt"] == "0aa05303"
    assert out["ms_cdp.device_hash"] == "1aa38a734c9c14e7e55300d7e24b2bff811843"


def test_ms_device_beacon_skips_when_subtype_is_swift_pair():
    """A Swift Pair payload (0x03) must not be misread as device beacon."""
    d = _dev(vendor_id=0x0006, manufacturer_hex="0600" "03" "01" "80")
    out = decode_all(d)
    assert "ms_cdp.subtype" not in out


def test_ms_device_beacon_skips_when_cid_is_apple():
    """Apple cid + bytes shaped like an MS subtype must not match."""
    d = _dev(vendor_id=0x004C, manufacturer_hex="4c00" "01" "0f20")
    out = decode_all(d)
    assert "ms_cdp.subtype" not in out


def test_ms_device_beacon_short_payload_partial_decode():
    """A truncated beacon should still surface the bytes that ARE
    present, not abstain wholesale. Tells the user the row IS an MS
    device beacon even though the salt/hash never arrived."""
    d = _dev(vendor_id=0x0006, manufacturer_hex="0600" "01" "0f")
    out = decode_all(d)
    assert out["ms_cdp.subtype"] == "device beacon"
    assert out["ms_cdp.device_type"] == "0x0f"
    assert "ms_cdp.salt" not in out


def test_ms_device_beacon_live_capture_pattern():
    """A second real-capture row using the more common 0x09 / 0x20
    header pattern observed across 20/20 rows in the office sample.
    Exercises field-name stability against the spec-friendly
    ``device_type / version / flags`` labelling."""
    raw = "0600" "01" "09" "20" "22" "9fcd1107" "42e70006845127ee204d2eb9360412f61a5d60"
    d = _dev(vendor_id=0x0006, manufacturer_hex=raw)
    out = decode_all(d)
    assert out["ms_cdp.device_type"] == "0x09"
    assert out["ms_cdp.version"] == "0x20"
    assert out["ms_cdp.flags"] == "0x22"
    assert out["ms_cdp.salt"] == "9fcd1107"


# ----------------------------------------------------------------------
# Microsoft CDP — Swift Pair (0x03 / 0x05 / 0x06 / 0x08)
# ----------------------------------------------------------------------

def test_swift_pair_decodes_utf8_model_name():
    """Canonical Swift Pair: subtype 0x03, sub-scenario 0x01,
    reserved RSSI 0x80, then UTF-8 'Surface Pen'."""
    name = "Surface Pen".encode("utf-8").hex()
    d = _dev(
        vendor_id=0x0006,
        manufacturer_hex="0600" "03" "01" "80" + name,
    )
    out = decode_all(d)
    assert out["swift_pair.subtype_hex"] == "0x03"
    assert out["swift_pair.sub_scenario"] == "0x01"
    assert out["swift_pair.reserved_rssi"] == "0x80"
    assert out["swift_pair.model"] == "Surface Pen"


def test_swift_pair_strips_trailing_nuls_in_model_name():
    """Some devices null-pad the model field. Don't render a name with
    visible NUL bytes."""
    name = "Razer Mouse".encode("utf-8").hex() + "0000"
    d = _dev(vendor_id=0x0006, manufacturer_hex="0600" "06" "01" "80" + name)
    out = decode_all(d)
    assert out["swift_pair.model"] == "Razer Mouse"


def test_swift_pair_handles_non_utf8_bytes_via_hex_fallback():
    """A malformed model field should not raise — emit hex instead."""
    # Random non-UTF-8 byte sequence
    d = _dev(
        vendor_id=0x0006,
        manufacturer_hex="0600" "03" "01" "80" "ffe080808080",
    )
    out = decode_all(d)
    assert "swift_pair.model" not in out
    assert out["swift_pair.model_hex"] == "ffe080808080"


def test_swift_pair_handles_subtype_0x06():
    """Swift Pair sub-scenario 0x06 (LE + BR/EDR) decodes the same
    way as 0x03."""
    name = "MX Master 3".encode("utf-8").hex()
    d = _dev(vendor_id=0x0006, manufacturer_hex="0600" "06" "00" "80" + name)
    out = decode_all(d)
    assert out["swift_pair.subtype_hex"] == "0x06"
    assert out["swift_pair.model"] == "MX Master 3"


def test_swift_pair_skips_unknown_subtype():
    """Microsoft cid + subtype not in the Swift Pair set abstains."""
    d = _dev(vendor_id=0x0006, manufacturer_hex="0600" "ff" "00" "80")
    out = decode_all(d)
    assert "swift_pair.subtype_hex" not in out


# ----------------------------------------------------------------------
# RuuviTag Format 5 (RAWv2)
# ----------------------------------------------------------------------

def test_ruuvi_format5_canonical_decode():
    """The canonical sample from the Ruuvi RAWv2 spec page:

      Temperature: 24.30 °C
      Humidity:    53.49 %
      Pressure:    1000.44 hPa
      Acc:         x=4 y=-4 z=1036 mG
      Battery:     2977 mV
      Tx power:    +4 dBm
      Movement:    66
      Seq:         205
      MAC:         CB:B8:33:4C:88:4F
    """
    raw = (
        "9904"            # cid 0x0499 LE
        "05"              # format 5
        "12fc"            # temperature: 0x12fc = 4860 → 4860 * 0.005 = 24.30 °C
        "5394"            # humidity: 0x5394 = 21396 → 53.49 %
        "c37c"            # pressure: 0x... + 50000 → 1000.44 hPa
        "0004"            # accel_x = 4 mG
        "fffc"            # accel_y = -4 mG
        "040c"            # accel_z = 1036 mG
        "ac36"            # power_info: voltage 2977 mV, tx +4 dBm
        "42"              # movement counter = 66
        "00cd"            # seq = 205
        "cbb8334c884f"    # MAC
    )
    d = _dev(vendor_id=0x0499, manufacturer_hex=raw)
    out = decode_all(d)
    assert out["ruuvi.format"] == 5
    assert abs(out["ruuvi.temperature_c"] - 24.30) < 0.01
    assert abs(out["ruuvi.humidity_pct"] - 53.49) < 0.01
    assert abs(out["ruuvi.pressure_hpa"] - 1000.44) < 0.01
    assert out["ruuvi.accel_mg"] == "x=4 y=-4 z=1036"
    assert out["ruuvi.battery_mv"] == 2977
    assert out["ruuvi.tx_power_dbm"] == 4
    assert out["ruuvi.movement_count"] == 66
    assert out["ruuvi.seq"] == 205
    assert out["ruuvi.mac"] == "cb:b8:33:4c:88:4f"


def test_ruuvi_invalid_sentinels_drop_fields():
    """When a sensor reports its "invalid" sentinel we drop the field
    rather than emit a misleading value (e.g. a -163 °C reading from
    a sensor that hasn't initialised yet)."""
    raw = (
        "9904"
        "05"
        "8000"            # temperature INVALID
        "ffff"            # humidity INVALID
        "ffff"            # pressure INVALID
        "8000" "8000" "8000"  # all accel INVALID
        "ffff"            # voltage 11-bit max + tx 5-bit max INVALID
        "ff"              # movement INVALID
        "ffff"            # seq INVALID
        "001122334455"    # MAC still valid (always 6 bytes)
    )
    d = _dev(vendor_id=0x0499, manufacturer_hex=raw)
    out = decode_all(d)
    assert out["ruuvi.format"] == 5
    assert "ruuvi.temperature_c" not in out
    assert "ruuvi.humidity_pct" not in out
    assert "ruuvi.pressure_hpa" not in out
    assert "ruuvi.accel_mg" not in out
    assert "ruuvi.battery_mv" not in out
    assert "ruuvi.tx_power_dbm" not in out
    assert "ruuvi.movement_count" not in out
    assert "ruuvi.seq" not in out
    assert out["ruuvi.mac"] == "00:11:22:33:44:55"


def test_ruuvi_skips_non_ruuvi_cid():
    """An advertisement on a different cid that happens to start with
    0x05 must not be misread as a Ruuvi v5 frame."""
    d = _dev(vendor_id=76, manufacturer_hex="4c00" "05" + "00" * 23)
    out = decode_all(d)
    assert "ruuvi.format" not in out


def test_ruuvi_skips_format_3():
    """Format 3 (RAWv1) packet on the Ruuvi cid: not implemented yet,
    but we must not pretend it's Format 5."""
    d = _dev(vendor_id=0x0499, manufacturer_hex="9904" "03" + "00" * 13)
    out = decode_all(d)
    assert "ruuvi.format" not in out


def test_ruuvi_skips_truncated_frame():
    """A Format 5 header but truncated body — abstain rather than
    indexing past the buffer."""
    d = _dev(vendor_id=0x0499, manufacturer_hex="9904" "05" + "00" * 10)
    out = decode_all(d)
    assert "ruuvi.format" not in out


# ----------------------------------------------------------------------
# Xiaomi / Anhui Huami
# ----------------------------------------------------------------------

def test_xiaomi_canonical_decode_with_body():
    """A real Xiaomi Mi Band-class advertisement captured in the field
    (cid 0x038F, frame byte 0x2a, 19 body bytes). The decoder should
    recognise the frame, surface the frame counter byte, and return
    the body bytes verbatim as hex so the user can compare across
    captures by hand."""
    raw = "8f03" "2a" "113461476f103041a20115262954bd57010302"
    d = _dev(vendor_id=0x038F, manufacturer_hex=raw)
    out = decode_all(d)
    assert out["xiaomi.cid"] == "0x038f"
    assert out["xiaomi.frame_seq"] == 0x2a
    assert out["xiaomi.body_hex"] == "113461476f103041a20115262954bd57010302"
    assert out["xiaomi.body_len"] == 19


def test_xiaomi_short_frame_decodes_just_frame_byte():
    """The ``8f03`` header-only advertisement (common after RPA
    rotations) decodes to an empty body without raising."""
    d = _dev(vendor_id=0x038F, manufacturer_hex="8f03")
    out = decode_all(d)
    assert out["xiaomi.cid"] == "0x038f"
    assert out["xiaomi.body_hex"] == ""
    assert out["xiaomi.body_len"] == 0
    # No frame_seq when the byte isn't there.
    assert "xiaomi.frame_seq" not in out


def test_xiaomi_skips_non_xiaomi_cid():
    """An advertisement on a different cid that happens to start with
    the same byte prefix must not be misread as Xiaomi."""
    d = _dev(vendor_id=76, manufacturer_hex="4c00" "8f03" + "2a")
    out = decode_all(d)
    assert "xiaomi.cid" not in out


def test_xiaomi_skips_malformed_hex():
    """A non-hex manufacturer string abstains (graceful, not raise)."""
    d = _dev(vendor_id=0x038F, manufacturer_hex="not-hex-bytes")
    out = decode_all(d)
    assert "xiaomi.cid" not in out


# ----------------------------------------------------------------------
# Generic manufacturer-data recogniser (long-tail vendors)
# ----------------------------------------------------------------------

def test_manufacturer_generic_surfaces_cid_and_body():
    """A vendored advert with no dedicated decoder (e.g. Polar, cid
    0x006B) yields mfg.cid + raw body, no invented semantics."""
    # cid 0x006b little-endian = "6b00", then a 5-byte body.
    d = _dev(vendor_id=0x006B, manufacturer_hex="6b00" "0102030405")
    out = decode_all(d)
    assert out["mfg.cid"] == "0x006b"
    assert out["mfg.body_hex"] == "0102030405"
    assert out["mfg.body_len"] == 5
    # No device classification is fabricated from the company-id.
    assert "device_type" not in out and "device_class" not in out


def test_manufacturer_generic_surfaces_vendor_name_when_known():
    from datetime import datetime, timezone
    now = datetime(2026, 5, 9, 13, 0, 0, tzinfo=timezone.utc)
    d = BLEDevice(
        identifier="x", name=None, vendor="Telink Semiconductor (Taipei) Co. Ltd.",
        vendor_id=0x0211, services=(), rssi_dbm=-70, is_connectable=True,
        first_seen=now, last_seen=now, ad_count=1,
        manufacturer_hex="1102" "aabbcc", service_data=(),
    )
    out = decode_all(d)
    assert out["mfg.cid"] == "0x0211"
    assert out["mfg.vendor"] == "Telink Semiconductor (Taipei) Co. Ltd."
    assert out["mfg.body_hex"] == "aabbcc"


def test_manufacturer_generic_skips_dedicated_cids():
    """Vendors with a dedicated decoder don't also get a redundant mfg.* row."""
    for cid, hexpfx in ((0x004C, "4c00"), (0x0006, "0600"), (0x038F, "8f03"), (0x0499, "9904")):
        d = _dev(vendor_id=cid, manufacturer_hex=hexpfx + "0011")
        out = decode_all(d)
        assert "mfg.cid" not in out, f"cid 0x{cid:04x} should be skipped"


def test_manufacturer_generic_abstains_without_or_on_short_mfg():
    assert "mfg.cid" not in decode_all(_dev(vendor_id=0x006B, manufacturer_hex=None))
    # Only the cid prefix survived (no body) → too short to be a frame.
    assert "mfg.cid" not in decode_all(_dev(vendor_id=0x006B, manufacturer_hex="6b"))
    # Header-only (cid prefix exactly) → recognised with empty body.
    out = decode_all(_dev(vendor_id=0x006B, manufacturer_hex="6b00"))
    assert out["mfg.cid"] == "0x006b" and out["mfg.body_len"] == 0
