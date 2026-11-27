# Build a macOS candidate

Use Apple silicon with macOS 15 or later, Apple Command Line Tools, Python 3 and Gitleaks. From the source folder:

```sh
python3 tools/package/export.py ./source-export
tools/package/build.sh ./build 0.1.0 1
```

Give each command a new output directory. The export reads tracked product files and carries a file list
so the exported folder can build the same product. The build leaves a DMG and its drag-to-Applications layout.
The app contains the source it needs for setup. It installs that source in `~/.viventium-light` on first open
and keeps the app bundle read-only. Models and other dependencies come from their upstream distributors during
setup. On a Mac without Homebrew, Viventium AI opens its signed package in macOS Installer for administrator approval.
Apple’s developer tools are not needed to run the downloaded app. Viventium AI continues setup in the same window
after approval. A small Mac can
require one Grok sign-in, as explained in the setup window.

See [the download inventory](downloads.md) for pins, verification, remaining limits and repair steps.

The build seals the assembled app with an ad-hoc signature. It verifies the seal on the mounted image and
again after copying the app out. The candidate has no Developer ID signature or notarization. Gatekeeper
can block a quarantined copy.

## Signing and notarization

The candidate is not signed with a Developer ID and not notarized yet. The expected signing identity is
**Developer ID Application: xPerfect.ai (TEAMID)**, which needs an Apple Developer Program membership for xPerfect.ai.

Supply the Developer ID Application identity, the Apple team ID and an existing notarytool Keychain profile
for that team. Sign the app first. Re-create the disk image from the signed layout, sign the disk image, then
submit and staple it. The layout has one Mach-O executable and no nested code that needs a separate signature.

```sh
layout='./build/DMG layout'
app="$layout/Viventium AI.app"
dmg='./build/Viventium AI Release.dmg'
: "${DEVELOPER_ID_APPLICATION:?Set the Developer ID Application identity}"
: "${APPLE_TEAM_ID:?Set the Apple team ID}"
: "${NOTARY_PROFILE:?Set the notarytool Keychain profile name}"

codesign --force --options runtime --timestamp --sign "$DEVELOPER_ID_APPLICATION" "$app"
codesign --verify --deep --strict --verbose=2 "$app"
codesign -dv --verbose=4 "$app" 2>&1 | grep -Fx "TeamIdentifier=$APPLE_TEAM_ID" || exit 1
hdiutil create -volname "Viventium AI" -srcfolder "$layout" -fs HFS+ -format UDZO "$dmg"
codesign --timestamp --sign "$DEVELOPER_ID_APPLICATION" "$dmg"
xcrun notarytool submit "$dmg" --keychain-profile "$NOTARY_PROFILE" --wait
# Continue only after the notary service returns Accepted.
xcrun stapler staple "$dmg"
xcrun stapler validate "$dmg"
spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"
```

Follow [Apple's notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).
The release still needs [Sparkle 2](https://sparkle-project.org/documentation/) with its public update key, a hosted
appcast and a tested migration for a changed runtime payload. The candidate reopens an exact installed payload and
preserves a different or pre-existing folder. Test the stapled image and the update path on clean Macs before distribution.
