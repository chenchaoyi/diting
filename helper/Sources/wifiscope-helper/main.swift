// wifiscope-helper — Swift sidecar that owns the macOS Location Services
// and Bluetooth permissions so the Python TUI can read unredacted scan-list
// SSIDs / BSSIDs and stream nearby BLE advertisements.
//
// Three roles in one binary:
//
//   wifiscope-helper           (no args, launched as a .app from Finder
//                               via `open` or by Launch Services)
//                              -> opens a small AppKit window, requests
//                                 Location Services AND Bluetooth
//                                 authorization, parks until the user
//                                 closes the window so the bundle stays
//                                 foregrounded long enough for the
//                                 system prompts.
//
//   wifiscope-helper scan      (invoked by the Python backend as a
//                               subprocess)
//                              -> performs a CoreWLAN scan, prints a
//                                 single JSON document {"networks": [...]}
//                                 to stdout, exits.
//
//   wifiscope-helper ble-scan  (invoked by the Python backend as a
//                               long-running subprocess)
//                              -> initialises CBCentralManager and
//                                 streams JSON Lines (one ad per line)
//                                 to stdout until SIGTERM / pipe close.
//
// The bundle's Info.plist declares NSLocationUsageDescription and
// NSBluetoothAlwaysUsageDescription, so the .app shows up in System
// Settings -> Privacy & Security -> Location Services AND Bluetooth
// after first launch and is grantable for both. Once granted, the CLI
// subprocesses inherit the bundle's TCC identity and CoreWLAN /
// CoreBluetooth return full data.

import Cocoa
import CoreBluetooth
import CoreLocation
import CoreWLAN
import Foundation
// IOBluetooth is needed for the connected-peripherals enumeration.
// CoreBluetooth's retrieveConnectedPeripherals(withServices:) only
// returns peripherals connected via a CBCentralManager.connect()
// call from some user-space app — it does NOT see system-level
// connections (Magic Keyboard / Mouse via HID, AirPods via A2DP,
// etc.) which are managed entirely outside CoreBluetooth. Those
// surface only through IOBluetooth's pairedDevices() roster, the
// same path System Settings and `system_profiler SPBluetoothDataType`
// take. IOBluetooth is "soft-deprecated" but fully functional on
// macOS 26 and remains the only public API for this query.
import IOBluetooth

// ---------------------------------------------------------------------
// CLI mode: scan
// ---------------------------------------------------------------------

func runScanAndDumpJSON() -> Never {
    let client = CWWiFiClient.shared()
    guard let iface = client.interface() else {
        emitError("no Wi-Fi interface")
    }

    let networks: Set<CWNetwork>
    do {
        networks = try iface.scanForNetworks(withName: nil)
    } catch {
        emitError("scan failed: \(error.localizedDescription)")
    }

    let timestamp = ISO8601DateFormatter().string(from: Date())
    var out: [[String: Any]] = []
    for net in networks {
        var row: [String: Any] = [:]
        if let s = net.ssid { row["ssid"] = s }
        if let b = net.bssid { row["bssid"] = b }
        if let cc = net.countryCode { row["country_code"] = cc }
        row["rssi_dbm"] = net.rssiValue
        row["noise_dbm"] = net.noiseMeasurement
        if let ch = net.wlanChannel {
            row["channel"] = ch.channelNumber
            row["channel_width_raw"] = ch.channelWidth.rawValue
            row["channel_band_raw"] = ch.channelBand.rawValue
        }
        row["security_raw"] = sampleSecurity(net)
        // Schema-3 (v0.7.0+) IE parsing. CoreWLAN exposes the raw
        // beacon information-element data via informationElementData;
        // we walk the Element ID / length tuples to surface the few
        // bits diagnostics actually want. Each field is emitted only
        // when the corresponding IE is present, so v2 consumers (or
        // a partial scan with no IEs) keep the existing keyset.
        if let ieData = net.informationElementData {
            decodeBeaconIEs(ieData, into: &row)
        }
        out.append(row)
    }

    var ifaceMeta: [String: Any] = ["name": iface.interfaceName ?? "?"]
    if let cc = iface.countryCode() { ifaceMeta["country_code"] = cc }
    if let hw = iface.hardwareAddress() { ifaceMeta["hardware_address"] = hw }

    let payload: [String: Any] = [
        // schema 3 = v0.6.0+: BLE deep-ID fields (type / device_class)
        // and connected-peripheral lines, plus v0.7.0+ Wi-Fi beacon-IE
        // fields (bss_load_pct / bss_station_count / supports_802_11r
        // / supports_802_11k / supports_802_11v). The schema number
        // does not change between v0.6.0 and v0.7.0; the IE fields
        // are additive and consumers tolerate their absence (older
        // helpers that ship schema=3 without IE keys remain valid).
        "schema": 3,
        "interface": ifaceMeta,
        "timestamp": timestamp,
        "networks": out,
    ]
    do {
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
        exit(0)
    } catch {
        emitError("json encode failed: \(error.localizedDescription)")
    }
}

// Decode the few beacon information elements diagnostics-grade
// callers care about: BSS Load (utilisation / station count), 802.11k
// (Radio Measurement Enabled Capabilities), 802.11r (Mobility Domain),
// and 802.11v (Extended Capabilities bit 19, BSS Transition). We walk
// the IE buffer as raw <id, length, payload> tuples; defensive against
// truncated payloads, since CoreWLAN occasionally hands back a buffer
// whose advertised length runs past the data end on certain APs.
func decodeBeaconIEs(_ data: Data, into row: inout [String: Any]) {
    var i = 0
    let bytes = [UInt8](data)
    while i + 2 <= bytes.count {
        let id = bytes[i]
        let length = Int(bytes[i + 1])
        let start = i + 2
        let end = start + length
        if end > bytes.count { break }
        let payload = Array(bytes[start..<end])
        switch id {
        case 11:
            // BSS Load — five bytes in the standard form.
            //   bytes 0-1: station_count (uint16, little-endian)
            //   byte    2: channel_utilisation (0..255 → 0..100%)
            //   bytes 3-4: available_admission_capacity (we ignore)
            if payload.count >= 3 {
                let stationCount = Int(payload[0]) | (Int(payload[1]) << 8)
                let utilByte = Int(payload[2])
                // Channel utilisation is reported as a value in
                // 0..255 representing the fraction of time the AP
                // observed the medium busy. Convert to a 0..100%
                // integer: percent = round(byte * 100 / 255).
                let pct = (utilByte * 100 + 127) / 255
                row["bss_load_pct"] = pct
                row["bss_station_count"] = stationCount
            }
        case 54:
            // Mobility Domain IE — presence alone signals 802.11r.
            row["supports_802_11r"] = true
        case 70:
            // RM Enabled Capabilities IE — its presence signals
            // 802.11k support (any of the radio-measurement bits).
            row["supports_802_11k"] = true
        case 127:
            // Extended Capabilities IE — bit 19 (3rd byte, bit 3
            // counting from LSB of byte 2 in 0-indexed terms) is
            // BSS Transition Management, the 802.11v feature most
            // commonly meant by "supports v".
            // Bits are indexed from LSB of byte 0.
            //   bit 19 → byte index 2 (19 / 8), bit position 3.
            if payload.count >= 3 {
                let byte2 = payload[2]
                if (byte2 & (1 << 3)) != 0 {
                    row["supports_802_11v"] = true
                }
            }
        default:
            break
        }
        i = end
    }
}

// CWNetwork.security is a method on CWInterface, not CWNetwork. Pull
// the security level via supportsSecurity for the common modes; on
// older macOS some constants may be unavailable. Best-effort.
func sampleSecurity(_ net: CWNetwork) -> Int {
    let candidates: [CWSecurity] = [
        .none, .WEP, .wpaPersonal, .wpa2Personal, .wpa3Personal,
        .wpaEnterprise, .wpa2Enterprise, .wpa3Enterprise,
    ]
    for s in candidates where net.supportsSecurity(s) {
        return s.rawValue
    }
    return -1
}

func emitError(_ message: String) -> Never {
    let payload: [String: Any] = ["error": message]
    if let data = try? JSONSerialization.data(withJSONObject: payload) {
        FileHandle.standardError.write(data)
        FileHandle.standardError.write("\n".data(using: .utf8)!)
    }
    exit(2)
}

// ---------------------------------------------------------------------
// CLI mode: ble-scan
// ---------------------------------------------------------------------

/// Result of running the public-format detection over a single
/// advertisement payload. Both fields are optional and either or both
/// may be nil when nothing is recognisable. We deliberately stop short
/// of decoding encrypted Continuity bits — only well-documented,
/// publicly-defined formats are surfaced.
struct BLEDetection {
    let type: String?         // "iBeacon" | "AirTag" | "Eddystone-URL" | ...
    let deviceClass: String?  // "iPhone" | "Mac" | "Apple Watch" | ...
}

/// Public-format BLE advertisement classifier. Mirrors the Python-side
/// fallback in `wifiscope/ble.py` byte-for-byte; both implementations
/// share the same conservative scope (Tier 1 categories only). See
/// `docs/specs/v0.6.0-ble-deep-identification.md` for the detection
/// rules.
enum BLEAdParser {
    /// Bluetooth SIG company IDs (little-endian uint16) we branch on.
    private static let companyAppleID = 0x004C
    private static let companyMicrosoftID = 0x0006
    private static let companySamsungID = 0x0075

    static func detect(advertisementData: [String: Any]) -> BLEDetection {
        let services = serviceUUIDStrings(advertisementData)
        let mfg = (advertisementData[CBAdvertisementDataManufacturerDataKey] as? Data)
            .flatMap { d -> [UInt8]? in d.count >= 2 ? Array(d) : nil }
        let companyID: Int? = mfg.map { Int($0[0]) | (Int($0[1]) << 8) }

        // 1. Manufacturer-data branches are checked first because they
        //    carry richer disambiguators than service UUIDs alone (the
        //    same FD5A UUID covers Apple Find My and Samsung SmartTag,
        //    for example, and only the company ID resolves the ambiguity).
        if let bytes = mfg, let cid = companyID {
            if cid == companyAppleID, bytes.count >= 3 {
                let typeByte = bytes[2]
                switch typeByte {
                case 0x02:
                    return BLEDetection(type: "iBeacon", deviceClass: nil)
                case 0x10:
                    // Apple Nearby Info. The device-class nibble sits
                    // in the high half of byte index 5 (after the type
                    // and length). Bytes beyond that are encrypted.
                    let dc = bytes.count >= 6 ? appleNearbyInfoDeviceClass(bytes[5]) : nil
                    return BLEDetection(type: nil, deviceClass: dc)
                case 0x12:
                    // Apple Find My target. Distinguish AirTag (owner-
                    // paired sub-type, length >= 25) from a generic
                    // Find My target (lost mode, shorter payload).
                    let isAirTag = bytes.count >= 25
                    return BLEDetection(
                        type: isAirTag ? "AirTag" : "Find My target",
                        deviceClass: nil,
                    )
                default:
                    if let label = appleContinuityType(typeByte) {
                        return BLEDetection(type: label, deviceClass: nil)
                    }
                }
            }
            if cid == companyMicrosoftID, bytes.count >= 3 {
                if bytes[2] == 0x03 {
                    return BLEDetection(type: "Swift Pair", deviceClass: nil)
                }
            }
            if cid == companySamsungID, services.contains("FD5A") {
                return BLEDetection(type: "SmartTag", deviceClass: nil)
            }
        }

        // 2. Service-UUID based detections. These are checked after
        //    manufacturer-data specifically so a Samsung SmartTag (which
        //    advertises FD5A) is labelled "SmartTag" via the company-ID
        //    branch above instead of being miscategorised as Apple Find
        //    My here.
        if services.contains("FEAA") {
            // Eddystone — the frame-type byte is the first byte of the
            // service-data IE (CBAdvertisementDataServiceDataKey).
            if let serviceData = advertisementData[CBAdvertisementDataServiceDataKey]
                as? [CBUUID: Data]
            {
                for (uuid, data) in serviceData where
                    uuid.uuidString.uppercased().hasSuffix("FEAA")
                {
                    if let frameType = data.first {
                        switch frameType {
                        case 0x00: return BLEDetection(type: "Eddystone-UID", deviceClass: nil)
                        case 0x10: return BLEDetection(type: "Eddystone-URL", deviceClass: nil)
                        case 0x20: return BLEDetection(type: "Eddystone-TLM", deviceClass: nil)
                        case 0x40: return BLEDetection(type: "Eddystone-EID", deviceClass: nil)
                        default: break
                        }
                    }
                }
            }
            return BLEDetection(type: "Eddystone", deviceClass: nil)
        }
        if services.contains("FEED") || services.contains("FEEC") {
            return BLEDetection(type: "Tile", deviceClass: nil)
        }
        if services.contains("FD5A") {
            // No Samsung company ID with this UUID → Apple Find My
            // accessory advertising in nearby mode (e.g. AirTag in
            // Found mode without an owner-ping payload).
            return BLEDetection(type: "Find My target", deviceClass: nil)
        }

        return BLEDetection(type: nil, deviceClass: nil)
    }

    /// Map the high nibble of the Apple Nearby Info action byte to a
    /// human-readable device class. Lower-nibble bits are activity /
    /// status flags and we ignore them. Mapping is reverse-engineered
    /// from the `furiousMAC/continuity` reference; per-model precision
    /// (iPhone 14 vs 15) is impossible from this byte alone.
    private static func appleNearbyInfoDeviceClass(_ actionByte: UInt8) -> String? {
        switch (actionByte >> 4) & 0x0F {
        case 0x1: return "iPhone"
        case 0x2: return "iPad"
        case 0x4: return "Mac"
        case 0x6: return "Apple TV"
        case 0x7: return "HomePod"
        case 0x9: return "Apple Watch"
        default: return nil
        }
    }

    /// Apple Continuity protocol type-byte → human label. Mirrors the
    /// Python-side ``_APPLE_CONTINUITY_TYPE`` map (ble.py) byte-for-byte;
    /// updates must land in both. Reverse-engineered from the public
    /// ``furiousMAC/continuity`` reference. Type bytes 0x02 / 0x10 / 0x12
    /// are handled inline above because they emit deviceClass payloads
    /// or have length-dependent sub-labels.
    private static func appleContinuityType(_ typeByte: UInt8) -> String? {
        switch typeByte {
        case 0x05: return "AirDrop"
        case 0x07: return "AirPods"
        case 0x09: return "AirPlay target"
        case 0x0A: return "AirPlay source"
        case 0x0B: return "Watch pairing"
        case 0x0C: return "Handoff"
        case 0x0D: return "Tethering target"
        case 0x0E: return "Tethering source"
        case 0x0F: return "Nearby Action"
        default: return nil
        }
    }

    private static func serviceUUIDStrings(_ ad: [String: Any]) -> Set<String> {
        var out: Set<String> = []
        if let services = ad[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] {
            for s in services { out.insert(s.uuidString.uppercased()) }
        }
        if let services = ad[CBAdvertisementDataOverflowServiceUUIDsKey] as? [CBUUID] {
            for s in services { out.insert(s.uuidString.uppercased()) }
        }
        if let services = ad[CBAdvertisementDataServiceDataKey] as? [CBUUID: Data] {
            for k in services.keys { out.insert(k.uuidString.uppercased()) }
        }
        return out
    }
}

/// 16-bit Bluetooth SIG service UUIDs we ask CoreBluetooth to enumerate
/// when listing currently-connected peripherals. A deliberately broad
/// union covering Audio, HID, Heart Rate / Battery / Health Thermometer,
/// Find My, Eddystone, and Tile — common bands the user likely cares
/// about. Anything more obscure (Bluetooth Mesh, exotic Health Devices)
/// is acceptable to miss for v0.6.0.
private let kConnectedServiceUUIDs: [CBUUID] = [
    // Audio profiles
    CBUUID(string: "1108"), CBUUID(string: "110A"), CBUUID(string: "110B"),
    CBUUID(string: "110C"), CBUUID(string: "110D"), CBUUID(string: "110E"),
    CBUUID(string: "110F"), CBUUID(string: "111E"),
    // HID
    CBUUID(string: "1124"), CBUUID(string: "1812"),
    // Heart Rate, Battery, Health Thermometer
    CBUUID(string: "180D"), CBUUID(string: "180F"), CBUUID(string: "1809"),
    // Find My
    CBUUID(string: "FD5A"), CBUUID(string: "FE9F"),
    // Eddystone, Tile
    CBUUID(string: "FEAA"), CBUUID(string: "FEED"), CBUUID(string: "FEEC"),
]

/// CBCentralManager driver for the `ble-scan` subcommand. One JSON
/// object per advertisement is written to stdout, terminated by a
/// newline; the Python side reads the pipe line-by-line.
///
/// In addition to advertisement events, every ~5 s the scanner snapshots
/// `retrieveConnectedPeripherals(withServices:)` and emits one
/// `{"connected": true, ...}` JSON line per returned peripheral followed
/// by a `connected_snapshot` sentinel. This surfaces things the user is
/// actually using right now (AirPods, Magic Keyboard, Apple Watch) which
/// are not advertising and so otherwise invisible to the BLE panel.
///
/// Permission failures (`.unauthorized`) emit a single JSON error line
/// and exit code 3 so the Python poller can distinguish "no Bluetooth
/// grant" from "no devices yet" or "subprocess crashed".
final class BLEScanner: NSObject, CBCentralManagerDelegate {
    private var central: CBCentralManager!
    private var connectedTimer: DispatchSourceTimer?
    private let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    func start() {
        // Run on the main queue so the run loop processes delegate
        // callbacks while the executable is parked in dispatchMain().
        central = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            // CBCentralManagerScanOptionAllowDuplicatesKey=true ensures
            // we get every advertisement, not just the first per device,
            // which is essential for tracking RSSI changes and `ad_count`.
            central.scanForPeripherals(
                withServices: nil,
                options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
            )
            startConnectedSnapshotTimer()
        case .unauthorized:
            emitBLEErrorAndExit("bluetooth unauthorized", code: 3)
        case .poweredOff:
            emitBLEErrorAndExit("bluetooth powered off", code: 4)
        case .unsupported:
            emitBLEErrorAndExit("bluetooth unsupported on this hardware", code: 5)
        case .resetting, .unknown:
            // Transient — wait for the next state update.
            return
        @unknown default:
            return
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        var row: [String: Any] = [
            "ts": isoFormatter.string(from: Date()),
            "id": peripheral.identifier.uuidString,
        ]
        // CoreBluetooth uses RSSI = 127 as the documented "no reading
        // available" sentinel. Any value at or above ~0 dBm is also
        // implausible for a received-power reading. Either case: omit
        // the field so the Python side renders "?" / dim, instead of
        // letting the sentinel ride into the panel as a "very strong"
        // signal that climbs to the top of the list and corrupts the
        // diagnostic-panel Closest line.
        let rssi = RSSI.intValue
        if rssi < 0 && rssi > -200 {
            row["rssi_dbm"] = rssi
        }

        // Apple-provided local name (truthier than the cached
        // peripheral.name when the device rotates its identifier).
        if let local = advertisementData[CBAdvertisementDataLocalNameKey] as? String {
            row["name"] = local
        } else if let name = peripheral.name {
            row["name"] = name
        }

        if let connectable = advertisementData[CBAdvertisementDataIsConnectable] as? NSNumber {
            row["is_connectable"] = connectable.boolValue
        } else {
            row["is_connectable"] = false
        }

        if let services = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] {
            row["service_uuids"] = services.map { $0.uuidString }
        }

        if let mfg = advertisementData[CBAdvertisementDataManufacturerDataKey] as? Data,
           mfg.count >= 2 {
            // Bluetooth SIG company IDs are little-endian uint16 in the
            // first two bytes of the manufacturer-specific payload.
            let companyID = Int(mfg[0]) | (Int(mfg[1]) << 8)
            row["manufacturer_id"] = companyID
            row["manufacturer_hex"] = mfg.map { String(format: "%02x", $0) }.joined()
        }

        // Schema-3 deep identification: tag the row with whatever
        // public-format detection produced. Both fields are optional;
        // unrecognised devices simply omit them.
        let detection = BLEAdParser.detect(advertisementData: advertisementData)
        if let t = detection.type { row["type"] = t }
        if let dc = detection.deviceClass { row["device_class"] = dc }

        emitJSONLine(row)
    }

    /// Periodic enumeration of connected peripherals. We don't
    /// `connect()` or `readRSSI()` — both would be invasive perturbations
    /// of the user's active Bluetooth links. The list comes back without
    /// a signal reading; the Python panel renders `—` for that column.
    private func startConnectedSnapshotTimer() {
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now(), repeating: 5.0)
        timer.setEventHandler { [weak self] in
            self?.emitConnectedSnapshot()
        }
        timer.resume()
        connectedTimer = timer
    }

    private func emitConnectedSnapshot() {
        // Source the roster via IOBluetooth, NOT
        // CBCentralManager.retrieveConnectedPeripherals(...) — see the
        // import-block comment for why CoreBluetooth misses every
        // system-paired keyboard / mouse / headphone. IOBluetooth's
        // pairedDevices() roster is what System Settings sees.
        guard let paired = IOBluetoothDevice.pairedDevices()
                as? [IOBluetoothDevice] else {
            // Even an empty list is a useful signal; surface zero with
            // a sentinel so the Python panel can clear any stale rows.
            let sentinel: [String: Any] = [
                "ts": isoFormatter.string(from: Date()),
                "connected_snapshot": true,
                "count": 0,
                "ids": [String](),
            ]
            emitJSONLine(sentinel)
            return
        }

        var emittedIDs: [String] = []
        for device in paired {
            // isConnected() checks live status — paired-but-disconnected
            // headphones in the next room would otherwise pollute the
            // "what am I using right now" list.
            guard device.isConnected() else { continue }
            // The device's BT MAC is the most stable identifier we have
            // (CoreBluetooth's per-host UUIDs do not exist for
            // IOBluetooth-managed devices). Lower-case to match the
            // Python side's BSSID convention; treat as opaque string
            // identifier downstream.
            guard let addr = device.addressString else { continue }
            let id = addr.lowercased()
            emittedIDs.append(id)
            var row: [String: Any] = [
                "ts": isoFormatter.string(from: Date()),
                "connected": true,
                "id": id,
            ]
            if let name = device.name, !name.isEmpty {
                row["name"] = name
            }
            // IOBluetoothDevice exposes a "class of device" record, not
            // an iterable services list like CBPeripheral. Translate
            // the major class into the primary 16-bit service UUID for
            // that category, so the Python side's existing
            // service_category() lookup picks the connected row up
            // with the same machinery it uses for advertising rows
            // (no parallel category-hint field needed).
            if let primaryUUID = bluetoothPrimaryServiceUUID(device) {
                row["service_uuids"] = [primaryUUID]
            }
            emitJSONLine(row)
        }

        let sentinel: [String: Any] = [
            "ts": isoFormatter.string(from: Date()),
            "connected_snapshot": true,
            "count": emittedIDs.count,
            "ids": emittedIDs,
        ]
        emitJSONLine(sentinel)
    }

    /// Translate IOBluetooth's major device-class enum into the 16-bit
    /// Bluetooth SIG service UUID that the Python side's
    /// `service_category()` already maps to a category label. We pick
    /// one canonical UUID per category — this is a *display hint* for
    /// the panel, not an authoritative list of every service the
    /// peripheral exposes (we cannot enumerate that without an active
    /// GATT connection). Returns nil when the class does not map.
    private func bluetoothPrimaryServiceUUID(
        _ device: IOBluetoothDevice
    ) -> String? {
        // Framework constants are declared as Int while
        // deviceClassMajor is BluetoothDeviceClassMajor (UInt32) —
        // cast both sides to Int for the switch to accept the patterns.
        let major = Int(device.deviceClassMajor)
        switch major {
        case kBluetoothDeviceClassMajorPeripheral:
            // Keyboards, mice, joysticks. 1812 = HID Service.
            return "1812"
        case kBluetoothDeviceClassMajorAudio:
            // 110A = Audio Source. Generic enough for the panel to
            // label as "Audio".
            return "110A"
        case kBluetoothDeviceClassMajorHealth:
            // 180D = Heart Rate Service. Imperfect (Health major class
            // is broader than HR) but it is the only Health label
            // mapped in the Python catalog.
            return "180D"
        default:
            return nil
        }
    }

    private func emitJSONLine(_ row: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: row, options: []) else {
            return
        }
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
}

func emitBLEErrorAndExit(_ message: String, code: Int32) -> Never {
    let payload: [String: Any] = ["error": message]
    if let data = try? JSONSerialization.data(withJSONObject: payload) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
    exit(code)
}

// macOS attaches every spawned process a "responsible" pid for TCC
// purposes — typically the GUI ancestor that started the chain (e.g.
// Warp, iTerm2, Terminal). When wifiscope's Python TUI invokes us as
// `<bundle>/Contents/MacOS/wifiscope-helper ble-scan` from inside such
// a terminal, the responsible process is the terminal app, *not* this
// helper. CoreBluetooth's TCC check then looks up
// NSBluetoothAlwaysUsageDescription in the responsible app's
// Info.plist — which never declares it — and SIGABRTs us with a
// privacy-violation crash.
//
// The fix is to disclaim our inherited responsibility before doing
// any TCC-protected work, so the kernel records *us* as our own
// responsible process. This is done by posix_spawn'ing ourselves once
// with a private spawn-attribute (`responsibility_spawnattrs_setdisclaim`)
// and exiting in the original process. The re-spawned child sees its
// own bundle Info.plist (now embedded into __TEXT,__info_plist as well
// as Contents/Info.plist), TCC accepts the usage description, and the
// scan proceeds normally. The disclaim env-var stops infinite recursion.
//
// CoreLocation's TCC check is more lenient than CoreBluetooth's — it
// resolves usage descriptions via Bundle.main with a fallback path —
// which is why the existing `scan` (Wi-Fi) subcommand works without
// disclaim. Only the BLE path needs this hop.

@_silgen_name("responsibility_spawnattrs_setdisclaim")
private func responsibility_spawnattrs_setdisclaim(
    _ attrs: UnsafeMutablePointer<posix_spawnattr_t?>, _ disclaim: Int32
) -> Int32

private let kDisclaimEnv = "WIFISCOPE_HELPER_DISCLAIMED"

private func reExecWithDisclaimedResponsibility() -> Never {
    var attrs: posix_spawnattr_t? = nil
    posix_spawnattr_init(&attrs)
    defer { posix_spawnattr_destroy(&attrs) }
    _ = responsibility_spawnattrs_setdisclaim(&attrs, 1)

    // Inherit the original argv exactly. Our binary path is argv[0].
    let exePath = strdup(CommandLine.arguments[0])!
    defer { free(exePath) }

    let argvCopies: [UnsafeMutablePointer<CChar>] = CommandLine.arguments.map { strdup($0)! }
    defer { argvCopies.forEach { free($0) } }
    var argv: [UnsafeMutablePointer<CChar>?] = argvCopies.map { Optional($0) }
    argv.append(nil)

    // Add the disclaim marker to the environment so the child knows
    // it has already been re-spawned and proceeds straight to the
    // scanner instead of looping back here.
    var env = ProcessInfo.processInfo.environment
    env[kDisclaimEnv] = "1"
    let envCopies: [UnsafeMutablePointer<CChar>] = env.map { strdup("\($0.key)=\($0.value)")! }
    defer { envCopies.forEach { free($0) } }
    var envp: [UnsafeMutablePointer<CChar>?] = envCopies.map { Optional($0) }
    envp.append(nil)

    var pid: pid_t = 0
    let rc = argv.withUnsafeMutableBufferPointer { argvBuf in
        envp.withUnsafeMutableBufferPointer { envBuf in
            posix_spawn(&pid, exePath, nil, &attrs,
                        argvBuf.baseAddress, envBuf.baseAddress)
        }
    }
    if rc != 0 {
        let payload: [String: Any] = ["error": "disclaim spawn failed: errno \(rc)"]
        if let data = try? JSONSerialization.data(withJSONObject: payload) {
            FileHandle.standardError.write(data)
            FileHandle.standardError.write("\n".data(using: .utf8)!)
        }
        exit(1)
    }

    // Forward signals to the child so Ctrl+C / SIGTERM kills both.
    let forwarded: [Int32] = [SIGTERM, SIGINT, SIGHUP]
    for sig in forwarded {
        signal(sig) { s in
            // Best-effort: forward to whatever child we last spawned.
            // The child PID is captured via a global below.
            if g_disclaimChildPid > 0 {
                kill(g_disclaimChildPid, s)
            }
        }
    }
    g_disclaimChildPid = pid

    var status: Int32 = 0
    waitpid(pid, &status, 0)
    let exitCode: Int32
    if (status & 0x7f) == 0 {
        exitCode = (status >> 8) & 0xff
    } else {
        exitCode = 128 + (status & 0x7f)  // signaled
    }
    exit(exitCode)
}

private var g_disclaimChildPid: pid_t = 0

func runBLEScan() -> Never {
    if ProcessInfo.processInfo.environment[kDisclaimEnv] == nil {
        reExecWithDisclaimedResponsibility()
    }
    let scanner = BLEScanner()
    scanner.start()
    // Park until the parent closes the pipe (SIGPIPE) or sends SIGTERM.
    // dispatchMain() runs the main run loop forever so CoreBluetooth's
    // delegate callbacks fire.
    dispatchMain()
}

/// Lightweight Bluetooth-permission probe used by the Python launcher
/// to decide whether to prompt the user before starting the TUI. We
/// initialise CBCentralManager and wait for the first state change,
/// then exit with a code that maps directly to a permission outcome.
/// The 2 s timeout exists because TCC silently leaves
/// `central.state == .unknown` forever when permission was never asked
/// — a non-event we still need to translate into an exit code.
final class BluetoothStatusProbe: NSObject, CBCentralManagerDelegate {
    private var manager: CBCentralManager!

    func start() {
        manager = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            exit(0)
        case .unauthorized:
            exit(3)
        case .poweredOff:
            exit(4)
        case .unsupported:
            exit(5)
        case .resetting, .unknown:
            // Wait for the next state update or for the timeout.
            return
        @unknown default:
            exit(2)
        }
    }
}

func runBluetoothStatusProbe() -> Never {
    // Same disclaim hop as the live ble-scan path so TCC checks against
    // our own bundle's Info.plist instead of the launching terminal's.
    if ProcessInfo.processInfo.environment[kDisclaimEnv] == nil {
        reExecWithDisclaimedResponsibility()
    }
    let probe = BluetoothStatusProbe()
    probe.start()
    DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
        // No state update arrived in time. Could be silent TCC denial
        // or a transient OS hiccup; both are "not granted" from the
        // launcher's point of view.
        exit(2)
    }
    dispatchMain()
}

// ---------------------------------------------------------------------
// App mode (Finder launch / open)
// ---------------------------------------------------------------------

final class HelperAppDelegate: NSObject, NSApplicationDelegate, CLLocationManagerDelegate, CBCentralManagerDelegate {
    private var window: NSWindow!
    private var statusLabel: NSTextField!
    private let locationManager = CLLocationManager()
    private var bluetoothManager: CBCentralManager!
    private var locationGranted = false
    private var bluetoothGranted = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let frame = NSRect(x: 0, y: 0, width: 520, height: 280)
        window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "wifiscope helper"
        window.center()

        let body = NSStackView(frame: NSRect(x: 24, y: 24, width: 472, height: 232))
        body.orientation = .vertical
        body.alignment = .leading
        body.spacing = 12
        body.translatesAutoresizingMaskIntoConstraints = false

        let title = NSTextField(labelWithString: "wifiscope helper")
        title.font = NSFont.systemFont(ofSize: 18, weight: .semibold)
        body.addArrangedSubview(title)

        let intro = NSTextField(wrappingLabelWithString:
            "This helper exists so wifiscope (the Python TUI) can read " +
            "nearby Wi-Fi network names / BSSIDs and scan for nearby BLE " +
            "devices without being blocked by macOS Location Services or " +
            "Bluetooth permissions. Grant the prompts below — a one-time " +
            "action — and you can close this window."
        )
        intro.preferredMaxLayoutWidth = 472
        body.addArrangedSubview(intro)

        statusLabel = NSTextField(wrappingLabelWithString: "Requesting permissions...")
        statusLabel.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        statusLabel.preferredMaxLayoutWidth = 472
        body.addArrangedSubview(statusLabel)

        window.contentView?.addSubview(body)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        locationManager.delegate = self
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()

        // Initialising CBCentralManager from an .app bundle triggers
        // the macOS Bluetooth permission prompt the first time. After
        // grant, the same bundle's CLI subprocesses inherit the TCC
        // identity, so `ble-scan` works without re-asking.
        bluetoothManager = CBCentralManager(delegate: self, queue: nil)

        report()
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        DispatchQueue.main.async { self.report() }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        DispatchQueue.main.async { self.report() }
    }

    private func report() {
        let locStatus = locationManager.authorizationStatus
        let btState = bluetoothManager?.state ?? .unknown

        switch locStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            locationGranted = true
        default:
            locationGranted = false
        }

        switch btState {
        case .poweredOn:
            bluetoothGranted = true
        case .unauthorized, .poweredOff, .unsupported:
            bluetoothGranted = false
        default:
            // .unknown / .resetting — defer judgement
            break
        }

        var lines: [String] = []
        lines.append(locationLine(locStatus))
        lines.append(bluetoothLine(btState))
        statusLabel.stringValue = lines.joined(separator: "\n")

        if locationGranted && bluetoothGranted {
            statusLabel.stringValue += "\n\nAll permissions granted. This window will close automatically..."
            // Give the user ~1.5 s to read the message, then exit so
            // they do not have to find Cmd+Q. The TCC grants are
            // persistent — wifiscope's Python TUI immediately picks
            // them up the next time it polls the helper.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                NSApp.terminate(nil)
            }
        }
    }

    private func locationLine(_ status: CLAuthorizationStatus) -> String {
        switch status {
        case .notDetermined:
            return "Location: waiting for permission decision..."
        case .restricted:
            return "Location: restricted by a system policy."
        case .denied:
            return "Location: denied. Enable it in System Settings → Privacy & Security → Location Services → wifiscope-helper."
        case .authorizedAlways, .authorizedWhenInUse:
            return "Location: granted."
        @unknown default:
            return "Location: unknown state \(status.rawValue)."
        }
    }

    private func bluetoothLine(_ state: CBManagerState) -> String {
        switch state {
        case .unknown:
            return "Bluetooth: querying state..."
        case .resetting:
            return "Bluetooth: resetting..."
        case .unsupported:
            return "Bluetooth: unsupported on this hardware."
        case .unauthorized:
            return "Bluetooth: denied. Enable it in System Settings → Privacy & Security → Bluetooth → wifiscope-helper."
        case .poweredOff:
            return "Bluetooth: turned off. Toggle it on in Control Center."
        case .poweredOn:
            return "Bluetooth: granted."
        @unknown default:
            return "Bluetooth: unknown state \(state.rawValue)."
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

// ---------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------

let args = CommandLine.arguments

if args.count > 1 {
    switch args[1] {
    case "scan":
        runScanAndDumpJSON()
    case "ble-scan":
        runBLEScan()
    case "bluetooth-status":
        runBluetoothStatusProbe()
    case "--help", "-h":
        print("""
        wifiscope-helper

          (no args)         Launch the bundle UI; request Location Services
                            and Bluetooth, keep the window open so the
                            system prompts can show.
          scan              Perform a CoreWLAN scan and print one JSON
                            document to stdout, then exit. Used by the
                            Python backend as a subprocess.
          ble-scan          Scan nearby BLE advertisements via
                            CoreBluetooth and stream JSON Lines (one ad
                            per line) to stdout until SIGTERM / parent
                            pipe close. Used by the Python BLEPoller.
          bluetooth-status  Probe Bluetooth TCC state and exit non-zero
                            when not granted. No JSON output. Exit codes:
                            0 .poweredOn (granted), 2 timeout / unknown,
                            3 .unauthorized, 4 .poweredOff,
                            5 .unsupported.
        """)
        exit(0)
    default:
        FileHandle.standardError.write("unknown subcommand \(args[1])\n".data(using: .utf8)!)
        exit(64)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = HelperAppDelegate()
app.delegate = delegate
app.run()
