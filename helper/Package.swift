// swift-tools-version:5.9
import PackageDescription

// `Info.plist` is embedded into the binary's `__TEXT,__info_plist` section
// in addition to being copied to `wifiscope-helper.app/Contents/Info.plist`
// during build. The bundle copy is what Finder / launchd / Gatekeeper read
// for GUI launches; the embedded copy is what TCC reads when the binary is
// spawned directly as a subprocess (the path our Python TUI uses for both
// `scan` and `ble-scan`). Without the embed, TCC sends SIGABRT on the
// first CBCentralManager call from a subprocess invocation, claiming
// `NSBluetoothAlwaysUsageDescription` is missing — even though the bundle
// plist has it — because the strict TCC path does not fall back to
// Contents/Info.plist when bundle context was not set up by launchd.
let package = Package(
    name: "wifiscope-helper",
    platforms: [.macOS(.v11)],
    targets: [
        .executableTarget(
            name: "wifiscope-helper",
            path: "Sources/wifiscope-helper",
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Info.plist",
                ])
            ]
        )
    ]
)
