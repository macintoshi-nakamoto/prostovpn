#!/bin/bash
#
# Собирает Prosto VPN для macOS и упаковывает в DMG.
#
#   ./scripts/make-dmg.sh              подпись ad-hoc, universal (arm64 + x86_64)
#   SIGN_IDENTITY="Developer ID Application: …" ./scripts/make-dmg.sh
#   OUTPUT_DIR=~/Desktop ./scripts/make-dmg.sh
#
# Почему сборка уезжает в ~/Library/Caches, а не в build/ рядом с проектом:
# каталог проекта лежит на Рабочем столе, а Рабочий стол синхронизируется
# iCloud Drive. Файловый провайдер вешает на собираемый .app расширенный
# атрибут com.apple.FinderInfo, и codesign отказывается подписывать такой
# бандл — «resource fork, Finder information, or similar detritus not
# allowed». Вне синхронизируемых папок этого не происходит.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

APP_NAME="ProstoVPN"
VOLUME_NAME="Prosto VPN"
BUILD_ROOT="${BUILD_ROOT:-$HOME/Library/Caches/ProstoVPN-build}"
DERIVED="$BUILD_ROOT/dd"
STAGING="$BUILD_ROOT/dmg"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/dist}"

# Чем подписываем.
#
# Ad-hoc подпись у каждой сборки своя, и связка ключей считает новую версию
# чужой программой: после каждого обновления система спрашивает пароль от
# связки, чтобы отдать приложению его же токен. Поэтому берём любой
# постоянный сертификат, какой есть в системе, — Developer ID, иначе Apple
# Development, — и только если нет ни одного, остаётся ad-hoc.
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
# Вложенное подписываем раньше внешнего: подпись бандла считает хеши того,
# что внутри, и перекладывание после неё её же и ломает.
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
# Ещё раз: ditto переносит атрибуты, а Finder успевает пометить свежую папку.
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
