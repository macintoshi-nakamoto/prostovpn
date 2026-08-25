#!/bin/bash

set -uo pipefail

LABEL="com.prostovpn.helper"
SOCKET="/var/run/prostovpn-helper.sock"

if [ "$(id -u)" != "0" ]; then
    echo "скрипт нужно запускать от root" >&2
    exit 1
fi

if [ -S "$SOCKET" ]; then
    printf '{"cmd":"down"}\n' | nc -U "$SOCKET" >/dev/null 2>&1 || true
fi

launchctl bootout "system/$LABEL" 2>/dev/null || true

rm -f /Library/LaunchDaemons/com.prostovpn.helper.plist
rm -f /Library/PrivilegedHelperTools/com.prostovpn.helper
rm -f /Library/PrivilegedHelperTools/prostovpn-awg
rm -f "$SOCKET"
rm -rf "/Library/Application Support/ProstoVPN"
rm -f /var/log/prostovpn-helper.log

echo "хелпер удалён"
