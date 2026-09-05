#!/usr/bin/env bash
#
# Установка агента на узел: бинарник, настройки, служба.
#
#   sudo bash install.sh https://prostovpn.cc <токен из панели>
#
# Токен выдаёт панель: `python tools/agent_token.py <имя узла>` на веб-сервере.
# Повторный запуск с новым токеном просто перезаписывает настройки.
set -euo pipefail

PANEL_URL="${1:-}"
TOKEN="${2:-}"
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
[[ -n "$PANEL_URL" && -n "$TOKEN" ]] || { echo "использование: install.sh <panel_url> <token>"; exit 1; }
[[ -f "$HERE/prosto-node" ]] || { echo "рядом со скриптом нет бинарника prosto-node"; exit 1; }

install -m 0755 "$HERE/prosto-node" /usr/local/bin/prosto-node
install -d -m 0700 /etc/prosto-node
umask 077
cat > /etc/prosto-node/agent.conf <<CONF
PANEL_URL=$PANEL_URL
TOKEN=$TOKEN
INTERVAL=15
CONF
umask 022

install -m 0644 "$HERE/prosto-node.service" /etc/systemd/system/prosto-node.service
systemctl daemon-reload
systemctl enable --now prosto-node
sleep 2
systemctl --no-pager --lines=5 status prosto-node || true

echo
echo "Пробный снимок (без отправки):"
/usr/local/bin/prosto-node --once | head -c 600
echo
