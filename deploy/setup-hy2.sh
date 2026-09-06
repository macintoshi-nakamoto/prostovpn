#!/usr/bin/env bash
#
# Hysteria2 на узле — третий протокол, для сторонних приложений (Happ).
#
# Зачем: на сотовых сетях в РФ к 2026 году операторы ловят VPN по повадкам
# трафика, а не по содержимому. AmneziaWG ловят быстро, Reality нестабилен,
# а Hysteria2 (QUIC, как Zoom/Discord/HTTP-3) держится — его нельзя душить,
# не задев легальный UDP. Панель отдаёт ссылку hysteria2:// рядом с vless://.
#
# Как устроено: слушает UDP/443 (порт HTTP/3, максимально обыденный) и
# диапазон «прыгающих» портов, который iptables заворачивает на 443.
# Пользователей не хранит — доступ решает панель (POST /api/v1/hy2/auth),
# паролем служит UUID VLESS-учётки человека на этом узле. Спрашивает её
# скрипт prosto-hy2-auth.sh (auth.type: command) с кэшем ответов и бюджетом
# обращений: мусорные пароли с 443/udp не превращаются в шторм запросов к
# панели, а при её недоступности знакомые пароли пускаются по памяти.
# Сертификат самоподписанный: клиент идёт с insecure=1, а DPI видит только
# SNI из ссылки. На HTTP/3-зонды отвечает как донор Reality.
#
#   sudo bash deploy/setup-hy2.sh www.google.com   # донор = SNI в ссылке
#   sudo bash deploy/setup-hy2.sh --status
#   sudo bash deploy/setup-hy2.sh --remove
#
# 443/UDP до этого был запасным портом AmneziaWG: скрипт снимает его из
# /etc/prosto-extra-ports.conf и перезапускает prosto-extra-ports. В панели
# порт 443 у AWG-точек тоже надо убрать из запасных — иначе приложения будут
# стучаться в Hysteria2 рукопожатием AWG.

set -euo pipefail

HY2_VERSION="${HY2_VERSION:-v2.12.2}"
HY2_SHA256="${HY2_SHA256:-6493dfffd55b5883f64c76c63880ecc32988f0c568c9ca9014907877b4d55f94}"
PANEL_URL="${PANEL_URL:-https://prostovpn.cc}"
HY2_PORT="${HY2_PORT:-443}"
HY2_HOP="${HY2_HOP:-20000-30000}"
STATS_PORT="${STATS_PORT:-10086}"

DIR=/opt/prosto-hy2
BIN="$DIR/hysteria"
CFG="$DIR/config.yaml"
SERVICE_USER=prosto-hy2
UNIT=/etc/systemd/system/prosto-hy2.service
PORTS_FILE=/etc/prosto-hy2-ports.conf
PORTS_BIN=/usr/local/bin/prosto-hy2-ports
AUTH_BIN=/usr/local/bin/prosto-hy2-auth
AUTH_CONF=/etc/prosto-hy2-auth.conf
CACHE_DIR=/var/lib/prosto-hy2
EXTRA_FILE=/etc/prosto-extra-ports.conf

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }

case "${1:-}" in
    --status)
        log "Служба"
        systemctl status prosto-hy2 --no-pager 2>/dev/null | head -8 || echo "   (не установлена)"
        log "Что слушает"
        ss -lunp 2>/dev/null | grep -E "hysteria" || echo "   (ничего)"
        log "Редирект прыгающих портов"
        iptables -t nat -S PREROUTING | grep -E "REDIRECT.*--to-ports ${HY2_PORT}\b" || echo "   (нет)"
        log "Версия"
        [[ -x "$BIN" ]] && "$BIN" version | grep -E "^Version" || echo "   (нет бинарника)"
        exit 0
        ;;
    --remove)
        log "Снимаем Hysteria2"
        systemctl disable --now prosto-hy2 2>/dev/null || true
        [[ -x "$PORTS_BIN" ]] && "$PORTS_BIN" --close || true
        rm -f "$UNIT" "$PORTS_BIN" "$PORTS_FILE" "$AUTH_BIN" "$AUTH_CONF"
        systemctl daemon-reload
        rm -rf "$DIR" "$CACHE_DIR"
        userdel "$SERVICE_USER" 2>/dev/null || true
        ok "снято; 443/UDP снова свободен — верните его AWG через extra-ports.sh"
        exit 0
        ;;
esac

SNI="${1:-www.google.com}"
WAN="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"
[[ -n "$WAN" ]] || { warn "не удалось определить внешний интерфейс"; exit 1; }

id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -m 0750 -o root -g "$SERVICE_USER" "$DIR"

log "Бинарник Hysteria2 ${HY2_VERSION}"
if [[ -x "$BIN" ]] && "$BIN" version 2>/dev/null | grep -q "${HY2_VERSION#v}"; then
    ok "уже стоит"
else
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "https://github.com/HyNetworks/hysteria/releases/download/app/${HY2_VERSION}/hysteria-linux-amd64" -o "$tmp/hysteria"
    got="$(sha256sum "$tmp/hysteria" | awk '{print $1}')"
    if [[ -n "$HY2_SHA256" && "$got" != "$HY2_SHA256" ]]; then
        warn "sha256 не совпал: $got"; exit 1
    fi
    install -m 0755 -o root -g root "$tmp/hysteria" "$BIN"
    ok "поставлен, sha256 $got"
fi

TLS_DIR=/opt/prosto-tls
CERT="$DIR/cert.pem"; KEY="$DIR/key.pem"; REAL_CERT=0
if [[ -s "$TLS_DIR/fullchain.pem" && -s "$TLS_DIR/privkey.pem" ]]; then
    # Настоящий сертификат своего домена разложен с веб-сервера
    # (deploy/server/certbot-deploy-nodes.sh) — берём его, клиенту insecure не нужен.
    CERT="$TLS_DIR/fullchain.pem"; KEY="$TLS_DIR/privkey.pem"; REAL_CERT=1
    log "Сертификат: настоящий, $TLS_DIR ($(openssl x509 -in "$CERT" -noout -subject 2>/dev/null | sed 's/subject=//'))"
else
log "Сертификат (самоподписанный, CN=$SNI)"
if [[ ! -s "$DIR/cert.pem" || ! -s "$DIR/key.pem" ]]; then
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -days 3650 -nodes \
        -subj "/CN=$SNI" -keyout "$DIR/key.pem" -out "$DIR/cert.pem" >/dev/null 2>&1
    ok "выпущен"
else
    ok "уже есть"
fi
chown root:"$SERVICE_USER" "$DIR/cert.pem" "$DIR/key.pem"
chmod 0640 "$DIR/cert.pem" "$DIR/key.pem"
fi

if [[ ! -s "$DIR/stats.secret" ]]; then
    head -c 24 /dev/urandom | base64 | tr -d '/+=' > "$DIR/stats.secret"
fi
chown root:"$SERVICE_USER" "$DIR/stats.secret"; chmod 0640 "$DIR/stats.secret"
STATS_SECRET="$(cat "$DIR/stats.secret")"

log "Конфиг $CFG"
cat > "$CFG" <<YAML
# Собрано deploy/setup-hy2.sh. Пользователи — в панели, здесь их нет.
listen: :${HY2_PORT}

tls:
  cert: ${CERT}
  key: ${KEY}

# Клиент шлёт SNI из ссылки; сертификат под него и выпущен, но строгая
# сверка ни к чему — доступ решает панель, а не имя.
sniGuard: disable

# Доступ решает панель, но через скрипт с кэшем и бюджетом обращений:
# свежие ответы отдаются без похода в панель, а пока она недоступна
# (перезапуск, сбой сети), знакомые пароли пускаются по памяти до 6 часов.
auth:
  type: command
  command: ${AUTH_BIN}

# На HTTP/3-зонд без ключа отвечаем как настоящий сайт-донор.
masquerade:
  type: proxy
  proxy:
    url: https://${SNI}
    rewriteHost: true

trafficStats:
  listen: 127.0.0.1:${STATS_PORT}
  secret: ${STATS_SECRET}

quic:
  initStreamReceiveWindow: 8388608
  maxStreamReceiveWindow: 8388608
  initConnReceiveWindow: 20971520
  maxConnReceiveWindow: 20971520
  maxIdleTimeout: 30s
  maxIncomingStreams: 1024
  disablePathMTUDiscovery: false

# Полосу задаёт клиент (Happ присылает свою); без ограничения сверху
# Brutal разгоняется до того, что даёт канал.
ignoreClientBandwidth: false
udpIdleTimeout: 60s
YAML
chown root:"$SERVICE_USER" "$CFG"; chmod 0640 "$CFG"

log "Проверка доступа через панель с кэшем"
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$CACHE_DIR"
echo "PANEL_URL=$PANEL_URL" > "$AUTH_CONF"
chmod 0644 "$AUTH_CONF"
AUTH_SRC="$(dirname "$(readlink -f "$0")")/prosto-hy2-auth.sh"
[[ -f "$AUTH_SRC" ]] || { warn "рядом нет prosto-hy2-auth.sh — положите его в ту же папку"; exit 1; }
install -m 0755 -o root -g root "$AUTH_SRC" "$AUTH_BIN"
ok "$AUTH_BIN, кэш $CACHE_DIR"

log "Прыгающие порты ${HY2_HOP}/udp → ${HY2_PORT}"
printf '%s %s\n' "${HY2_HOP/-/:}" "$HY2_PORT" > "$PORTS_FILE"
cat > "$PORTS_BIN" <<'PORTS'
#!/usr/bin/env bash
# Редирект диапазона прыгающих портов Hysteria2 на его основной порт.
# Идемпотентен: ставит правило, только если его нет. --close снимает.
set -u
FILE=/etc/prosto-hy2-ports.conf
WAN="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"
[[ -f "$FILE" && -n "$WAN" ]] || exit 0
while read -r range target; do
    [[ "$range" =~ ^[0-9]+:[0-9]+$ && "$target" =~ ^[0-9]+$ ]] || continue
    if [[ "${1:-}" == "--close" ]]; then
        while iptables -t nat -C PREROUTING -i "$WAN" -p udp --dport "$range" -j REDIRECT --to-ports "$target" 2>/dev/null; do
            iptables -t nat -D PREROUTING -i "$WAN" -p udp --dport "$range" -j REDIRECT --to-ports "$target"
        done
        continue
    fi
    iptables -t nat -C PREROUTING -i "$WAN" -p udp --dport "$range" -j REDIRECT --to-ports "$target" 2>/dev/null \
        || iptables -t nat -A PREROUTING -i "$WAN" -p udp --dport "$range" -j REDIRECT --to-ports "$target"
done < "$FILE"
exit 0
PORTS
chmod 0755 "$PORTS_BIN"
"$PORTS_BIN"
ok "$(iptables -t nat -S PREROUTING | grep -E "REDIRECT.*--to-ports ${HY2_PORT}\b" | head -1)"

if [[ -f "$EXTRA_FILE" ]] && grep -qE "^${HY2_PORT}(:|$)" "$EXTRA_FILE"; then
    log "Снимаем ${HY2_PORT}/UDP с AmneziaWG"
    tmp_extra="$(mktemp)"
    grep -vE "^${HY2_PORT}(:|$)" "$EXTRA_FILE" > "$tmp_extra" || true
    mv "$tmp_extra" "$EXTRA_FILE"
    systemctl restart prosto-extra-ports 2>/dev/null || true
    ok "теперь запасные AWG: $(tr '\n' ' ' < "$EXTRA_FILE")"
fi

if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "^Status: active"; then
    ufw allow "${HY2_PORT}/udp" comment "Hysteria2" >/dev/null 2>&1 || true
    ufw allow "${HY2_HOP/-/:}/udp" comment "Hysteria2 прыгающие порты" >/dev/null 2>&1 || true
fi

log "Служба prosto-hy2"
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Prosto VPN — Hysteria2
After=network-online.target prosto-extra-ports.service
Wants=network-online.target

[Service]
User=${SERVICE_USER}
Group=${SERVICE_USER}
ExecStartPre=+${PORTS_BIN}
ExecStart=${BIN} server -c ${CFG}
Restart=always
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadOnlyPaths=${DIR} ${TLS_DIR}
ReadWritePaths=${CACHE_DIR}
LimitNOFILE=65536
# На каждое новое соединение hysteria форкает скрипт проверки; шквал
# мусорных рукопожатий без предела съедал бы все процессы узла, а с ним
# xray/awg/агента. 512 — предохранитель для соседей, не защита.
TasksMax=512

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
systemctl enable prosto-hy2 >/dev/null 2>&1 || true
systemctl restart prosto-hy2
sleep 2
if systemctl is-active --quiet prosto-hy2 && ss -lun "sport = :${HY2_PORT}" | grep -q ":${HY2_PORT}"; then
    ok "слушает UDP/${HY2_PORT}"
else
    warn "служба не поднялась:"; journalctl -u prosto-hy2 -n 15 --no-pager
    exit 1
fi

log "Дальше — в панели"
cat <<NEXT
1. У VLESS-точки узла в params добавить
     "hy2": {"port": ${HY2_PORT}, "hop": "${HY2_HOP}", "sni": "${SNI}"$( [[ $REAL_CERT -eq 1 ]] && printf ', "tls": "real"' )}
   — после этого подписка отдаст ссылку hysteria2:// рядом с vless://.
2. Убрать ${HY2_PORT} из запасных портов AWG (servers.alt_ports и
   node_endpoints.alt_ports) и перевести ключи с endpoint_port=${HY2_PORT}
   на другой запасной.
3. Проверить снаружи: журнал панели должен показать POST /api/v1/hy2/auth
   с адреса узла при первом подключении.
NEXT
