// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "wifiscope-helper",
    platforms: [.macOS(.v11)],
    targets: [
        .executableTarget(
            name: "wifiscope-helper",
            path: "Sources/wifiscope-helper"
        )
    ]
)
