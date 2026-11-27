#!/usr/bin/env bash
# Build the native Apple silicon app and its drag-to-Applications disk image.
set -euo pipefail
umask 077
root=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:?Usage: build.sh NEW_OUTPUT_DIR VERSION BUILD_NUMBER}
version=${2:?Supply a version such as 0.1.0}
build=${3:?Supply an increasing build number}
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$build" =~ ^[0-9]+$ ]]
mkdir "$out"
out=$(cd "$out" && pwd)
tmp=$(mktemp -d "$out/.build.XXXXXXXX")
layout="$tmp/layout"
volume="$tmp/volume"
app_name="Viventium AI.app"
app="$layout/$app_name"
image="$tmp/Viventium AI.dmg"
mounted=
cleanup() {
  if [ -n "$mounted" ]; then hdiutil detach "$volume" || return; fi
  rm -rf "$tmp"
}
trap cleanup EXIT
# The private output directory contains a bundle that any user can read and open.
umask 022
bin="$app/Contents/MacOS/Viventium"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$tmp/AppIcon.iconset" "$volume"
python3 "$root/tools/package/export.py" --payload "$app/Contents/Resources/Light"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root" python3 -c 'import json; from settings.catalog import setup_accounts; print(json.dumps(setup_accounts()))' \
  > "$app/Contents/Resources/SetupAccounts.json"
source=$(cat "$app/Contents/Resources/Light/.vx-release")
swiftc -target arm64-apple-macos15.0 -O -module-cache-path "$tmp/modules" \
  -o "$bin" "$root/tools/menubar/main.swift"
for side in 16 32 128 256 512; do
  "$bin" --icon "$tmp/AppIcon.iconset/icon_${side}x${side}.png" "$side"
  "$bin" --icon "$tmp/AppIcon.iconset/icon_${side}x${side}@2x.png" "$((side * 2))"
done
iconutil -c icns -o "$app/Contents/Resources/AppIcon.icns" "$tmp/AppIcon.iconset"
cat >"$app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>ai.viventium.light</string>
  <key>CFBundleName</key><string>Viventium AI</string>
  <key>CFBundleDisplayName</key><string>Viventium AI</string>
  <key>NSHumanReadableCopyright</key><string>© 2026 xPerfect.ai</string>
  <key>CFBundleExecutable</key><string>Viventium</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>$build</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>LSUIElement</key><true/>
  <key>ViventiumPackaged</key><true/>
  <key>ViventiumSource</key><string>$source</string>
</dict></plist>
EOF
plutil -lint "$app/Contents/Info.plist"
ln -s /Applications "$layout/Applications"
# The launcher is the only executable code in the bundle. Sign any future nested code before sealing the app.
codesign --force --sign - "$app"
hdiutil create -volname "Viventium AI" -srcfolder "$layout" -fs HFS+ -format UDZO "$image"
hdiutil attach -readonly -nobrowse -mountpoint "$volume" "$image"
mounted=1
codesign --verify --deep --strict --verbose=2 "$volume/$app_name"
ditto "$volume/$app_name" "$tmp/Applications/$app_name"
hdiutil detach "$volume"
mounted=
codesign --verify --deep --strict --verbose=2 "$tmp/Applications/$app_name"
mv "$layout" "$out/DMG layout"
mv "$image" "$out/Viventium AI.dmg"
