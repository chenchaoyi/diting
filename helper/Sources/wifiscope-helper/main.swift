// wifiscope-helper — Swift sidecar that owns the macOS Location Services
// permission so the Python TUI can read unredacted scan-list SSIDs and
// BSSIDs.
//
// Two roles in one binary:
//
//   wifiscope-helper           (no args, launched as a .app from Finder
//                               via `open` or by Launch Services)
//                              -> opens a small AppKit window, requests
//                                 Location Services authorization,
//                                 parks until the user closes the window
//                                 so the bundle stays foregrounded long
//                                 enough for the system prompt.
//
//   wifiscope-helper scan      (invoked by the Python backend as a
//                               subprocess)
//                              -> performs a CoreWLAN scan, prints a
//                                 single JSON document {"networks": [...]}
//                                 to stdout, exits.
//
// The bundle's Info.plist declares NSLocationUsageDescription, so the
// .app shows up in System Settings -> Privacy & Security -> Location
// Services after first launch and is grantable. Once granted, the
// CLI subprocess inherits the bundle's TCC identity and CoreWLAN
// returns full identity fields for every scanned network.

import Cocoa
import CoreLocation
import CoreWLAN
import Foundation

// ---------------------------------------------------------------------
// CLI mode
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
// App mode (Finder launch / open)
// ---------------------------------------------------------------------

final class HelperAppDelegate: NSObject, NSApplicationDelegate, CLLocationManagerDelegate {
    private var window: NSWindow!
    private var statusLabel: NSTextField!
    private let locationManager = CLLocationManager()

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
            "nearby Wi-Fi network names and BSSIDs without being blocked " +
            "by macOS Location Services. Grant the prompt below — it's a " +
            "one-time action — and you can close this window."
        )
        intro.preferredMaxLayoutWidth = 472
        body.addArrangedSubview(intro)

        statusLabel = NSTextField(wrappingLabelWithString: "Requesting permission...")
        statusLabel.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        statusLabel.preferredMaxLayoutWidth = 472
        body.addArrangedSubview(statusLabel)

        window.contentView?.addSubview(body)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        locationManager.delegate = self
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
        report(locationManager.authorizationStatus)
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        DispatchQueue.main.async { self.report(status) }
    }

    private func report(_ status: CLAuthorizationStatus) {
        switch status {
        case .notDetermined:
            statusLabel.stringValue = "Waiting for permission decision..."
        case .restricted:
            statusLabel.stringValue = "Location Services is restricted by a system policy. wifiscope cannot read nearby BSSIDs."
        case .denied:
            statusLabel.stringValue =
                "Location Services denied.\n" +
                "Open System Settings → Privacy & Security → Location Services → " +
                "wifiscope-helper, toggle ON, then relaunch this app."
        case .authorizedAlways, .authorizedWhenInUse:
            statusLabel.stringValue = "✓ Permission granted. wifiscope (Python) is ready to use; you may quit this window."
        @unknown default:
            statusLabel.stringValue = "Unknown auth state \(status.rawValue)"
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
    case "--help", "-h":
        print("""
        wifiscope-helper

          (no args)   Launch the bundle UI; request Location Services and
                      keep the window open so the system prompt can show.
          scan        Perform a CoreWLAN scan and print one JSON document
                      to stdout, then exit. Used by the Python backend
                      as a subprocess.
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
