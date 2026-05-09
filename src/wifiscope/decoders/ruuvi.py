"""RuuviTag environmental sensor decoder.

RuuviTag broadcasts temperature / humidity / pressure / acceleration
/ battery in its manufacturer-data field (cid 0x0499 = "Ruuvi
Innovations Ltd"). The device is open-source hardware, the spec is
public, and the byte layout has been stable since 2018:

  https://docs.ruuvi.com/communication/bluetooth-advertisements/data-format-5-rawv2

This decoder handles **Format 5 (RAWv2)**, the format every modern
RuuviTag firmware emits. Format 3 (RAWv1, deprecated) and format 8
(encrypted) are not implemented — Format 5 is what users actually
see on hardware shipped after ~2019.

Output keys: ``ruuvi.*``. Sensor readings come back in their
"natural" units (°C, %, hPa, mV, dBm) rather than the protocol's
fixed-point integers, so the modal can show them directly.
"""
from __future__ import annotations

from typing import Any

from ..ble import BLEDevice
from . import register

_RUUVI_CID = 0x0499
_FORMAT_5 = 0x05

_INVALID_TEMP = -32768  # sentinel for sensor failure
_INVALID_HUMIDITY = 0xFFFF
_INVALID_PRESSURE = 0xFFFF
_INVALID_ACCEL = -32768
_INVALID_VOLT = 0x7FF  # 11-bit max
_INVALID_TX = 0x1F  # 5-bit max
_INVALID_MOVEMENT = 0xFF
_INVALID_SEQ = 0xFFFF


def _signed16_be(b: bytes) -> int:
    v = (b[0] << 8) | b[1]
    return v - 0x10000 if v >= 0x8000 else v


@register
def decode(d: BLEDevice) -> dict[str, Any] | None:
    """RuuviTag Format 5 (RAWv2) decoder.

    Layout (post-format byte, 23 data bytes):

      [0..1]    temperature  signed 16 BE, 0.005 °C / unit
      [2..3]    humidity     unsigned 16 BE, 0.0025 % / unit
      [4..5]    pressure     unsigned 16 BE, Pa offset by 50000
      [6..7]    accel_x      signed 16 BE, mG
      [8..9]    accel_y      signed 16 BE, mG
      [10..11]  accel_z      signed 16 BE, mG
      [12..13]  power_info   bits[15:5] = battery_mv − 1600,
                             bits[4:0]  = (tx_power_dbm + 40) / 2
      [14]      movement_ctr unsigned, increments on motion
      [15..16]  seq_no       unsigned 16 BE, packet sequence
      [17..22]  mac          BLE MAC address (6 bytes BE)

    Each field has a documented "invalid" sentinel; we drop those
    fields rather than emit nonsensical values like temperature −163 °C.
    """
    if d.vendor_id != _RUUVI_CID:
        return None
    if not d.manufacturer_hex:
        return None
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    # cid (2) + format (1) + 23 data bytes = 26 bytes
    if len(blob) < 26:
        return None
    if blob[2] != _FORMAT_5:
        return None
    body = blob[3:26]

    out: dict[str, Any] = {"ruuvi.format": 5}

    temp_raw = _signed16_be(body[0:2])
    if temp_raw != _INVALID_TEMP:
        out["ruuvi.temperature_c"] = round(temp_raw * 0.005, 2)

    hum_raw = (body[2] << 8) | body[3]
    if hum_raw != _INVALID_HUMIDITY:
        out["ruuvi.humidity_pct"] = round(hum_raw * 0.0025, 2)

    press_raw = (body[4] << 8) | body[5]
    if press_raw != _INVALID_PRESSURE:
        # Spec stores Pa offset by 50000; convert to hPa for display.
        out["ruuvi.pressure_hpa"] = round((press_raw + 50000) / 100.0, 2)

    ax = _signed16_be(body[6:8])
    ay = _signed16_be(body[8:10])
    az = _signed16_be(body[10:12])
    accels = []
    for axis_name, raw in (("x", ax), ("y", ay), ("z", az)):
        if raw != _INVALID_ACCEL:
            accels.append((axis_name, raw))
    if len(accels) == 3:
        out["ruuvi.accel_mg"] = (
            f"x={accels[0][1]} y={accels[1][1]} z={accels[2][1]}"
        )

    power = (body[12] << 8) | body[13]
    voltage_raw = (power >> 5) & 0x7FF
    tx_raw = power & 0x1F
    if voltage_raw != _INVALID_VOLT:
        out["ruuvi.battery_mv"] = voltage_raw + 1600
    if tx_raw != _INVALID_TX:
        out["ruuvi.tx_power_dbm"] = (tx_raw * 2) - 40

    if body[14] != _INVALID_MOVEMENT:
        out["ruuvi.movement_count"] = body[14]

    seq = (body[15] << 8) | body[16]
    if seq != _INVALID_SEQ:
        out["ruuvi.seq"] = seq

    # MAC is always 6 bytes; surface as colon-separated hex for
    # parity with our other id formats. Helpful when the user has
    # multiple Ruuvi tags and wants to tell them apart by sticker.
    mac_bytes = body[17:23]
    out["ruuvi.mac"] = ":".join(f"{b:02x}" for b in mac_bytes)

    return out
