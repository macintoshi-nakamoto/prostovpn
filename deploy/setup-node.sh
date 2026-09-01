#!/usr/bin/env bash

set -euo pipefail

PANEL_IP="${1:-}"
AWG_DIR=/etc/amnezia/amneziawg

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }
[[ -n "$PANEL_IP" ]] || { warn "укажите адрес панели: sudo bash $0 <IP-панели>"; exit 1; }

export DEBIAN_FRONTEND=noninteractive

log "Системные пакеты"
apt-get update -qq
apt-get install -y -qq software-properties-common curl unzip iptables ca-certificates rsync

log "AmneziaWG"
if ! command -v awg >/dev/null; then
    if ! add-apt-repository -y ppa:amnezia/ppa >/dev/null 2>&1; then
        warn "add-apt-repository не прошёл — прописываем источник напрямую"
        curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x4166f2c257290828" \
            | gpg --dearmor > /usr/share/keyrings/amnezia.gpg
        cat > /etc/apt/sources.list.d/amnezia.sources <<SRC
Types: deb
URIs: https://ppa.launchpadcontent.net/amnezia/ppa/ubuntu/
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: main
Signed-By: /usr/share/keyrings/amnezia.gpg
SRC
    fi
    apt-get update -qq
    apt-get install -y -qq "linux-headers-$(uname -r)" || true
    apt-get install -y -qq amneziawg amneziawg-tools
fi

modprobe amneziawg 2>/dev/null || true
if lsmod | grep -q amneziawg; then
    ok "модуль загружен"
else
    warn "модуль amneziawg не загрузился — обычно помогает перезагрузка после DKMS"
    warn "проверьте: dkms status; journalctl -k | tail -30"
fi
install -d -m 700 "$AWG_DIR"

log "Форвардинг и BBR"
cat > /etc/sysctl.d/99-prosto-node.conf <<'SYS'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
net.core.default_qdisc = fq_codel
net.ipv4.tcp_congestion_control = bbr
SYS
sysctl --system >/dev/null
ok "ip_forward=$(sysctl -n net.ipv4.ip_forward), cc=$(sysctl -n net.ipv4.tcp_congestion_control)"

log "Ключ панели"
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
if grep -q 'prosto-panel' /root/.ssh/authorized_keys; then
    ok "ключ панели уже прописан"
else
    warn "ключ панели НЕ прописан. С панели выполните:"
    echo "     ssh-copy-id не годится — ключ должен быть ограничен адресом:"
    echo "     echo 'from=\"$PANEL_IP\" '\"\$(cat /opt/prosto-vpn/.ssh/panel_ed25519.pub)\" \\"
    echo "       | ssh root@<этот-узел> 'cat >> /root/.ssh/authorized_keys'"
fi

log "Готово"
echo "   Дальше на этом же узле:"
echo "     sudo bash deploy/setup-xray.sh                 # VLESS+Reality (443 здесь свободен)"
echo "     sudo bash deploy/extra-ports.sh 443 4500 2408 8443 # запасные UDP-порты для AWG"
echo "     sudo bash deploy/node-watchdog.sh --install       # сторож: awg, редиректы, xray"
echo
echo "   Про 443. На отдельном узле nginx нет, поэтому Reality вешается прямо"
echo "   на 443/TCP — stream-слой с SNI-роутингом (deploy/server/reality-443)"
echo "   нужен только там, где 443 уже занят панелью."
echo "   443/UDP при этом свободен и достаётся AWG: он неотличим от QUIC и"
echo "   проходит там, где 51820 давно режут. Раньше панель считала порт"
echo "   занятым по обоим транспортам сразу и не давала так сделать —"
echo "   теперь проверка смотрит на транспорт, и 443 можно держать дважды."
