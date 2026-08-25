#!/bin/bash

set -euo pipefail

HELPER_SRC="${1:?нужен путь к бинарнику хелпера}"
ENGINE_SRC="${2:?нужен путь к бинарнику движка}"
PLIST_SRC="${3:?нужен путь к plist демона}"
OWNER_UID="${4:?нужен uid владельца}"

HELPER_DST="/Library/PrivilegedHelperTools/com.prostovpn.helper"
ENGINE_DST="/Library/PrivilegedHelperTools/prostovpn-awg"
PLIST_DST="/Library/LaunchDaemons/com.prostovpn.helper.plist"
SUPPORT_DIR="/Library/Application Support/ProstoVPN"
SOCKET="/var/run/prostovpn-helper.sock"
LABEL="com.prostovpn.helper"

if [ "$(id -u)" != "0" ]; then
    echo "скрипт нужно запускать от root" >&2
    exit 1
fi


launchctl bootout "system/$LABEL" 2>/dev/null || true

for _ in $(seq 1 60); do
    launchctl print "system/$LABEL" >/dev/null 2>&1 || break
    sleep 0.25
done

pkill -f "^$HELPER_DST$" 2>/dev/null || true
sleep 0.2

rm -f "$SOCKET"


mkdir -p /Library/PrivilegedHelperTools
install -o root -g wheel -m 755 "$HELPER_SRC" "$HELPER_DST"
install -o root -g wheel -m 755 "$ENGINE_SRC" "$ENGINE_DST"

mkdir -p "$SUPPORT_DIR"
chown root:wheel "$SUPPORT_DIR"
chmod 755 "$SUPPORT_DIR"
printf '%s' "$OWNER_UID" > "$SUPPORT_DIR/owner.uid"
chown root:wheel "$SUPPORT_DIR/owner.uid"
chmod 644 "$SUPPORT_DIR/owner.uid"

install -o root -g wheel -m 644 "$PLIST_SRC" "$PLIST_DST"


bootstrapped=0
for _ in $(seq 1 5); do
    if launchctl bootstrap system "$PLIST_DST" 2>/dev/null; then
        bootstrapped=1
        break
    fi
    launchctl bootout "system/$LABEL" 2>/dev/null || true
    sleep 1
done

if [ "$bootstrapped" != "1" ]; then
    echo "launchd не принял службу:" >&2
    launchctl print "system/$LABEL" 2>&1 | head -20 >&2
    exit 1
fi

launchctl enable "system/$LABEL" 2>/dev/null || true
launchctl kickstart "system/$LABEL" 2>/dev/null || true

for _ in $(seq 1 100); do
    if [ -S "$SOCKET" ]; then
        exit 0
    fi
    sleep 0.1
done

echo "служба установлена, но сокет так и не появился" >&2
tail -20 /var/log/prostovpn-helper.log 2>/dev/null >&2 || true
exit 1
