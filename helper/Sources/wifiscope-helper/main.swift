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
        out.append(row)
    }

    var ifaceMeta: [String: Any] = ["name": iface.interfaceName ?? "?"]
    if let cc = iface.countryCode() { ifaceMeta["country_code"] = cc }
    if let hw = iface.hardwareAddress() { ifaceMeta["hardware_address"] = hw }

    let payload: [String: Any] = [
        "schema": 2,
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

/// CBCentralManager driver for the `ble-scan` subcommand. One JSON
/// object per advertisement is written to stdout, terminated by a
/// newline; the Python side reads the pipe line-by-line.
///
/// Permission failures (`.unauthorized`) emit a single JSON error line
/// and exit code 3 so the Python poller can distinguish "no Bluetooth
/// grant" from "no devices yet" or "subprocess crashed".
final class BLEScanner: NSObject, CBCentralManagerDelegate {
    private var central: CBCentralManager!
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
            "rssi_dbm": RSSI.intValue,
        ]

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

        emitJSONLine(row)
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

func runBLEScan() -> Never {
    let scanner = BLEScanner()
    scanner.start()
    // Park until the parent closes the pipe (SIGPIPE) or sends SIGTERM.
    // dispatchMain() runs the main run loop forever so CoreBluetooth's
    // delegate callbacks fire.
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
    case "--help", "-h":
        print("""
        wifiscope-helper

          (no args)   Launch the bundle UI; request Location Services and
                      Bluetooth, keep the window open so the system
                      prompts can show.
          scan        Perform a CoreWLAN scan and print one JSON document
                      to stdout, then exit. Used by the Python backend
                      as a subprocess.
          ble-scan    Scan nearby BLE advertisements via CoreBluetooth
                      and stream JSON Lines (one ad per line) to stdout
                      until SIGTERM / parent pipe close. Used by the
                      Python BLEPoller.
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
