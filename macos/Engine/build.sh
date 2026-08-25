#!/bin/bash

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
OUT="$HERE/bin"
REPO="https://github.com/amnezia-vpn/amneziawg-go.git"
REF="v3.1.20260814"

if [ ! -d "$SRC" ]; then
    echo "→ исходники движка: клонирую $REPO"
    git clone "$REPO" "$SRC"
fi

cd "$SRC"
git fetch --tags --quiet origin
git checkout --quiet "$REF"
echo "→ движок на $REF ($(git rev-parse --short HEAD))"
cd "$HERE"

mkdir -p "$OUT"
cd "$SRC"

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
