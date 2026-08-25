#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

APP_NAME="ProstoVPN"
VOLUME_NAME="Prosto VPN"
BUILD_ROOT="${BUILD_ROOT:-$HOME/Library/Caches/ProstoVPN-build}"
DERIVED="$BUILD_ROOT/dd"
STAGING="$BUILD_ROOT/dmg"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/dist}"

if [ -z "${SIGN_IDENTITY:-}" ]; then
    SIGN_IDENTITY="$(security find-identity -v -p codesigning \
        | grep -o '"Developer ID Application: [^"]*"' | head -1 | tr -d '"' || true)"
fi
if [ -z "$SIGN_IDENTITY" ]; then
    SIGN_IDENTITY="$(security find-identity -v -p codesigning \
        | grep -o '"Apple Development: [^"]*"' | head -1 | tr -d '"' || true)"
fi
SIGN_IDENTITY="${SIGN_IDENTITY:--}"

echo "→ движок"
if [ ! -x "Engine/bin/prostovpn-awg" ]; then
    ./Engine/build.sh
fi

echo "→ сборка Release (arm64 + x86_64)"
rm -rf "$DERIVED/Build/Products/Release/$APP_NAME.app"
xcodebuild \
    -project "$APP_NAME.xcodeproj" \
    -scheme "$APP_NAME" \
    -configuration Release \
    -derivedDataPath "$DERIVED" \
    ARCHS="arm64 x86_64" \
    ONLY_ACTIVE_ARCH=NO \
    build >"$BUILD_ROOT/xcodebuild.log" 2>&1 || {
        echo "сборка не удалась, подробности: $BUILD_ROOT/xcodebuild.log" >&2
        tail -30 "$BUILD_ROOT/xcodebuild.log" >&2
        exit 1
    }

APP="$DERIVED/Build/Products/Release/$APP_NAME.app"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$APP/Contents/Info.plist")"
echo "  версия $VERSION"

echo "→ подпись ($SIGN_IDENTITY)"
xattr -cr "$APP"
codesign --force --options runtime --timestamp=none \
    --sign "$SIGN_IDENTITY" "$APP/Contents/Resources/prostovpn-awg"
codesign --force --options runtime --timestamp=none \
    --sign "$SIGN_IDENTITY" "$APP/Contents/Resources/com.prostovpn.helper"
codesign --force --options runtime --timestamp=none \
    --entitlements "$ROOT/$APP_NAME/$APP_NAME.entitlements" \
    --sign "$SIGN_IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"

echo "→ образ"
rm -rf "$STAGING"
mkdir -p "$STAGING"
ditto "$APP" "$STAGING/$APP_NAME.app"
ln -s /Applications "$STAGING/Applications"
cp "$ROOT/scripts/dmg-readme.txt" "$STAGING/Как установить.txt"
xattr -cr "$STAGING"

mkdir -p "$OUTPUT_DIR"
DMG="$OUTPUT_DIR/ProstoVPN-$VERSION.dmg"
rm -f "$DMG"
hdiutil create \
    -volname "$VOLUME_NAME" \
    -srcfolder "$STAGING" \
    -fs HFS+ \
    -format UDZO \
    -ov \
    -quiet \
    "$DMG"

if [ "$SIGN_IDENTITY" != "-" ]; then
    codesign --force --sign "$SIGN_IDENTITY" "$DMG"
fi

SIZE="$(stat -f %z "$DMG")"
SHA="$(shasum -a 256 "$DMG" | cut -d' ' -f1)"

cat <<INFO

Готово: $DMG
  версия  $VERSION
  размер  $SIZE байт
  sha256  $SHA

Публикация в панели (она посчитает sha256 сама, если файл лежит в
каталоге установщиков):

  POST /api/v1/admin/releases {"platform":"macos","version":"$VERSION","url":"https://prostovpn.cc/downloads/$(basename "$DMG")"}
INFO
