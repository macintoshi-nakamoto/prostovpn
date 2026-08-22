#!/usr/bin/env bash
#
# Второй протокол на узле: VLESS + XTLS-Reality через xray.
#
# Зачем он нужен. AmneziaWG — это UDP, и там, где UDP режут целиком или
# пропускают только по белому списку, он не поднимается вовсе. Reality решает
# другую задачу: соединение неотличимо от обычного HTTPS к крупному чужому
# сайту, потому что им и является — на чужой ClientHello узел молча проксирует
# запрос настоящему донору и отдаёт его настоящий сертификат.
#
# Приоритет у него НИЖЕ awg: AWG быстрее (UDP против TCP-в-TCP) и дешевле по
# батарее. VLESS — запасной путь.
#
# Ставим вручную закреплённой версией, а не официальным install-release.sh:
# тот трогает systemd, logrotate и cron на живой машине, где рядом работает
# ещё и второй продукт.
#
#   sudo bash deploy/setup-xray.sh              # поставить
#   sudo bash deploy/setup-xray.sh --status     # что сейчас
#   sudo bash deploy/setup-xray.sh --remove     # снять целиком

set -euo pipefail

XRAY_VERSION="${XRAY_VERSION:-v25.1.30}"
XRAY_DIR="/opt/prosto-xray"
XRAY_BIN="$XRAY_DIR/xray"
XRAY_CONFIG="$XRAY_DIR/config.json"
UNIT="/etc/systemd/system/prosto-xray.service"
SERVICE_USER="prosto-xray"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }

case "${1:-}" in
    --status)
        log "Служба"
        systemctl status prosto-xray --no-pager 2>/dev/null | head -12 || echo "   (не установлена)"
        log "Что слушает"
        ss -tlnp 2>/dev/null | grep -E "xray" || echo "   (ничего)"
        log "Версия"
        [[ -x "$XRAY_BIN" ]] && "$XRAY_BIN" version | head -2 || echo "   (нет бинарника)"
        exit 0
        ;;
    --remove)
        log "Снимаем xray"
        systemctl disable --now prosto-xray 2>/dev/null || true
        rm -f "$UNIT"
        systemctl daemon-reload
        rm -rf "$XRAY_DIR"
        userdel "$SERVICE_USER" 2>/dev/null || true
        ok "снято, AmneziaWG не тронут"
        exit 0
        ;;
esac

# --- пользователь и каталог ---------------------------------------------------
#
# Отдельный системный пользователь без оболочки и без домашнего каталога.
# Конфиг читает только он: в конфиге приватный ключ Reality и UUID всех
# клиентов, а на этой машине есть ещё и докер соседнего продукта.
id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -m 0750 -o root -g "$SERVICE_USER" "$XRAY_DIR"

# --- бинарник -----------------------------------------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ASSET="Xray-linux-64.zip" ;;
    aarch64) ASSET="Xray-linux-arm64-v8a.zip" ;;
    *) warn "неизвестная архитектура $ARCH"; exit 1 ;;
esac

if [[ -x "$XRAY_BIN" ]] && "$XRAY_BIN" version 2>/dev/null | grep -q "${XRAY_VERSION#v}"; then
    ok "xray ${XRAY_VERSION} уже стоит"
else
    log "Ставим xray ${XRAY_VERSION}"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    base="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}"
    curl -fsSL "$base/$ASSET" -o "$tmp/xray.zip"
    curl -fsSL "$base/$ASSET.dgst" -o "$tmp/xray.dgst" || true

    # Сверяем контрольную сумму, если издатель её опубликовал: скачанный по
    # сети бинарник, который потом ходит в интернет от нашего имени, обязан
    # быть тем, что мы думаем.
    if [[ -s "$tmp/xray.dgst" ]]; then
        want="$(grep -iE '^sha256' "$tmp/xray.dgst" | head -1 | awk '{print $NF}')"
        have="$(sha256sum "$tmp/xray.zip" | awk '{print $1}')"
        if [[ -n "$want" && "$want" != "$have" ]]; then
            warn "контрольная сумма не сошлась: ждали $want, получили $have"
            exit 1
        fi
        ok "sha256 сверен"
    else
        warn "издатель не отдал .dgst — сумма не проверена"
    fi

    unzip -o -q "$tmp/xray.zip" -d "$tmp"
    install -m 0755 -o root -g root "$tmp/xray" "$XRAY_BIN"
    # Геобазы нужны правилам маршрутизации: без них конфиг с geoip: не
    # загрузится и демон не поднимется вовсе.
    install -m 0644 -o root -g root "$tmp/geoip.dat" "$XRAY_DIR/geoip.dat" 2>/dev/null || true
    install -m 0644 -o root -g root "$tmp/geosite.dat" "$XRAY_DIR/geosite.dat" 2>/dev/null || true
    ok "$($XRAY_BIN version | head -1)"
fi

# --- заготовка конфига --------------------------------------------------------
#
# Настоящий конфиг пишет панель (services/xray.py): она единственный источник
# правды о клиентах и точках входа. Здесь — минимум, чтобы служба поднялась и
# было куда писать.
if [[ ! -f "$XRAY_CONFIG" ]]; then
    cat > "$XRAY_CONFIG" <<'JSON'
{
  "log": {"loglevel": "warning"},
  "api": {"tag": "api", "services": ["HandlerService", "StatsService"]},
  "stats": {},
  "policy": {"levels": {"0": {"statsUserUplink": true, "statsUserDownlink": true}}},
  "inbounds": [
    {"tag": "api-in", "listen": "127.0.0.1", "port": 10085,
     "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"}}
  ],
  "outbounds": [
    {"tag": "direct", "protocol": "freedom"},
    {"tag": "block", "protocol": "blackhole"}
  ],
  "routing": {"domainStrategy": "IPIfNonMatch",
    "rules": [{"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"}]}
}
JSON
fi
chown root:"$SERVICE_USER" "$XRAY_CONFIG"
chmod 0640 "$XRAY_CONFIG"
touch "$XRAY_DIR/.config.lock"
chown root:"$SERVICE_USER" "$XRAY_DIR/.config.lock"
chmod 0660 "$XRAY_DIR/.config.lock"

# --- служба -------------------------------------------------------------------
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Prosto VPN — xray (VLESS + Reality)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
# Привилегия нужна только чтобы слушать порт ниже 1024, если точку входа
# поставят на 443. На свободном порту она не задействуется.
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=$XRAY_DIR
Environment=XRAY_LOCATION_ASSET=$XRAY_DIR
ExecStart=$XRAY_BIN run -config $XRAY_CONFIG
# ExecReload намеренно НЕ объявлен: xray-core не подписан на SIGHUP, и такой
# «reload» просто убивал бы процесс — то есть вёл бы себя как перезапуск, но
# выглядел бы как мягкое перечитывание. Панель применяет конфиг явным restart.
Restart=always
RestartSec=3
# Демон роняют ответы сети и битый конфиг; без этого systemd пометил бы службу
# failed и перестал поднимать — ровно та беда, что была у телеграм-бота.
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable --now prosto-xray
sleep 1

if systemctl is-active --quiet prosto-xray; then
    ok "служба поднята"
else
    warn "служба не поднялась:"
    journalctl -u prosto-xray -n 20 --no-pager
    exit 1
fi

log "Готово"
echo "   Дальше — в панели: Серверы → узел → «Точки входа» → добавить VLESS."
echo "   Порт выбирайте свободный (2053), донор — крупный чужой сайт с TLS 1.3."
echo "   Панель сама запишет конфиг и перечитает демон."
