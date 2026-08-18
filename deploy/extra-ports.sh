#!/usr/bin/env bash
#
# Дополнительные UDP-порты для AmneziaWG на том же узле.
#
# Зачем. Узел слушает 51820 — канонический порт WireGuard. Часть операторов
# его просто не пропускает: приложение исправно, сервер исправен, пир заведён,
# а рукопожатия нет ни одного и человек видит вечное «подключение». В базе это
# выглядит как ключ, созданный при входе, с last_handshake_at = NULL навсегда.
#
# Что делает скрипт. Оставляет 51820 как есть и добавляет правила, которые
# заворачивают на него другие порты. Интерфейс по-прежнему один, пиры те же,
# ключи менять не нужно — снаружи узел просто начинает отвечать ещё на
# нескольких портах.
#
# Почему именно эти порты:
#   443  — неотличим от QUIC/HTTP3. Режут в последнюю очередь: заблокировать
#          его целиком значит сломать половину интернета. Занят ли он? TCP/443
#          держит nginx, но это TCP — UDP свободен, QUIC мы не раздаём.
#   2408 — порт Cloudflare WARP. Открыт почти везде по той же причине.
#   8443 — запасной «альтернативный HTTPS», часто открыт.
#
# После скрипта пропишите порты в панели: Серверы → узел → «Запасные порты».
# Оттуда они уезжают приложению (поле alt_ports в /api/v1/servers), и клиент
# начинает их перебирать; тем, у кого рукопожатия не было ни разу, панель сама
# предлагает следующий порт при каждом опросе.
#
#   sudo bash deploy/extra-ports.sh              # добавить 443, 2408, 8443
#   sudo bash deploy/extra-ports.sh 443 2408     # свой список
#   sudo bash deploy/extra-ports.sh --status     # что сейчас настроено
#   sudo bash deploy/extra-ports.sh --close      # убрать всё, что добавили

set -euo pipefail

AWG_PORT="${AWG_PORT:-51820}"
RULES_FILE="/etc/prosto-extra-ports.conf"
UNIT="/etc/systemd/system/prosto-extra-ports.service"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }
command -v iptables >/dev/null || { warn "нет iptables"; exit 1; }

# Внешний интерфейс: правила вешаем только на него, иначе под перенаправление
# попадёт и трафик внутри туннеля (awg0), где эти порты значат совсем другое.
WAN="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"
[[ -n "$WAN" ]] || { warn "не удалось определить внешний интерфейс"; exit 1; }

show_status() {
    log "Правила перенаправления сейчас"
    iptables -t nat -S PREROUTING | grep -E "REDIRECT.*--to-ports ${AWG_PORT}" || echo "   (нет)"
    log "Что слушает узел"
    ss -lunp | awk 'NR==1 || /:'"${AWG_PORT}"'/'
    if [[ -f "$RULES_FILE" ]]; then
        log "Сохранённый список портов"
        cat "$RULES_FILE"
    fi
}

remove_rules() {
    # Снимаем ровно свои правила: те, что ведут на порт AmneziaWG.
    while iptables -t nat -S PREROUTING | grep -qE "REDIRECT.*--to-ports ${AWG_PORT}"; do
        local rule
        rule="$(iptables -t nat -S PREROUTING | grep -E "REDIRECT.*--to-ports ${AWG_PORT}" | head -1)"
        # shellcheck disable=SC2086
        iptables -t nat ${rule/-A/-D}
    done
}

restore_rules() {
    # Восстановление после перезагрузки: список берём из файла, а не из
    # аргументов — юнит запускается без них.
    [[ -f "$RULES_FILE" ]] || exit 0
    remove_rules
    while read -r port; do
        [[ "$port" =~ ^[0-9]+$ ]] || continue
        iptables -t nat -A PREROUTING -i "$WAN" -p udp --dport "$port" -j REDIRECT --to-ports "$AWG_PORT"
    done < "$RULES_FILE"
    exit 0
}

case "${1:-}" in
    --restore) restore_rules ;;
    --status) show_status; exit 0 ;;
    --close)
        log "Убираем дополнительные порты"
        remove_rules
        rm -f "$RULES_FILE"
        systemctl disable --now prosto-extra-ports.service 2>/dev/null || true
        rm -f "$UNIT"
        systemctl daemon-reload
        ok "Порт ${AWG_PORT} не тронут, дополнительные сняты"
        exit 0
        ;;
esac

PORTS=("$@")
[[ ${#PORTS[@]} -gt 0 ]] || PORTS=(443 2408 8443)
ACCEPTED=()

log "Внешний интерфейс: $WAN, порт AmneziaWG: $AWG_PORT"

# --- проверка занятости ------------------------------------------------------
#
# Занятый UDP-порт молча съест перенаправление: правило встанет, а пакеты
# заберёт чужая служба. Лучше отказаться сразу, чем потом искать, почему
# «порт добавили, а не работает».
for port in "${PORTS[@]}"; do
    if ss -lun "sport = :$port" | grep -q ":$port"; then
        warn "UDP $port уже кем-то занят — пропускаю"
        continue
    fi
    ACCEPTED+=("$port")
done
[[ ${#ACCEPTED[@]} -gt 0 ]] || { warn "нечего добавлять"; exit 1; }

# --- правила -----------------------------------------------------------------
remove_rules
for port in "${ACCEPTED[@]}"; do
    iptables -t nat -A PREROUTING -i "$WAN" -p udp --dport "$port" -j REDIRECT --to-ports "$AWG_PORT"
    ok "UDP $port → $AWG_PORT"
done

# Пропускаем сами пакеты через фильтр: у REDIRECT назначение меняется ДО
# INPUT, поэтому разрешать надо порт AmneziaWG, а не исходный. Обычно он уже
# открыт — проверяем на всякий случай, молча.
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "^Status: active"; then
    ufw allow "${AWG_PORT}/udp" >/dev/null 2>&1 || true
fi

printf '%s\n' "${ACCEPTED[@]}" > "$RULES_FILE"

# --- переживание перезагрузки -------------------------------------------------
#
# iptables-persistent ставить не хотим: он сохраняет ВЕСЬ набор правил,
# включая чужие, и однажды восстановит то, что кто-то намеренно убрал.
# Свой маленький юнит восстанавливает ровно наши правила и ничего больше.
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Prosto VPN — дополнительные UDP-порты для AmneziaWG
After=network-online.target amnezia-awg@awg0.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/env bash $(readlink -f "$0") --restore

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
systemctl enable prosto-extra-ports.service >/dev/null 2>&1 || true

show_status

log "Дальше — руками"
cat <<'NEXT'
1. В панели: Серверы → узел → «Запасные порты» → 443,2408,8443 → Сохранить.
   Оттуда список уезжает приложению и включает подбор порта тем,
   у кого рукопожатия не было ни разу.

2. Проверить снаружи, что порт действительно доходит:

     sudo tcpdump -ni any udp port 51820 -c 5

   и в это же время подключиться с телефона. Пакеты должны появиться
   даже когда клиент стучится на 443 — на узел они приходят уже с
   подменённым портом.
NEXT
