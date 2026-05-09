# Tasks — document ble-decoders

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/decoders/__init__.py` (registry, decode_all), `ibeacon.py`, `eddystone.py`, `apple_continuity.py`, `microsoft_cdp.py`, `ruuvi.py`.
- [x] 1.2 Cross-checked against `tests/test_decoders.py` — all 40 unit tests reflect the contract above.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "BLE devices" section explains the protocol-namespaced output convention so users reading the modal know what `nearby_info.status_hex` means.
- [x] 2.2 Add a `decoders/CONTRIBUTING.md` short note pointing at this spec.
