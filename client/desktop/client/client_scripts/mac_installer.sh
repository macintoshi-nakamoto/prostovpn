#!/bin/bash

EXTRACT_DIR="$1"
INSTALLER_PATH="$2"

set -e

echo "[NexaVPN] Installer package: $INSTALLER_PATH"

if [ ! -f "$INSTALLER_PATH" ]; then
    echo "[NexaVPN] ERROR: Installer package not found: $INSTALLER_PATH"
    exit 1
fi

PKG_PATH="$INSTALLER_PATH"
echo "[NexaVPN] Using PKG: $PKG_PATH"

# Optional: basic signature/gatekeeper checks (non-fatal)
if command -v pkgutil >/dev/null 2>&1; then
    pkgutil --check-signature "$PKG_PATH" || true
fi
if command -v spctl >/dev/null 2>&1; then
    spctl -a -vvv -t install "$PKG_PATH" || true
fi

# Run installer with admin privileges via AppleScript (prompts for password)
echo "[NexaVPN] Running installer..."
OSA_CMD='do shell script "/usr/sbin/installer -pkg '"$PKG_PATH"' -target /" with administrator privileges'
osascript -e "$OSA_CMD"

STATUS=$?
if [ $STATUS -ne 0 ]; then
    echo "[NexaVPN] ERROR: installer exited with status $STATUS"
    exit $STATUS
fi

echo "[NexaVPN] Cleaning up..."
rm -f "$INSTALLER_PATH" || true
rm -rf "$EXTRACT_DIR" 2>/dev/null || true

echo "[NexaVPN] Installation completed successfully"
exit 0
