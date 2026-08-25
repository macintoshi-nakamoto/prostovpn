#!/usr/bin/env bash

set -euo pipefail

AWG_PORT="${AWG_PORT:-51820}"
RULES_FILE="/etc/prosto-extra-ports.conf"
UNIT="/etc/systemd/system/prosto-extra-ports.service"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }
command -v iptables >/dev/null || { warn "нет iptables"; exit 1; }

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
    local target="${1:-$AWG_PORT}"
    while iptables -t nat -S PREROUTING | grep -qE "REDIRECT.*--to-ports ${target}\b"; do
        local rule
        rule="$(iptables -t nat -S PREROUTING | grep -E "REDIRECT.*--to-ports ${target}\b" | head -1)"
        iptables -t nat ${rule/-A/-D}
    done
}

restore_rules() {
    [[ -f "$RULES_FILE" ]] || exit 0
    while IFS=: read -r port target; do
        [[ "$port" =~ ^[0-9]+$ ]] || continue
        [[ "$target" =~ ^[0-9]+$ ]] || target="$AWG_PORT"
        remove_rules "$target"
    done < "$RULES_FILE"
    while IFS=: read -r port target; do
        [[ "$port" =~ ^[0-9]+$ ]] || continue
        [[ "$target" =~ ^[0-9]+$ ]] || target="$AWG_PORT"
        iptables -t nat -A PREROUTING -i "$WAN" -p udp --dport "$port" -j REDIRECT --to-ports "$target"
    done < "$RULES_FILE"
    exit 0
}

case "${1:-}" in
    --restore) restore_rules ;;
    --status) show_status; exit 0 ;;
    --close)
        log "Убираем дополнительные порты цели ${AWG_PORT}"
        remove_rules "$AWG_PORT"
        if [[ -f "$RULES_FILE" ]]; then
            tmp_close="$(mktemp)"
            grep -vE ":${AWG_PORT}$" "$RULES_FILE" > "$tmp_close" || true
            mv "$tmp_close" "$RULES_FILE"
        fi
        if [[ ! -s "$RULES_FILE" ]]; then
            rm -f "$RULES_FILE"
            systemctl disable --now prosto-extra-ports.service 2>/dev/null || true
            rm -f "$UNIT"
            systemctl daemon-reload
        fi
        ok "Порт ${AWG_PORT} не тронут, его дополнительные сняты"
        exit 0
        ;;
esac

PORTS=("$@")
[[ ${#PORTS[@]} -gt 0 ]] || PORTS=(443 2408 8443)
ACCEPTED=()

log "Внешний интерфейс: $WAN, порт AmneziaWG: $AWG_PORT"

for port in "${PORTS[@]}"; do
    if ss -lun "sport = :$port" | grep -q ":$port"; then
        warn "UDP $port уже кем-то занят — пропускаю"
        continue
    fi
    ACCEPTED+=("$port")
done
[[ ${#ACCEPTED[@]} -gt 0 ]] || { warn "нечего добавлять"; exit 1; }

remove_rules
for port in "${ACCEPTED[@]}"; do
    iptables -t nat -A PREROUTING -i "$WAN" -p udp --dport "$port" -j REDIRECT --to-ports "$AWG_PORT"
    ok "UDP $port → $AWG_PORT"
done

if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "^Status: active"; then
    ufw allow "${AWG_PORT}/udp" >/dev/null 2>&1 || true
fi

touch "$RULES_FILE"
tmp_rules="$(mktemp)"
grep -vE ":${AWG_PORT}\$" "$RULES_FILE" > "$tmp_rules" || true
for port in "${ACCEPTED[@]}"; do
    printf '%s:%s\n' "$port" "$AWG_PORT" >> "$tmp_rules"
done
sort -u "$tmp_rules" > "$RULES_FILE"
rm -f "$tmp_rules"

cat > "$UNIT" <<UNITEOF
[Unit]
Description=Prosto VPN — дополнительные UDP-порты для AmneziaWG
After=network-online.target awg-quick@awg0.service
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
