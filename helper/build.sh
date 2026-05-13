#!/usr/bin/env bash
# Build diting-tianer.app from Swift source.
#
# Output: helper/diting-tianer.app — a minimal Cocoa bundle that
# diting's Python backend can shell out to for unredacted CoreWLAN
# scans once the user has granted Location Services to the bundle.
#
# Requires: Swift 5.9+ (Xcode command line tools or full Xcode).

set -euo pipefail

cd "$(dirname "$0")"

readonly BUNDLE="diting-tianer.app"
readonly BIN_NAME="diting-tianer"

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

# Ship per-locale InfoPlist.strings overrides so macOS's TCC
# prompts (Location / Bluetooth) AND the Finder display name pick
# up Chinese strings for zh users instead of the English defaults
# baked into Info.plist. Without these, the user sees one prompt
# with "谛听 · 天耳" (CFBundleDisplayName) and another with
# "diting-tianer.app" (the bundle filename), since macOS uses
# different name sources across TCC prompt categories.
for lproj in Resources/*.lproj; do
    if [ -d "$lproj" ]; then
        cp -R "$lproj" "$BUNDLE/Contents/Resources/"
    fi
done

echo "==> ad-hoc code signing"
# Ad-hoc signature is enough for local use; macOS still recognises the
# bundle as a distinct TCC subject. For distribution, replace `-` with
# a Developer ID identity.
codesign --force --deep --sign - "$BUNDLE"

echo
echo "Built $(pwd)/$BUNDLE"
echo
echo "Next steps:"
echo "  1. open $BUNDLE                 # triggers Location + Bluetooth prompts"
echo "  2. Click Allow on each prompt, close the window"
echo "  3. Run \`uv run diting\` — the in-place bundle is auto-detected"
echo
echo "(Leave the bundle here. Moving it into /Applications is no longer"
echo " recommended — TCC keys grants by cdhash, and a copy / move would"
echo " force you to re-grant the prompts.)"
