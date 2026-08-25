#!/usr/bin/env bash

set -euo pipefail

COUNTRY="${1:-Нидерланды}"
CITY="${2:-Амстердам}"
CODE="${3:-NL}"

APP_DIR="/opt/prosto-vpn"
APP_USER="prostovpn"
AWG_DIR="/etc/amnezia/amneziawg"
IFACE="awg0"
PORT=51820
SUBNET="10.8.1"
PANEL_KEY="$APP_DIR/.ssh/panel_ed25519"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }
[[ -d "$APP_DIR/backend" ]] || { warn "сначала выполните deploy/bootstrap.sh"; exit 1; }


if ! command -v awg >/dev/null; then
    log "Ставим AmneziaWG"
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:amnezia/ppa >/dev/null
    apt-get update -qq
    apt-get install -y -qq amneziawg amneziawg-tools
fi

modprobe amneziawg 2>/dev/null || true
if ! lsmod | grep -q amneziawg; then
    warn "Модуль amneziawg не загрузился. Обычно помогает перезагрузка после установки DKMS."
    warn "Проверьте: dkms status; journalctl -k | tail -30"
fi


mkdir -p "$AWG_DIR"
chmod 700 "$AWG_DIR"

if [[ ! -f "$AWG_DIR/server_private.key" ]]; then
    log "Генерируем ключи сервера"
    umask 077
    awg genkey > "$AWG_DIR/server_private.key"
    awg pubkey < "$AWG_DIR/server_private.key" > "$AWG_DIR/server_public.key"
fi

SERVER_PRIV="$(cat "$AWG_DIR/server_private.key")"
SERVER_PUB="$(cat "$AWG_DIR/server_public.key")"

if [[ ! -f "$AWG_DIR/obfuscation.env" ]]; then
    log "Генерируем параметры маскировки"
    python3 - > "$AWG_DIR/obfuscation.env" <<'PY'
import secrets

rng = secrets.SystemRandom()

h = rng.sample(range(5, 2_147_483_647), 4)

jc = rng.randint(3, 6)
jmin = rng.randint(16, 64)
jmax = rng.randint(256, 1000)

s1 = rng.randint(15, 130)
forbidden = s1 + 148 - 92
s2 = rng.choice([v for v in range(15, 131) if v != forbidden])

print(f"JC={jc}")
print(f"JMIN={jmin}")
print(f"JMAX={jmax}")
print(f"S1={s1}")
print(f"S2={s2}")
for i, v in enumerate(h, start=1):
    print(f"H{i}={v}")
PY
    chmod 600 "$AWG_DIR/obfuscation.env"
fi
source "$AWG_DIR/obfuscation.env"


EGRESS="$(ip route show default | awk '/default/ {print $5; exit}')"
PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || ip -4 addr show "$EGRESS" | awk '/inet /{print $2}' | cut -d/ -f1 | head -1)"

if [[ ! -f "$AWG_DIR/$IFACE.conf" ]]; then
    log "Пишем $AWG_DIR/$IFACE.conf"
    cat > "$AWG_DIR/$IFACE.conf" <<EOF
[Interface]
Address = $SUBNET.1/24
ListenPort = $PORT
PrivateKey = $SERVER_PRIV
Jc = $JC
Jmin = $JMIN
Jmax = $JMAX
S1 = $S1
S2 = $S2
H1 = $H1
H2 = $H2
H3 = $H3
H4 = $H4

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o $EGRESS -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o $EGRESS -j MASQUERADE

EOF
    chmod 600 "$AWG_DIR/$IFACE.conf"
fi

log "Включаем маршрутизацию"
cat > /etc/sysctl.d/99-amneziawg.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -p /etc/sysctl.d/99-amneziawg.conf >/dev/null

log "Поднимаем интерфейс $IFACE"
systemctl enable --now "awg-quick@$IFACE" || {
    warn "awg-quick@$IFACE не поднялся. Смотрите: journalctl -u awg-quick@$IFACE -n 40"
    exit 1
}

ufw allow "$PORT/udp" >/dev/null 2>&1 || true


if [[ ! -f "$PANEL_KEY" ]]; then
    log "Создаём SSH-ключ для панели"
    mkdir -p "$APP_DIR/.ssh"
    ssh-keygen -t ed25519 -N "" -C "prosto-panel@$(hostname)" -f "$PANEL_KEY" -q
    chown -R "$APP_USER:$APP_USER" "$APP_DIR/.ssh"
    chmod 700 "$APP_DIR/.ssh"
    chmod 600 "$PANEL_KEY"
fi

mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

PANEL_PUB="$(cat "$PANEL_KEY.pub")"
if ! grep -qF "$PANEL_PUB" /root/.ssh/authorized_keys 2>/dev/null; then
    echo "from=\"127.0.0.1\" $PANEL_PUB" >> /root/.ssh/authorized_keys
fi


log "Регистрируем сервер в панели"
cd "$APP_DIR/backend"

PANEL_SSH_KEY="$(cat "$PANEL_KEY")" \
AWG_DIR="$AWG_DIR" IFACE="$IFACE" PORT="$PORT" PUBLIC_IP="$PUBLIC_IP" \
COUNTRY="$COUNTRY" CITY="$CITY" CODE="$CODE" SERVER_PUB="$SERVER_PUB" \
JC="$JC" JMIN="$JMIN" JMAX="$JMAX" S1="$S1" S2="$S2" \
H1="$H1" H2="$H2" H3="$H3" H4="$H4" \
sudo -u "$APP_USER" -E "$APP_DIR/backend/.venv/bin/python" - <<'PY'
import os
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Provisioning, Server

init_db()

env = os.environ

from app.services.translit import slugify

name = f"{env['CODE'].lower()}-{slugify(env['CITY'], fallback='node')[:6]}-01"

obfuscation = {k: env[k] for k in ("JC", "JMIN", "JMAX", "S1", "S2", "H1", "H2", "H3", "H4")}

template = f"""[Interface]
Address = {{address}}
PrivateKey = {{private_key}}
DNS = 1.1.1.1, 1.0.0.1
MTU = 1280
Jc = {obfuscation['JC']}
Jmin = {obfuscation['JMIN']}
Jmax = {obfuscation['JMAX']}
S1 = {obfuscation['S1']}
S2 = {obfuscation['S2']}
H1 = {obfuscation['H1']}
H2 = {obfuscation['H2']}
H3 = {obfuscation['H3']}
H4 = {obfuscation['H4']}

[Peer]
PublicKey = {env['SERVER_PUB']}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {env['PUBLIC_IP']}:{env['PORT']}
PersistentKeepalive = 25
"""

ssh_key = env["PANEL_SSH_KEY"]

with SessionLocal() as db:
    server = db.scalar(select(Server).where(Server.host == env["PUBLIC_IP"]))
    if server is None:
        server = Server(name=name, host=env["PUBLIC_IP"])
        db.add(server)

    server.name = name
    server.country = env["COUNTRY"]
    server.city = env["CITY"]
    server.country_code = env["CODE"].upper()
    server.port = int(env["PORT"])
    server.is_active = True
    server.provisioning = Provisioning.SSH
    server.awg_template = template
    server.ssh_host = "127.0.0.1"
    server.ssh_port = 22
    server.ssh_user = "root"
    server.ssh_key = ssh_key
    db.commit()
    db.refresh(server)
    print(f"   сервер #{server.id}: {server.country}, {server.city} — {server.host}:{server.port}")
PY

systemctl restart prosto-panel


log "Готово"
cat <<EOF

  VPN-сервер поднят и зарегистрирован в панели.

  Страна:     $COUNTRY, $CITY ($CODE)
  Адрес:      $PUBLIC_IP:$PORT/udp
  Интерфейс:  $IFACE ($SUBNET.0/24)

  Состояние туннеля:  awg show $IFACE
  Служба:             systemctl status awg-quick@$IFACE

  Дальше — в панели создайте пользователя: ключ на этот сервер
  выдастся ему сразу, а в приложении он увидит только «$COUNTRY».

EOF
