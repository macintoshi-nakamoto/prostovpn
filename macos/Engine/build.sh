#!/bin/bash
#
# Собирает движок AmneziaWG для macOS в universal-бинарник.
#
# Движок — обычный userspace-демон: поднимает utun, слушает UAPI-сокет и
# сам ничего не знает ни про адреса, ни про маршруты. Всё остальное делает
# хелпер (см. macos/Helper).
#
# Исходники не кладём в репозиторий: они большие и живут своей жизнью.
# Скрипт клонирует их сам, если папки src нет.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
OUT="$HERE/bin"
REPO="https://github.com/amnezia-vpn/amneziawg-go.git"

if [ ! -d "$SRC" ]; then
    echo "→ исходники движка: клонирую $REPO"
    git clone --depth 1 "$REPO" "$SRC"
fi

mkdir -p "$OUT"
cd "$SRC"

# CGO выключен: движку хватает чистого Go, а без него бинарник собирается
# под обе архитектуры без установки кросс-тулчейнов.
for arch in arm64 amd64; do
    echo "→ сборка darwin/$arch"
    GOOS=darwin GOARCH="$arch" CGO_ENABLED=0 \
        go build -trimpath -ldflags "-s -w" -o "$OUT/prostovpn-awg-$arch" .
done

echo "→ склейка universal"
lipo -create -output "$OUT/prostovpn-awg" \
    "$OUT/prostovpn-awg-arm64" "$OUT/prostovpn-awg-amd64"
rm -f "$OUT/prostovpn-awg-arm64" "$OUT/prostovpn-awg-amd64"
chmod +x "$OUT/prostovpn-awg"

lipo -info "$OUT/prostovpn-awg"
