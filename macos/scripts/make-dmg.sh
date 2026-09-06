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

# Нотаризация: без неё macOS 15 не даёт открыть даже образ («автор является
# неустановленным разработчиком»), а приложение — только через Настройки →
# «Открыть всё равно». Нужны Developer ID (платная программа Apple) и профиль
# notarytool в связке ключей:
#   xcrun notarytool store-credentials prosto --apple-id <почта> --team-id <TEAM> --password <app-specific>
# Тогда: NOTARY_PROFILE=prosto ./scripts/make-dmg.sh — образ уйдёт к Apple,
# дождётся вердикта и получит скрепку (stapler), после чего открывается молча.
NOTARY_PROFILE="${NOTARY_PROFILE:-}"
case "$SIGN_IDENTITY" in
    "Developer ID Application:"*) TIMESTAMP="--timestamp" ;;  # нотаризации нужна доверенная метка времени
    *) TIMESTAMP="--timestamp=none" ;;
esac
if [ -n "$NOTARY_PROFILE" ] && [ "$TIMESTAMP" != "--timestamp" ]; then
    echo "NOTARY_PROFILE задан, но подписи Developer ID нет ($SIGN_IDENTITY) — Apple такой образ не примет" >&2
    exit 1
fi

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
codesign --force --options runtime "$TIMESTAMP" \
    --sign "$SIGN_IDENTITY" "$APP/Contents/Resources/prostovpn-awg"
codesign --force --options runtime "$TIMESTAMP" \
    --sign "$SIGN_IDENTITY" "$APP/Contents/Resources/com.prostovpn.helper"
codesign --force --options runtime "$TIMESTAMP" \
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
    codesign --force "$TIMESTAMP" --sign "$SIGN_IDENTITY" "$DMG"
fi

if [ -n "$NOTARY_PROFILE" ]; then
    echo "→ нотаризация (обычно 1–5 минут)"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    # Проверка глазами Gatekeeper: должно быть «accepted», source=Notarized Developer ID.
    spctl -a -t open --context context:primary-signature -v "$DMG" || true
else
    echo "  без нотаризации: на macOS 15 образ откроется только через Настройки → «Открыть всё равно»"
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
