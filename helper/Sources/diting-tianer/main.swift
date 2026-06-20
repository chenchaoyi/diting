// diting-tianer — Swift sidecar that owns the macOS Location Services
// and Bluetooth permissions so the Python TUI can read unredacted scan-list
// SSIDs / BSSIDs and stream nearby BLE advertisements.
//
// Three roles in one binary:
//
//   diting-tianer           (no args, launched as a .app from Finder
//                               via `open` or by Launch Services)
//                              -> opens a small AppKit window, requests
//                                 Location Services AND Bluetooth
//                                 authorization, parks until the user
//                                 closes the window so the bundle stays
//                                 foregrounded long enough for the
//                                 system prompts.
//
//   diting-tianer scan      (invoked by the Python backend as a
//                               subprocess)
//                              -> performs a CoreWLAN scan, prints a
//                                 single JSON document {"networks": [...]}
//                                 to stdout, exits.
//
//   diting-tianer ble-scan  (invoked by the Python backend as a
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
import Security
import UserNotifications
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

/// Drives the location-authorization handshake and performs the
/// CoreWLAN scan inside the libdispatch main queue context. macOS 14.4+
/// (and tighter on 26) gates CWNetwork.ssid / .bssid behind being a
/// *registered* CoreLocation consumer, not just an *authorized* one.
/// Registration only completes after `locationd` calls back via the
/// main dispatch queue — meaning we need a running dispatch main loop
/// (not just a one-shot `Thread.sleep` or `RunLoop.run(mode:before:)`,
/// both of which leave libdispatch callbacks un-pumped on a short-lived
/// CLI subprocess).
///
/// Same pattern as `runBluetoothStatusProbe`: hand control to
/// `dispatchMain()`, do real work inside the delegate callback, exit
/// when done. Anything that needs to happen after registration
/// completes runs inside `performScanAndExit()`, which is invoked
/// either from `locationManagerDidChangeAuthorization` (the fast path
/// when TCC.db already has a grant) or from a 2-second fallback timer
/// (so a hard-denied or missing grant still produces an exit and not
/// a hang).
final class ScanWorker: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var done = false

    func start() {
        manager.delegate = self
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
        // Don't wait a fixed time — try the scan immediately, and if
        // it comes back redacted (CoreLocation registration not yet
        // complete), retry after 500 ms. Up to 6 attempts ≈ 5 s
        // worst-case. dispatchMain keeps the libdispatch + CoreLocation
        // machinery alive across retries, so registration eventually
        // lands; we use the *first* unredacted scan we get as the
        // result. Warm state returns on attempt 0 in ~0.2 s; cold
        // state typically takes 3-4 attempts (~2 s wall-clock).
        attemptScan(attempt: 0)
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        // Cut the retry loop short on explicit denial / restriction —
        // the scan will return redacted no matter how many times we
        // ask, so don't make the user wait the full 6 s.
        switch manager.authorizationStatus {
        case .denied, .restricted:
            emitCurrentScan(force: true)
        default:
            break
        }
    }

    // Pre-Catalina spelling — macOS picks one of the two delegate
    // entry points based on SDK target.
    func locationManager(_ manager: CLLocationManager,
                         didChangeAuthorization status: CLAuthorizationStatus) {
        switch status {
        case .denied, .restricted:
            emitCurrentScan(force: true)
        default:
            break
        }
    }

    private func attemptScan(attempt: Int) {
        guard !done else { return }
        if attempt >= 6 {
            // Out of retries; emit whatever the last scan returned
            // even if redacted. Caller can then surface a "permission
            // missing" hint rather than hanging forever.
            emitCurrentScan(force: true)
            return
        }

        let client = CWWiFiClient.shared()
        guard let iface = client.interface() else {
            done = true
            emitError("no Wi-Fi interface")
        }
        let networks: Set<CWNetwork>
        do {
            networks = try iface.scanForNetworks(withName: nil)
        } catch {
            done = true
            emitError("scan failed: \(error.localizedDescription)")
        }
        latestScan = networks
        latestIface = iface
        // Count rows with bssid populated. Any non-zero count means
        // CoreLocation registration completed and CoreWLAN unredacted
        // — we can ship this result immediately. Zero unredacted rows
        // with a non-empty scan means we got the scan but Location is
        // still gated; retry after a short delay to let registration
        // catch up.
        let unredactedCount = networks.filter { $0.bssid != nil }.count
        if unredactedCount > 0 || networks.isEmpty {
            // Empty networks also short-circuits — there's nothing to
            // unredact anyway (e.g. radio off), and retrying won't
            // change that.
            emitCurrentScan(force: false)
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.attemptScan(attempt: attempt + 1)
        }
    }

    private var latestScan: Set<CWNetwork> = []
    private var latestIface: CWInterface?

    private func emitCurrentScan(force: Bool) {
        guard !done else { return }
        done = true

        // If the early-exit (denied / restricted) path got here
        // before any scan ran, do one last scan attempt so the
        // caller still gets a structured response (with redacted
        // rows). Saves a special-case error code at the caller.
        if latestIface == nil {
            let client = CWWiFiClient.shared()
            guard let iface = client.interface() else {
                emitError("no Wi-Fi interface")
            }
            do {
                latestScan = try iface.scanForNetworks(withName: nil)
            } catch {
                emitError("scan failed: \(error.localizedDescription)")
            }
            latestIface = iface
        }
        _ = force  // suppressed-unused for future plumbing

        guard let iface = latestIface else {
            emitError("no Wi-Fi interface")
        }

        let timestamp = ISO8601DateFormatter().string(from: Date())
        var out: [[String: Any]] = []
        for net in latestScan {
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
            "schema": 3,
            "interface": ifaceMeta,
            "timestamp": timestamp,
            "networks": out,
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            // When invoked via the LaunchServices outer/inner split,
            // the inner writes its JSON to a temp file that the outer
            // then relays to stdout. Otherwise (legacy direct stdout
            // path, kept for the disclaim-still-works case) write
            // directly to stdout.
            if let outPath = ProcessInfo.processInfo.environment["DITING_SCAN_OUT"] {
                let url = URL(fileURLWithPath: outPath)
                try data.write(to: url, options: .atomic)
                exit(0)
            }
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write("\n".data(using: .utf8)!)
            exit(0)
        } catch {
            emitError("json encode failed: \(error.localizedDescription)")
        }
    }
}

// Global reference: dispatchMain() never returns, but we need the
// worker (and its CLLocationManager) to outlive the call site. A
// global keeps it pinned for the lifetime of the process.
private var g_scanWorker: ScanWorker?

func runScanAndDumpJSON() -> Never {
    // macOS 14.4+ (and tighter on 26) gates CWNetwork.ssid / .bssid
    // behind Location Services at the calling process level. Three
    // things have to be true at scanForNetworks time:
    //
    //   1. The TCC subject seen by macOS is the helper bundle (not
    //      the terminal that launched us). Inherited responsibility
    //      from Terminal → diting → diting-tianer breaks this on
    //      macOS 26 — tccd attributes the request to Terminal,
    //      which has no NSLocationUsageDescription, and CWNetwork
    //      redacts ssid / bssid silently. Fix: disclaim our parent
    //      so we become our own responsible process. Same hop the
    //      ble-scan subcommand has done since v0.5.0.
    //
    //   2. The process is a *registered* CoreLocation consumer at
    //      the moment scanForNetworks runs — meaning a
    //      CLLocationManager exists AND its delegate has received
    //      `didChangeAuthorization` from locationd. The earlier
    //      v1.0.3 / v1.0.6 attempts used `Thread.sleep` then
    //      `RunLoop.run(mode:before:)` — neither reliably pumps the
    //      libdispatch main queue the delegate callback rides on
    //      inside a short-lived CLI subprocess. The fix is to drive
    //      everything from inside `dispatchMain()` — same pattern
    //      as the bluetooth-status probe — so libdispatch's main
    //      queue is fully active during the auth handshake AND the
    //      scan call.
    //
    //   3. The CLLocationManager reference stays alive across the
    //      scanForNetworks call. The global g_scanWorker pins it
    //      for the lifetime of the process.
    //
    // The earlier code comment claiming CoreLocation was "more
    // lenient" than CoreBluetooth was wrong; CoreWLAN on macOS 26
    // enforces all three. v1.0.6 implemented (1) and partially (2)
    // but the run-loop pump it used didn't actually drive the
    // libdispatch handshake — scans only appeared to work when a
    // GUI bundle had recently run and warmed the system caches.
    // This v1.0.7 implementation uses dispatchMain() so registration
    // completes reliably from cold.
    // Two code paths share this function:
    //
    //   A. CLI subprocess from Python (no DITING_SCAN_VIA_LAUNCH env):
    //      Re-launch ourselves via `open` so the new instance is
    //      bona fide LaunchServices-attributed, then read its result
    //      file. On macOS 26 this is the only way to get a CLI scan
    //      that sees the bundle's Location grant — direct-exec
    //      binaries (even when in the bundle's Contents/MacOS/) are
    //      not attributed to the bundle and CLLocationManager.
    //      authorizationStatus stays at .notDetermined no matter
    //      what NSApp / dispatchMain / disclaim trick we try.
    //      Empirically verified 2026-05-13.
    //
    //   B. LaunchServices-launched child (DITING_SCAN_VIA_LAUNCH=1):
    //      Run the actual scan inside an NSApp context where TCC
    //      attribution works, write JSON to the path in
    //      DITING_SCAN_OUT, exit.
    if ProcessInfo.processInfo.environment["DITING_SCAN_VIA_LAUNCH"] == "1" {
        runScanViaLaunchInner()
    }
    runScanViaLaunchOuter()
}

/// Outer half: spawns the bundle via `open` so the inner half runs
/// LaunchServices-attributed. Reads the inner's JSON output back from
/// a temp file, writes it to our own stdout, exits. Python sees this
/// process as the one it subprocess'd — no protocol change required.
private func runScanViaLaunchOuter() -> Never {
    let outPath = NSTemporaryDirectory() + "diting-scan-\(UUID().uuidString).json"
    let bundlePath = Bundle.main.bundlePath

    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    task.arguments = [
        "-W",                                  // wait for app to exit
        "-g",                                  // do not bring to front
        "-a", bundlePath,                      // target bundle
        "--env", "DITING_SCAN_VIA_LAUNCH=1",
        "--env", "DITING_SCAN_OUT=\(outPath)",
        "--args", "scan",                      // pass through scan arg
    ]
    do {
        try task.run()
    } catch {
        emitError("scan-via-launch spawn failed: \(error.localizedDescription)")
    }
    task.waitUntilExit()

    guard let data = try? Data(contentsOf: URL(fileURLWithPath: outPath)) else {
        emitError("scan-via-launch produced no output at \(outPath)")
    }
    FileHandle.standardOutput.write(data)
    if data.last != UInt8(ascii: "\n") {
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
    try? FileManager.default.removeItem(atPath: outPath)
    exit(task.terminationStatus)
}

/// Inner half: runs as a LaunchServices-launched bundle instance.
/// Initialises an NSApp + CLLocationManager + the scan-with-retry
/// worker, writes JSON to DITING_SCAN_OUT, exits.
private func runScanViaLaunchInner() -> Never {
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)

    let worker = ScanWorker()
    g_scanWorker = worker
    worker.start()
    app.run()
    exit(0)  // unreachable; worker exits the process via exit(0)
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
/// fallback in `diting/ble.py` byte-for-byte; both implementations
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
                    // Apple Find My target. AirTag and AirPods Pro both
                    // broadcast type 0x12 with length >= 25 when away
                    // from their owner, so the length-only heuristic
                    // mis-labels AirPods as AirTag. Real AirTags never
                    // carry a localName (privacy by design); AirPods /
                    // Watches do. So presence of any localName forces
                    // the more general "Find My target" label.
                    let hasName: Bool
                    if let s = advertisementData[CBAdvertisementDataLocalNameKey] as? String,
                       !s.isEmpty {
                        hasName = true
                    } else {
                        hasName = false
                    }
                    let isAirTag = bytes.count >= 25 && !hasName
                    return BLEDetection(
                        type: isAirTag ? "AirTag" : "Find My target",
                        deviceClass: nil
                    )
                default:
                    if let label = appleContinuityType(typeByte) {
                        return BLEDetection(type: label, deviceClass: nil)
                    }
                }
            }
            if cid == companyMicrosoftID, bytes.count >= 3 {
                // 0x01 = general device-discovery beacon (Phone Link /
                // Nearby Sharing), 0x03 = Swift Pair. Both are
                // documented public formats. Mirror the Python-side
                // _MS_CDP_TYPE table byte-for-byte.
                switch bytes[2] {
                case 0x01: return BLEDetection(type: "MS device beacon", deviceClass: nil)
                case 0x03: return BLEDetection(type: "Swift Pair", deviceClass: nil)
                default: break
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
        // 0x16 — accessory proximity broadcast, observed at high
        // density in real Mac scans. Generic label; the encrypted
        // tail is opaque so we don't claim more.
        case 0x16: return "Apple Proximity"
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

        // Schema-4 fields (helper v0.8.0+). Optional and additive — Python
        // tolerates absence. Surfacing more of CoreBluetooth's
        // advertisementData dict makes the rows usable as raw input for
        // downstream sensor / beacon decoders (Eddystone-URL, Xiaomi
        // MiBeacon, Govee, SwitchBot, RuuviTag) that put their payload in
        // service-data rather than manufacturer-data.

        // Service-data: {uuid_string: hex_bytes}. The CBUUID may be
        // 16-bit (Eddystone "FEAA") or 128-bit (vendor-private). Encode
        // the bytes as hex to match manufacturer_hex's format.
        if let svcData = advertisementData[CBAdvertisementDataServiceDataKey] as? [CBUUID: Data],
           !svcData.isEmpty {
            var out: [String: String] = [:]
            for (uuid, data) in svcData {
                out[uuid.uuidString] = data.map { String(format: "%02x", $0) }.joined()
            }
            row["service_data"] = out
        }

        // Tx-power-level: included by iBeacon / Eddystone-TLM and a few
        // other beacons. Consumers can use it for rough distance
        // estimation (RSSI − tx_power), or surface it as-is.
        if let txPower = advertisementData[CBAdvertisementDataTxPowerLevelKey] as? NSNumber {
            row["tx_power_dbm"] = txPower.intValue
        }

        // Solicited service UUIDs: services the peripheral wants to be
        // connected for, even when not actively advertising them. HID
        // peer-discovery and Find My peer-discovery surface here.
        if let solicited = advertisementData[CBAdvertisementDataSolicitedServiceUUIDsKey] as? [CBUUID],
           !solicited.isEmpty {
            row["solicited_service_uuids"] = solicited.map { $0.uuidString }
        }

        // Overflow service UUIDs: BLE adv frames are 31 bytes; iOS
        // spills over-budget UUIDs into a backup list. Apple Continuity
        // secondary advertisements land here.
        if let overflow = advertisementData[CBAdvertisementDataOverflowServiceUUIDsKey] as? [CBUUID],
           !overflow.isEmpty {
            row["overflow_service_uuids"] = overflow.map { $0.uuidString }
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
// Warp, iTerm2, Terminal). When diting's Python TUI invokes us as
// `<bundle>/Contents/MacOS/diting-tianer ble-scan` from inside such
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

private let kDisclaimEnv = "DITING_HELPER_DISCLAIMED"

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
// `notification-status` subcommand
//
// Exit-code-only probe of the bundle's Notifications TCC authorization,
// mirroring `bluetooth-status`. Lets the Python side VERIFY the
// Notifications grant (not just request it) so `diting setup` can report
// a trustworthy state. `getNotificationSettings` is a read — it never
// prompts. We take the same disclaim hop as the other probes so the
// authorization is attributed to OUR bundle, not the launching terminal.
//
//   exit 0  .authorized / .provisional  (granted)
//   exit 3  .denied
//   exit 4  .notDetermined
//   exit 2  timeout / unknown
func runNotificationStatusProbe() -> Never {
    if ProcessInfo.processInfo.environment[kDisclaimEnv] == nil {
        reExecWithDisclaimedResponsibility()
    }
    // Read-only query; prohibit any Dock-icon flash just like `notify`.
    NSApplication.shared.setActivationPolicy(.prohibited)
    let center = UNUserNotificationCenter.current()
    center.getNotificationSettings { settings in
        switch settings.authorizationStatus {
        case .authorized, .provisional:
            exit(0)
        case .denied:
            exit(3)
        case .notDetermined:
            exit(4)
        @unknown default:
            exit(2)
        }
    }
    // No callback in time → treat as not granted from the caller's POV.
    DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
        exit(2)
    }
    dispatchMain()
}

// ---------------------------------------------------------------------
// `notify` subcommand
//
// Posts a single UserNotification under the bundle's identity so the
// notification carries the helper's app icon (the diting logo) instead
// of /usr/bin/osascript's AppleScript scroll. The Python TUI's anomaly
// watchdog (_watchdog.py) shells out to this rather than emitting via
// osascript.
//
// Same outer / inner LaunchServices split as `scan`. The reason is the
// same macOS 26 TCC asymmetry: direct-exec subprocesses of an ad-hoc-
// signed bundle's binary do NOT inherit the bundle's TCC grants. For
// Notifications that means `requestAuthorization` reports `granted=false`
// even when the user clicked Allow during the install-time HelperAppDelegate
// flow. The fix mirrors `runScanAndDumpJSON`:
//
//   A. Outer (no DITING_NOTIFY_VIA_LAUNCH env): spawn ourselves via
//      `/usr/bin/open -W -g -a <bundle>` so the inner instance is
//      LaunchServices-attributed and sees the bundle's Notifications
//      grant. Title + body travel via env vars (newline / quote safe).
//   B. Inner (DITING_NOTIFY_VIA_LAUNCH=1): set activation policy to
//      `.prohibited` (defence-in-depth alongside LSUIElement=true so
//      nothing can ever flash even on older macOS), call
//      UNUserNotificationCenter, exit.
//
// We wait briefly before exit() in the inner half so the notification
// request actually makes it through the system daemon — a process
// that exits too fast can lose the message. 1 s is enough in practice.
// ---------------------------------------------------------------------

func runNotifyAndExit(args: [String]) -> Never {
    if ProcessInfo.processInfo.environment["DITING_NOTIFY_VIA_LAUNCH"] == "1" {
        runNotifyViaLaunchInner()
    }
    runNotifyViaLaunchOuter(args: args)
}

/// Parse `--title T --body B` out of an arg list. Used by the outer
/// half to thread the values through env vars to the inner half.
private func parseNotifyArgs(_ args: [String]) -> (title: String, body: String) {
    var title = ""
    var body = ""
    var i = 0
    while i < args.count {
        let arg = args[i]
        if arg == "--title" && i + 1 < args.count {
            title = args[i + 1]
            i += 2
        } else if arg == "--body" && i + 1 < args.count {
            body = args[i + 1]
            i += 2
        } else {
            i += 1
        }
    }
    return (title, body)
}

/// Outer half: spawn the bundle via `open` so the inner half runs
/// LaunchServices-attributed (and thus sees the bundle's Notifications
/// authorization). Returns the inner's exit code.
private func runNotifyViaLaunchOuter(args: [String]) -> Never {
    let (title, body) = parseNotifyArgs(args)
    if title.isEmpty && body.isEmpty {
        FileHandle.standardError.write(
            "notify: --title and/or --body required\n".data(using: .utf8)!
        )
        exit(64)
    }

    let bundlePath = Bundle.main.bundlePath
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    task.arguments = [
        "-W",                                       // wait for app to exit
        "-g",                                       // do not bring to front
        "-a", bundlePath,                           // target bundle
        "--env", "DITING_NOTIFY_VIA_LAUNCH=1",
        "--env", "DITING_NOTIFY_TITLE=\(title)",
        "--env", "DITING_NOTIFY_BODY=\(body)",
        "--args", "notify",
    ]
    do {
        try task.run()
    } catch {
        // Spawn failed — silent exit because the watchdog treats
        // notifications as best-effort. We pick a non-zero code so
        // Python's `proc.wait()` can surface it to logs if needed.
        exit(70)
    }
    task.waitUntilExit()
    exit(task.terminationStatus)
}

/// Inner half: runs as a LaunchServices-launched bundle instance with
/// the bundle's Notifications grant. Posts the notification via
/// UNUserNotificationCenter and exits.
private func runNotifyViaLaunchInner() -> Never {
    let env = ProcessInfo.processInfo.environment
    let title = env["DITING_NOTIFY_TITLE"] ?? ""
    let body = env["DITING_NOTIFY_BODY"] ?? ""

    // Defence in depth: even with LSUIElement=true, set the activation
    // policy explicitly so any future regression in the Info.plist
    // doesn't suddenly make notifications flash a Dock icon.
    NSApplication.shared.setActivationPolicy(.prohibited)

    let center = UNUserNotificationCenter.current()
    let group = DispatchGroup()

    group.enter()
    center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
        guard granted else {
            group.leave()
            return
        }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )
        center.add(request) { _ in group.leave() }
    }

    // Best-effort: cap the wait so a stuck notification daemon does
    // not block the calling TUI's watchdog longer than necessary.
    _ = group.wait(timeout: .now() + 1.0)
    exit(0)
}

// ---------------------------------------------------------------------
// `associate` subcommand
//
// Drives a CoreWLAN association to a user-selected SSID, called by
// the Python TUI's WifiDetailScreen `j` binding. Same outer / inner
// LaunchServices split as `scan` and `notify`: CoreWLAN association
// to a CWNetwork needs the bundle's Location TCC grant, which a
// directly-exec'd subprocess cannot inherit on macOS 26.
//
//   Outer (no DITING_ASSOC_VIA_LAUNCH env): parses argv, rejects
//   `--password` (the password protocol is stdin-only — a `ps` view
//   must never see secrets). Drains stdin into a 0600 temp file if
//   non-empty so a piped password reaches the inner without
//   crossing argv or env. Spawns the inner via `open`, waits, copies
//   the result JSON written to DITING_ASSOC_OUT onto our own stdout,
//   exits with the inner's status.
//
//   Inner (DITING_ASSOC_VIA_LAUNCH=1): activation-policy `.accessory`
//   (no dock icon flash); runs an AssociateWorker on the
//   dispatchMain queue that registers CoreLocation, performs a
//   CoreWLAN scan to locate the SSID, refuses Enterprise / 802.1X
//   with code `enterprise_unsupported`, calls
//   `CWInterface.associate(toNetwork:password:nil error:)` for the
//   open-or-Keychain fast path, and falls back to an NSAlert with
//   an NSSecureTextField + Remember-this-network checkbox when the
//   nil-password attempt fails on a secured network. Writes a JSON
//   status to DITING_ASSOC_OUT, exits.
//
// Exit codes:
//   0 ok
//   2 unexpected (no Wi-Fi interface, JSON encode failure, spawn fail)
//   5 enterprise_unsupported
//   6 user cancelled the AppKit sheet
//   7 auth_failed (CWInterface.associate threw)
//   8 ssid_not_found (SSID absent from a fresh scan)
//   64 bad args (--password on argv, missing --ssid)
//
// We deliberately do NOT call `iface.disassociate()` first.
// `CWInterface.associate(toNetwork:password:error:)` drives the L2
// transition itself, which is the minimum-window path. Per the
// design's D7 ("Lossless / hitless cross-SSID switching is
// explicitly not a goal"), the user has already consented in the
// TUI's JoinConfirmScreen to the 2-5 s gap.
// ---------------------------------------------------------------------

private enum AssociateEnv {
    static let viaLaunch = "DITING_ASSOC_VIA_LAUNCH"
    static let ssid      = "DITING_ASSOC_SSID"
    static let bssid     = "DITING_ASSOC_BSSID"
    static let pwFile    = "DITING_ASSOC_PW_FILE"
    static let outFile   = "DITING_ASSOC_OUT"
}

func runAssociateAndExit(args: [String]) -> Never {
    if ProcessInfo.processInfo.environment[AssociateEnv.viaLaunch] == "1" {
        runAssociateInner()
    }
    runAssociateOuter(args: args)
}

private func runAssociateOuter(args: [String]) -> Never {
    var ssid: String?
    var bssid: String?
    var i = 0
    while i < args.count {
        let a = args[i]
        if a == "--ssid" && i + 1 < args.count {
            ssid = args[i + 1]; i += 2
        } else if a == "--bssid" && i + 1 < args.count {
            bssid = args[i + 1]; i += 2
        } else if a == "--password" || a.hasPrefix("--password=") {
            emitAssociateOuterError(
                message: "--password is not accepted; pipe the password via stdin",
                code: "bad_args",
                exitCode: 64
            )
        } else {
            i += 1
        }
    }
    guard let targetSSID = ssid, !targetSSID.isEmpty else {
        emitAssociateOuterError(
            message: "--ssid <SSID> required",
            code: "bad_args",
            exitCode: 64
        )
    }

    // Drain stdin. Strip a single trailing newline so `echo "$pw"`
    // and `printf %s "$pw"` both work cleanly. Non-empty stdin
    // becomes a 0600 temp file the inner reads and immediately
    // deletes; argv and env are visible to `ps eww` and must not
    // carry secrets.
    var stdinData = FileHandle.standardInput.readDataToEndOfFile()
    if !stdinData.isEmpty, stdinData.last == 0x0a {
        stdinData.removeLast()
    }
    var pwFile: String? = nil
    if !stdinData.isEmpty {
        let path = NSTemporaryDirectory() + "diting-assoc-pw-\(UUID().uuidString)"
        let ok = FileManager.default.createFile(
            atPath: path,
            contents: stdinData,
            attributes: [.posixPermissions: NSNumber(value: 0o600)]
        )
        if ok { pwFile = path }
    }
    stdinData.resetBytes(in: 0..<stdinData.count)

    let outPath = NSTemporaryDirectory() + "diting-assoc-out-\(UUID().uuidString).json"
    let bundlePath = Bundle.main.bundlePath
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    var taskArgs: [String] = [
        "-W",                                  // wait for app to exit
        "-g",                                  // do not bring to front
                                               // (LSUIElement=true means
                                               // the bundle has no Dock
                                               // presence; without -g,
                                               // `open` tries to fg an
                                               // app it can't fg and
                                               // returns early without
                                               // propagating --env /
                                               // --args. The sheet path
                                               // calls
                                               // NSApp.activate(...) on
                                               // its own when needed.)
        "-n",                                  // force a new instance —
                                               // if a stale bundle copy
                                               // is already running it
                                               // would otherwise absorb
                                               // the --args / --env and
                                               // our inner would never
                                               // run.
        "-a", bundlePath,                      // target bundle
        "--env", "\(AssociateEnv.viaLaunch)=1",
        "--env", "\(AssociateEnv.ssid)=\(targetSSID)",
        "--env", "\(AssociateEnv.outFile)=\(outPath)",
    ]
    if let b = bssid {
        taskArgs += ["--env", "\(AssociateEnv.bssid)=\(b)"]
    }
    if let pwf = pwFile {
        taskArgs += ["--env", "\(AssociateEnv.pwFile)=\(pwf)"]
    }
    taskArgs += ["--args", "associate"]
    task.arguments = taskArgs
    do {
        try task.run()
    } catch {
        if let pwf = pwFile { try? FileManager.default.removeItem(atPath: pwf) }
        emitAssociateOuterError(
            message: "associate-via-launch spawn failed: \(error.localizedDescription)",
            code: "unknown",
            exitCode: 2
        )
    }
    task.waitUntilExit()
    if let pwf = pwFile { try? FileManager.default.removeItem(atPath: pwf) }

    if let data = try? Data(contentsOf: URL(fileURLWithPath: outPath)) {
        FileHandle.standardOutput.write(data)
        if data.last != UInt8(ascii: "\n") {
            FileHandle.standardOutput.write("\n".data(using: .utf8)!)
        }
        try? FileManager.default.removeItem(atPath: outPath)
    } else {
        // Inner produced no JSON; never leave the caller with blank
        // stdout — they parse JSON unconditionally. Carry the
        // `open` termination status so the user / log can tell
        // "launchctl rejected the bundle" (non-zero) from "the
        // inner ran but skipped the write path" (zero).
        let status = task.terminationStatus
        let payload = associateJSONError(
            message: "inner produced no output (open exit=\(status))",
            code: "unknown"
        )
        FileHandle.standardOutput.write(payload)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
    exit(task.terminationStatus)
}

private func runAssociateInner() -> Never {
    let env = ProcessInfo.processInfo.environment
    guard let ssid = env[AssociateEnv.ssid], !ssid.isEmpty else {
        emitAssociateInnerError(
            message: "missing SSID env",
            code: "unknown",
            exitCode: 2
        )
    }
    let bssidHint = env[AssociateEnv.bssid]

    // Read the piped password if the outer dropped one for us.
    var pipedPassword: String? = nil
    if let pwPath = env[AssociateEnv.pwFile] {
        if var data = try? Data(contentsOf: URL(fileURLWithPath: pwPath)) {
            pipedPassword = String(data: data, encoding: .utf8)
            data.resetBytes(in: 0..<data.count)
        }
        // Defence-in-depth: the outer also tries to remove the file.
        try? FileManager.default.removeItem(atPath: pwPath)
    }

    // `.accessory` so the helper doesn't flash a dock icon when the
    // AppKit sheet path fires. NSAlert.runModal() still brings its
    // window to the front when we `activate(ignoringOtherApps: true)`.
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)

    let worker = AssociateWorker(
        ssid: ssid,
        bssidHint: bssidHint,
        pipedPassword: pipedPassword
    )
    g_associateWorker = worker
    worker.start()
    app.run()
    exit(0)  // unreachable — worker exits via emitAssociateInnerExit
}

private var g_associateWorker: AssociateWorker?

private final class AssociateWorker: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let ssid: String
    private let bssidHint: String?
    private var password: String?
    private var done = false

    init(ssid: String, bssidHint: String?, pipedPassword: String?) {
        self.ssid = ssid
        self.bssidHint = bssidHint
        self.password = pipedPassword
    }

    func start() {
        manager.delegate = self
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()

        // Already-on-this-SSID short-circuit. The user can press `j`
        // on the row of the network they're currently associated to
        // (per the spec scenario "User opens detail on the currently-
        // associated SSID and presses j"); we don't need to scan +
        // re-associate — that would tear the link down for no gain.
        // CWInterface.ssid() is TCC-redacted to nil in unprivileged
        // processes, but inside the LaunchServices-attributed bundle
        // it's populated, so this check fires reliably.
        let client = CWWiFiClient.shared()
        if let iface = client.interface(),
           let live = iface.ssid(),
           live == ssid {
            done = true
            emitAssociateInnerExit(
                payload: associateJSONOK(
                    bssid: iface.bssid(),
                    keychainSaved: false
                ),
                exitCode: 0
            )
        }

        attemptResolve(attempt: 0)
    }

    func locationManager(
        _ manager: CLLocationManager,
        didChangeAuthorization status: CLAuthorizationStatus
    ) { /* no-op; the scan retry loop drives forward progress */ }

    private func attemptResolve(attempt: Int) {
        guard !done else { return }
        // 12 attempts × ~0.5 s + scan call time (~0.1 s cached,
        // ~3 s fresh). Total budget ~6-20 s — wide enough for a
        // cold helper-bundle launch to complete the CoreLocation
        // registration handshake before we give up. The previous
        // budget (6 attempts) timed out on a freshly-spawned
        // bundle with the user clearly seeing the SSID in the TUI.
        if attempt >= 12 {
            done = true
            emitAssociateInnerExit(
                payload: associateJSONError(
                    message: "SSID \(ssid) not in scan range "
                        + "(\(attempt) attempts, no match)",
                    code: "ssid_not_found"
                ),
                exitCode: 8
            )
        }
        let client = CWWiFiClient.shared()
        guard let iface = client.interface() else {
            done = true
            emitAssociateInnerExit(
                payload: associateJSONError(
                    message: "no Wi-Fi interface",
                    code: "unknown"
                ),
                exitCode: 2
            )
        }
        let networks: Set<CWNetwork>
        do {
            networks = try iface.scanForNetworks(withName: nil)
        } catch {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                self?.attemptResolve(attempt: attempt + 1)
            }
            return
        }
        var match: CWNetwork? = nil
        for net in networks where net.ssid == ssid {
            if let hint = bssidHint?.lowercased(),
               let nb = net.bssid?.lowercased(),
               nb == hint {
                match = net
                break
            }
            if match == nil { match = net }
        }
        guard let target = match else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                self?.attemptResolve(attempt: attempt + 1)
            }
            return
        }
        proceed(net: target, iface: iface)
    }

    private func proceed(net: CWNetwork, iface: CWInterface) {
        done = true
        if isEnterpriseOnly(net) {
            emitAssociateInnerExit(
                payload: associateJSONError(
                    message: associateEnterpriseHint(),
                    code: "enterprise_unsupported"
                ),
                exitCode: 5
            )
        }
        // Caller-supplied password path — skip the sheet, the caller
        // told us exactly what to use.
        if let pw = password, !pw.isEmpty {
            do {
                try iface.associate(to: net, password: pw)
                password = nil
                emitAssociateInnerExit(
                    payload: associateJSONOK(bssid: net.bssid, keychainSaved: false),
                    exitCode: 0
                )
            } catch {
                password = nil
                emitAssociateInnerExit(
                    payload: associateJSONError(
                        message: error.localizedDescription,
                        code: "auth_failed"
                    ),
                    exitCode: 7
                )
            }
        }
        // Open network: no Keychain involvement, password is nil.
        if net.supportsSecurity(.none) {
            do {
                try iface.associate(to: net, password: nil)
                emitAssociateInnerExit(
                    payload: associateJSONOK(
                        bssid: net.bssid,
                        keychainSaved: false,
                        keychainRead: "skipped-open"
                    ),
                    exitCode: 0
                )
            } catch {
                emitAssociateInnerExit(
                    payload: associateJSONError(
                        message: error.localizedDescription,
                        code: "auth_failed"
                    ),
                    exitCode: 7
                )
            }
            return
        }
        // Secured network: explicit cached-credential lookup, then
        // sheet on miss. We do NOT try `associate(...password: nil)`
        // here — CoreWLAN's raw primitive doesn't read from Keychain
        // on its own (only WiFiAgent does, and we are not it), so
        // that call would just spin for 3-5 s before throwing.
        let read = attemptKeychainRead(ssid: ssid)
        let keychainReadVariant = read.variant
        if let saved = read.password {
            do {
                try iface.associate(to: net, password: saved)
                emitAssociateInnerExit(
                    payload: associateJSONOK(
                        bssid: net.bssid,
                        keychainSaved: false,
                        keychainRead: keychainReadVariant
                    ),
                    exitCode: 0
                )
            } catch {
                // Stale cached password (AP key rotation, mismatched
                // BSSID, etc). Fall through to the sheet — on
                // resubmit, attemptKeychainWrite hits errSecDuplicateItem
                // and SecItemUpdate rewrites the data in place,
                // preserving the existing .userPresence ACL. The read
                // succeeded (variant == "diting") so we surface that
                // on the eventual emit — debug signal that this was a
                // stale-cache recovery, not a first-time-join.
                DispatchQueue.main.async { [weak self] in
                    self?.showPasswordSheet(
                        net: net,
                        iface: iface,
                        keychainReadVariant: keychainReadVariant
                    )
                }
                return
            }
        }
        // Miss / denied / err — go straight to the sheet. variant
        // is plumbed onto the response if/when the sheet path emits.
        DispatchQueue.main.async { [weak self] in
            self?.showPasswordSheet(
                net: net,
                iface: iface,
                keychainReadVariant: keychainReadVariant
            )
        }
    }

    private func showPasswordSheet(
        net: CWNetwork,
        iface: CWInterface,
        keychainReadVariant: String = "miss"
    ) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = associatePromptTitle(ssid: ssid)
        alert.informativeText = associatePromptBody()

        let pwField = NSSecureTextField(frame: NSRect(x: 0, y: 30, width: 260, height: 24))
        let rememberBtn = NSButton(
            checkboxWithTitle: associateRememberLabel(),
            target: nil,
            action: nil
        )
        rememberBtn.state = .on
        rememberBtn.frame = NSRect(x: 0, y: 0, width: 260, height: 22)
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 260, height: 60))
        container.addSubview(pwField)
        container.addSubview(rememberBtn)
        alert.accessoryView = container

        alert.addButton(withTitle: associateJoinLabel())
        let cancelButton = alert.addButton(withTitle: associateCancelLabel())
        cancelButton.keyEquivalent = "\u{1b}"  // Esc

        alert.window.initialFirstResponder = pwField

        let resp = alert.runModal()
        if resp == .alertFirstButtonReturn {
            let typed = pwField.stringValue
            let rememberOn = (rememberBtn.state == .on)
            do {
                try iface.associate(to: net, password: typed)
                let saved = rememberOn
                    ? attemptKeychainWrite(ssid: ssid, password: typed)
                    : false
                pwField.stringValue = ""
                emitAssociateInnerExit(
                    payload: associateJSONOK(
                        bssid: net.bssid,
                        keychainSaved: saved,
                        keychainRead: keychainReadVariant
                    ),
                    exitCode: 0
                )
            } catch {
                pwField.stringValue = ""
                emitAssociateInnerExit(
                    payload: associateJSONError(
                        message: error.localizedDescription,
                        code: "auth_failed"
                    ),
                    exitCode: 7
                )
            }
        } else {
            emitAssociateInnerExit(
                payload: associateJSONError(
                    message: "user cancelled",
                    code: "cancelled"
                ),
                exitCode: 6
            )
        }
    }
}

private func isEnterpriseOnly(_ net: CWNetwork) -> Bool {
    let enterprise: [CWSecurity] = [.wpaEnterprise, .wpa2Enterprise, .wpa3Enterprise]
    let personal: [CWSecurity] = [.none, .WEP, .wpaPersonal, .wpa2Personal, .wpa3Personal]
    let supportsEnt = enterprise.contains(where: { net.supportsSecurity($0) })
    if !supportsEnt { return false }
    return !personal.contains(where: { net.supportsSecurity($0) })
}

/// Read a saved Wi-Fi password from the user's login keychain
/// via `Security.framework`'s `SecItemCopyMatching`. The entry
/// lives under our own service namespace
/// (`com.chenchaoyi.diting.tianer`) — we deliberately do NOT probe
/// macOS's own `AirPort/<SSID>` items in the System keychain.
/// That path is gated by Authorization Services rule
/// `authenticate-admin-nonshared`, which forces a fresh admin
/// password every read and does not accept biometric substitution
/// (confirmed via macOS Sequoia behaviour observed in PR #75).
///
/// Items we write here carry a `.userPresence` access-control flag
/// (see `attemptKeychainWrite`). macOS resolves that at read time
/// against the user's configured authentication path: Touch ID on
/// capable Macs, Apple Watch unlock if paired, otherwise the login
/// password (NOT admin password — different Authorization right).
///
/// Returns `(password, variant)`:
///   - `variant == "diting"` — cached read succeeded, password is non-nil
///   - `variant == "miss"`   — no entry for this SSID
///   - `variant == "denied"` — user dismissed the Touch ID / login-pw dialog
///   - `variant == "err:N"`  — any other OSStatus, surfaced for debug
///
/// The caller (the associate worker) drops the password into
/// `CWInterface.associate(toNetwork:password:error:)` on hit and
/// falls through to the AppKit sheet on miss / denied / err.
private let kDitingKeychainService = "com.chenchaoyi.diting.tianer"

private func attemptKeychainRead(ssid: String) -> (password: String?, variant: String) {
    let prompt = keychainReadPrompt(ssid: ssid)
    return readSecGenericPassword(
        service: kDitingKeychainService,
        account: ssid,
        prompt: prompt
    )
}

/// Locale-aware reason string for `kSecUseOperationPrompt`. The
/// OS surfaces this in the Touch ID / login-password dialog so the
/// user sees why authentication is being requested. Locale picked
/// from `LANG` / `LC_ALL` so a `--lang zh` diting run shows ZH text
/// here too; note that on some macOS versions the dialog renders
/// against the system locale regardless — Apple does not guarantee
/// `kSecUseOperationPrompt` is honoured. Passing it anyway costs
/// nothing.
private func keychainReadPrompt(ssid: String) -> String {
    let lang = (ProcessInfo.processInfo.environment["LC_ALL"]
                ?? ProcessInfo.processInfo.environment["LANG"]
                ?? "").lowercased()
    if lang.hasPrefix("zh") {
        return "diting 想要连接 Wi-Fi “\(ssid)”"
    }
    return "diting wants to join Wi-Fi “\(ssid)”"
}

private func readSecGenericPassword(
    service: String,
    account: String,
    prompt: String
) -> (password: String?, variant: String) {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service,
        kSecAttrAccount as String: account,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne,
        kSecUseOperationPrompt as String: prompt,
    ]
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    switch status {
    case errSecSuccess:
        guard let data = result as? Data,
              let pw = String(data: data, encoding: .utf8),
              !pw.isEmpty else {
            return (nil, "miss")
        }
        return (pw, "diting")
    case errSecItemNotFound:
        return (nil, "miss")
    case errSecUserCanceled:
        return (nil, "denied")
    default:
        return (nil, "err:\(status)")
    }
}

/// Persist a Wi-Fi password to the user's login keychain so the
/// next `j` on the same SSID can recover it silently (gated by a
/// single Touch ID / login-password gesture — see the read path).
///
/// Items are written under our own `kSecAttrService` namespace
/// (`com.chenchaoyi.diting.tianer`); we never write to
/// `kSecAttrService = "AirPort"` (would compete with macOS's own
/// menu-bar-managed entries) and we never set
/// `kSecAttrSynchronizable` (Wi-Fi passwords stay on this Mac, no
/// iCloud Keychain sync).
///
/// Each `SecItemAdd` attaches a `.userPresence` access-control
/// flag, which resolves at read time to Touch ID, Apple Watch
/// unlock, or login passcode depending on hardware + System
/// Settings. We deliberately avoid `.biometryAny` (would lock
/// Macs without a sensor out entirely) and `.biometryCurrentSet`
/// (adding a new fingerprint would invalidate the entry).
///
/// `SecItemAdd` returns `errSecDuplicateItem` when the SSID has
/// been joined through diting before and the cached password
/// changed (AP key rotation; user typed a fresh one in our sheet
/// because the old cached value `auth_failed`'d). In that path we
/// fall back to `SecItemUpdate` writing **only `kSecValueData`**
/// — passing any other attribute would let macOS replace the
/// item's `kSecAttrAccessControl`, which would re-prompt the user
/// for the `.userPresence` ACL on the next read. Keep the update
/// minimal so rotation is silent on the write side.
private func attemptKeychainWrite(ssid: String, password: String) -> Bool {
    guard let pwData = password.data(using: .utf8) else { return false }
    var sacError: Unmanaged<CFError>?
    guard let access = SecAccessControlCreateWithFlags(
        nil,
        kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        .userPresence,
        &sacError
    ) else {
        // ACL construction failed — extremely unlikely (would mean
        // the user's macOS install lacks the Security framework).
        // Per spec: keychain failures SHALL NOT abort the join, just
        // report keychain_saved: false. Don't try to write without
        // an ACL (that would defeat the whole point of the change).
        return false
    }
    let baseAttrs: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: kDitingKeychainService,
        kSecAttrAccount as String: ssid,
    ]
    var addAttrs = baseAttrs
    addAttrs[kSecValueData as String] = pwData
    addAttrs[kSecAttrAccessControl as String] = access
    let addStatus = SecItemAdd(addAttrs as CFDictionary, nil)
    if addStatus == errSecSuccess { return true }
    if addStatus == errSecDuplicateItem {
        // ACL preservation: update attrs MUST contain only
        // kSecValueData. Adding kSecAttrAccessControl here would
        // re-set the ACL and force the user to re-grant
        // .userPresence on the next read.
        let updateStatus = SecItemUpdate(
            baseAttrs as CFDictionary,
            [kSecValueData as String: pwData] as CFDictionary
        )
        return updateStatus == errSecSuccess
    }
    return false
}

private func associateJSONOK(
    bssid: String?,
    keychainSaved: Bool,
    keychainRead: String? = nil
) -> Data {
    var payload: [String: Any] = [
        "schema": 1,
        "ok": true,
        "keychain_saved": keychainSaved,
    ]
    if let b = bssid { payload["bssid"] = b }
    // `keychain_read` is a diagnostic-only field: which path
    // supplied the cached credential — "diting" on hit, "miss" /
    // "denied" / "err:<status>" on the sheet path, "skipped-open"
    // for open networks. Python ignores unknown JSON keys, so
    // this is safe to log even when the TUI doesn't surface it.
    if let kr = keychainRead { payload["keychain_read"] = kr }
    return (try? JSONSerialization.data(
        withJSONObject: payload,
        options: [.sortedKeys]
    )) ?? Data()
}

private func associateJSONError(message: String, code: String) -> Data {
    let payload: [String: Any] = [
        "schema": 1,
        "error": message,
        "code": code,
    ]
    return (try? JSONSerialization.data(
        withJSONObject: payload,
        options: [.sortedKeys]
    )) ?? Data()
}

/// Outer-half error path: always writes to stdout (no OUT file yet)
/// and exits. Python parser reads from stdout.
private func emitAssociateOuterError(
    message: String, code: String, exitCode: Int32
) -> Never {
    let data = associateJSONError(message: message, code: code)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    exit(exitCode)
}

/// Inner-half exit path: prefers the OUT file so the outer can relay
/// the response unchanged; falls back to stdout when run standalone.
private func emitAssociateInnerExit(payload: Data, exitCode: Int32) -> Never {
    if let outPath = ProcessInfo.processInfo.environment[AssociateEnv.outFile] {
        var data = payload
        if data.last != UInt8(ascii: "\n") {
            data.append(0x0a)
        }
        try? data.write(to: URL(fileURLWithPath: outPath), options: .atomic)
    } else {
        FileHandle.standardOutput.write(payload)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
    exit(exitCode)
}

private func emitAssociateInnerError(
    message: String, code: String, exitCode: Int32
) -> Never {
    emitAssociateInnerExit(
        payload: associateJSONError(message: message, code: code),
        exitCode: exitCode
    )
}

// AppKit sheet + Enterprise hint string lookups. Mirrors the
// `detectHelperLang()` switch that the install-time status window
// uses — keeps the helper's user-facing surface speaking one
// language consistently.
private func associateEnterpriseHint() -> String {
    detectHelperLang() == .zh
        ? "企业 / 802.1X 网络请先用系统 Wi-Fi 菜单加入一次，之后 diting 才能使用保存的凭据。"
        : "Enterprise / 802.1X — join from the system Wi-Fi menu first; diting can use the saved credential afterwards."
}

private func associatePromptTitle(ssid: String) -> String {
    detectHelperLang() == .zh
        ? "请输入 \"\(ssid)\" 的密码"
        : "Enter the password for \"\(ssid)\""
}

private func associatePromptBody() -> String {
    detectHelperLang() == .zh ? "Wi-Fi 密码" : "Wi-Fi password"
}

private func associateRememberLabel() -> String {
    detectHelperLang() == .zh ? "记住此网络" : "Remember this network"
}

private func associateJoinLabel() -> String {
    detectHelperLang() == .zh ? "加入" : "Join"
}

private func associateCancelLabel() -> String {
    detectHelperLang() == .zh ? "取消" : "Cancel"
}

// ---------------------------------------------------------------------
// App-mode localization
//
// Resolution order matches the Python CLI's i18n: DITING_LANG env var
// first (so `open --env DITING_LANG=zh bundle.app` from the Python
// launcher wins), then the user's macOS locale preference. install.sh's
// first-launch `open -g` can't pass env, so the macOS preference is the
// fallback that gets the first popup right for a Chinese-locale user.
// ---------------------------------------------------------------------

private enum HelperLang { case en, zh }

private func detectHelperLang() -> HelperLang {
    if let env = ProcessInfo.processInfo.environment["DITING_LANG"]?.lowercased() {
        return env == "zh" ? .zh : .en
    }
    // Fall back to the same source macOS uses to pick the bundle's
    // .lproj for TCC prompts (Bundle.preferredLocalizations) rather
    // than the user-global Locale.preferredLanguages. Under
    // LaunchServices these two can return different first entries —
    // the helper used to render its status window in English while
    // macOS's Location prompt rendered "谛听 · 天耳" in the same
    // session. Using Bundle.preferredLocalizations guarantees that
    // the helper UI and the macOS prompts speak the same language.
    if let pref = Bundle.main.preferredLocalizations.first?.lowercased(),
       pref.hasPrefix("zh") {
        return .zh
    }
    return .en
}

private struct HelperStrings {
    let lang: HelperLang
    var title: String        { lang == .zh ? "diting 天耳" : "diting tianer" }
    var intro: String {
        switch lang {
        case .zh:
            return "这个辅助 .app 让 diting（Python TUI）能够读取附近 Wi-Fi 的 SSID / BSSID，并扫描附近 BLE 设备 —— 否则 macOS 的「定位服务」和「蓝牙」权限会拦下 Python 进程。下面的弹窗点 Allow 各一次（只用一次），授权完毕关闭此窗口即可。"
        case .en:
            return "This helper exists so diting (the Python TUI) can read nearby Wi-Fi network names / BSSIDs and scan for nearby BLE devices without being blocked by macOS Location Services or Bluetooth permissions. Grant the prompts below — a one-time action — and you can close this window."
        }
    }
    var requestingStatus: String { lang == .zh ? "正在请求权限…" : "Requesting permissions..." }
    var allGranted: String {
        switch lang {
        case .zh:
            return "全部权限已授予。本窗口将在几秒后自动关闭…"
        case .en:
            return "All permissions granted. This window will close automatically in a few seconds..."
        }
    }
    // Location lines
    func locationWaiting() -> String { lang == .zh ? "定位服务：等待用户决定…" : "Location: waiting for permission decision..." }
    func locationRestricted() -> String { lang == .zh ? "定位服务：被系统策略限制。" : "Location: restricted by a system policy." }
    func locationDenied() -> String {
        lang == .zh
            ? "定位服务：被拒绝。请到 系统设置 → 隐私与安全性 → 定位服务 → diting-tianer 启用。"
            : "Location: denied. Enable it in System Settings → Privacy & Security → Location Services → diting-tianer."
    }
    func locationGranted() -> String { lang == .zh ? "定位服务：已授权。" : "Location: granted." }
    func locationUnknown(_ raw: Int) -> String { lang == .zh ? "定位服务：未知状态 \(raw)。" : "Location: unknown state \(raw)." }
    // Bluetooth lines
    func bluetoothQuerying() -> String { lang == .zh ? "蓝牙：正在查询状态…" : "Bluetooth: querying state..." }
    func bluetoothResetting() -> String { lang == .zh ? "蓝牙：正在重置…" : "Bluetooth: resetting..." }
    func bluetoothUnsupported() -> String { lang == .zh ? "蓝牙：本机硬件不支持。" : "Bluetooth: unsupported on this hardware." }
    func bluetoothUnauthorized() -> String {
        lang == .zh
            ? "蓝牙：被拒绝。请到 系统设置 → 隐私与安全性 → 蓝牙 → diting-tianer 启用。"
            : "Bluetooth: denied. Enable it in System Settings → Privacy & Security → Bluetooth → diting-tianer."
    }
    func bluetoothOff() -> String { lang == .zh ? "蓝牙：已关闭。请在控制中心打开蓝牙。" : "Bluetooth: turned off. Toggle it on in Control Center." }
    func bluetoothGranted() -> String { lang == .zh ? "蓝牙：已授权。" : "Bluetooth: granted." }
    func bluetoothUnknown(_ raw: Int) -> String { lang == .zh ? "蓝牙：未知状态 \(raw)。" : "Bluetooth: unknown state \(raw)." }
    // Notification lines
    func notificationsPending() -> String { lang == .zh ? "通知：等待用户决定…" : "Notifications: waiting for permission decision..." }
    func notificationsGranted() -> String { lang == .zh ? "通知：已授权。" : "Notifications: granted." }
    func notificationsDenied() -> String {
        lang == .zh
            ? "通知：被拒绝。可到 系统设置 → 通知 → diting · 天耳 重新开启。"
            : "Notifications: denied. Re-enable in System Settings → Notifications → diting · tianer."
    }
    // Step markers
    var pendingMarker: String   { "→ " }
    var inactiveMarker: String  { "  " }
    func stepPrefix(_ n: Int, of total: Int) -> String { "\(n)/\(total) " }
}

// ---------------------------------------------------------------------
// App mode (Finder launch / open)
// ---------------------------------------------------------------------

private enum InstallStep: Int {
    case requestingLocation = 1
    case requestingBluetooth
    case requestingNotifications
    case allDone
}

final class HelperAppDelegate: NSObject, NSApplicationDelegate, CLLocationManagerDelegate, CBCentralManagerDelegate {
    private var window: NSWindow!
    private var statusLabel: NSTextField!
    private let locationManager = CLLocationManager()
    private var bluetoothManager: CBCentralManager?
    private var locationSettled = false
    private var bluetoothSettled = false
    private var notificationsSettled = false
    private var notificationsGranted = false
    private var autoCloseScheduled = false
    private var step: InstallStep = .requestingLocation
    private let strings = HelperStrings(lang: detectHelperLang())

    func applicationDidFinishLaunching(_ notification: Notification) {
        let frame = NSRect(x: 0, y: 0, width: 520, height: 320)
        window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = strings.title
        window.center()

        let body = NSStackView(frame: NSRect(x: 24, y: 24, width: 472, height: 272))
        body.orientation = .vertical
        body.alignment = .leading
        body.spacing = 12
        body.translatesAutoresizingMaskIntoConstraints = false

        let title = NSTextField(labelWithString: strings.title)
        title.font = NSFont.systemFont(ofSize: 18, weight: .semibold)
        body.addArrangedSubview(title)

        let intro = NSTextField(wrappingLabelWithString: strings.intro)
        intro.preferredMaxLayoutWidth = 472
        body.addArrangedSubview(intro)

        statusLabel = NSTextField(wrappingLabelWithString: strings.requestingStatus)
        statusLabel.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        statusLabel.preferredMaxLayoutWidth = 472
        body.addArrangedSubview(statusLabel)

        window.contentView?.addSubview(body)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Step 1/3 — Location only. The Bluetooth and Notifications
        // requests fire from their predecessor's auth callback, so
        // macOS shows at most one TCC prompt on screen at a time
        // and the status panel can update each line in sequence.
        locationManager.delegate = self
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
        report()
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        DispatchQueue.main.async { self.handleLocationCallback(status) }
    }

    private func handleLocationCallback(_ status: CLAuthorizationStatus) {
        if status == .notDetermined {
            // First fire is .notDetermined right after the request;
            // wait for the user's actual choice before advancing.
            report()
            return
        }
        if !locationSettled {
            locationSettled = true
            // Step 2/3 — Bluetooth. Initialising CBCentralManager
            // from a bundle triggers the macOS Bluetooth TCC prompt
            // the first time. The previous prompt is gone, so the
            // user sees this one cleanly on top of the status panel.
            step = .requestingBluetooth
            bluetoothManager = CBCentralManager(delegate: self, queue: nil)
        }
        report()
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        DispatchQueue.main.async { self.handleBluetoothCallback(central.state) }
    }

    private func handleBluetoothCallback(_ state: CBManagerState) {
        switch state {
        case .unknown, .resetting:
            // Still settling. Don't advance yet.
            report()
            return
        default:
            break
        }
        if !bluetoothSettled {
            bluetoothSettled = true
            // Step 3/3 — Notifications. UNUserNotificationCenter's
            // request fires a system prompt on first call. The
            // completion handler is invoked off the main thread,
            // so we re-enter the state machine on the main queue.
            step = .requestingNotifications
            UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .sound]
            ) { granted, _ in
                DispatchQueue.main.async {
                    self.handleNotificationsCallback(granted: granted)
                }
            }
        }
        report()
    }

    private func handleNotificationsCallback(granted: Bool) {
        notificationsSettled = true
        notificationsGranted = granted
        step = .allDone
        report()
    }

    private func report() {
        let locStatus = locationManager.authorizationStatus
        let btState = bluetoothManager?.state ?? .unknown

        let line1 = renderLine(
            stepNum: 1,
            isCurrent: step == .requestingLocation,
            text: locationLine(locStatus)
        )
        let line2 = renderLine(
            stepNum: 2,
            isCurrent: step == .requestingBluetooth,
            // Show "waiting" if we haven't yet entered this step;
            // otherwise show the live BT state line.
            text: step.rawValue >= InstallStep.requestingBluetooth.rawValue
                ? bluetoothLine(btState)
                : strings.bluetoothQuerying()
        )
        let line3 = renderLine(
            stepNum: 3,
            isCurrent: step == .requestingNotifications,
            text: notificationsLine()
        )
        statusLabel.stringValue = [line1, line2, line3].joined(separator: "\n")

        if step == .allDone && !autoCloseScheduled {
            autoCloseScheduled = true
            statusLabel.stringValue += "\n\n" + strings.allGranted
            // 4 s gives the user a beat to actually read the final
            // outcome before the window vanishes. TCC grants are
            // persistent — diting's Python launcher will pick them
            // up on its next poll cycle regardless.
            DispatchQueue.main.asyncAfter(deadline: .now() + 4.0) {
                NSApp.terminate(nil)
            }
        }
    }

    private func renderLine(stepNum: Int, isCurrent: Bool, text: String) -> String {
        let marker = isCurrent ? strings.pendingMarker : strings.inactiveMarker
        return marker + strings.stepPrefix(stepNum, of: 3) + text
    }

    private func locationLine(_ status: CLAuthorizationStatus) -> String {
        switch status {
        case .notDetermined:
            return strings.locationWaiting()
        case .restricted:
            return strings.locationRestricted()
        case .denied:
            return strings.locationDenied()
        case .authorizedAlways, .authorizedWhenInUse:
            return strings.locationGranted()
        @unknown default:
            return strings.locationUnknown(Int(status.rawValue))
        }
    }

    private func bluetoothLine(_ state: CBManagerState) -> String {
        switch state {
        case .unknown:
            return strings.bluetoothQuerying()
        case .resetting:
            return strings.bluetoothResetting()
        case .unsupported:
            return strings.bluetoothUnsupported()
        case .unauthorized:
            return strings.bluetoothUnauthorized()
        case .poweredOff:
            return strings.bluetoothOff()
        case .poweredOn:
            return strings.bluetoothGranted()
        @unknown default:
            return strings.bluetoothUnknown(Int(state.rawValue))
        }
    }

    private func notificationsLine() -> String {
        if !notificationsSettled {
            return strings.notificationsPending()
        }
        return notificationsGranted
            ? strings.notificationsGranted()
            : strings.notificationsDenied()
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
    case "notification-status":
        runNotificationStatusProbe()
    case "notify":
        runNotifyAndExit(args: Array(args.dropFirst(2)))
    case "associate":
        runAssociateAndExit(args: Array(args.dropFirst(2)))
    case "--help", "-h":
        print("""
        diting-tianer

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
          notification-status
                            Probe Notifications TCC state and exit
                            non-zero when not granted. No JSON output.
                            Exit codes: 0 authorized/provisional,
                            2 timeout / unknown, 3 denied,
                            4 notDetermined.
          notify --title T --body B
                            Post a UserNotification with the helper's
                            bundle identity (icon = diting logo).
                            Best-effort; exits within ~1 s regardless
                            of whether macOS surfaced the notification.
                            Used by the Python TUI watchdog.
          associate --ssid S [--bssid B]
                            Associate to SSID S via CoreWLAN. The password
                            is read from STDIN (never argv — `ps` would
                            otherwise see it); empty stdin drives the
                            Keychain-or-AppKit-sheet resolution chain.
                            Writes one JSON object to stdout on every
                            outcome. Exit codes: 0 ok, 5
                            enterprise_unsupported, 6 cancelled, 7
                            auth_failed, 8 ssid_not_found, 64 bad args.
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
