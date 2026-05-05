#!/usr/bin/env bash
# Build wifiscope-helper.app from Swift source.
#
# Output: helper/wifiscope-helper.app — a minimal Cocoa bundle that
# wifiscope's Python backend can shell out to for unredacted CoreWLAN
# scans once the user has granted Location Services to the bundle.
#
# Requires: Swift 5.9+ (Xcode command line tools or full Xcode).

set -euo pipefail

cd "$(dirname "$0")"

readonly BUNDLE="wifiscope-helper.app"
readonly BIN_NAME="wifiscope-helper"

echo "==> swift build -c release"
swift build -c release --product "$BIN_NAME"

readonly BIN_PATH=".build/release/$BIN_NAME"
if [ ! -f "$BIN_PATH" ]; then
    echo "build failed: $BIN_PATH does not exist" >&2
    exit 1
fi

echo "==> assembling $BUNDLE"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS"
mkdir -p "$BUNDLE/Contents/Resources"
cp Info.plist "$BUNDLE/Contents/Info.plist"
cp "$BIN_PATH" "$BUNDLE/Contents/MacOS/$BIN_NAME"
chmod +x "$BUNDLE/Contents/MacOS/$BIN_NAME"

echo "==> ad-hoc code signing"
# Ad-hoc signature is enough for local use; macOS still recognises the
# bundle as a distinct TCC subject. For distribution, replace `-` with
# a Developer ID identity.
codesign --force --deep --sign - "$BUNDLE"

echo
echo "Built $(pwd)/$BUNDLE"
echo
echo "Next steps:"
echo "  1. mv $BUNDLE /Applications/   (or ~/Applications, or leave it here)"
echo "  2. open $BUNDLE                 # triggers Location Services prompt"
echo "  3. Grant the prompt, close the window"
echo "  4. Run wifiscope normally — its scan path will pick the helper up"
