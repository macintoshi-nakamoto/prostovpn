#!/usr/bin/env bash
#
# Обход узлов с веб-сервера панели: раз в пять минут проверяет каждый узел
# снаружи и изнутри и пишет владельцу в Telegram, когда узел ломается или
# чинится. Сторож на самом узле (node-watchdog.sh) чинит то, что может;
# этот скрипт нужен ради того, что сторож не увидит: узел выключен, SSH не
# отвечает, Reality снаружи не отвечает, рукопожатий давно нет.
#
# Что проверяет:
#   * SSH до узла (ключ панели /root/.ssh/prosto_nodes);
#   * awg0 поднят; сколько рукопожатий за 15 минут (в отчёт, не в тревогу);
#   * xray работает и слушает порт VLESS; снаружи Reality отвечает
#     сертификатом донора (openssl s_client с SNI);
#   * Hysteria2 работает, слушает свой порт, API /online отвечает;
#   * редиректы запасных портов на месте.
#
# Тревога уходит только при смене состояния (сломалось / починилось), чтобы
# не спамить. Состояние — /var/lib/prosto-probe/<id>.state. Токен и адреса
# владельцев — из /opt/prosto-bot/.env (BOT_TOKEN, ADMIN_IDS).
#
#   sudo bash deploy/node-probe.sh --install   # таймер каждые 5 минут
#   sudo bash deploy/node-probe.sh             # разовый прогон, отчёт в stdout
#   sudo bash deploy/node-probe.sh --status

set -u

DB="${PANEL_DB:-/opt/prosto-vpn/backend/panel.db}"
KEY="${NODE_KEY:-/root/.ssh/prosto_nodes}"
BOT_ENV="${BOT_ENV:-/opt/prosto-bot/.env}"
STATE_DIR=/var/lib/prosto-probe
BIN=/usr/local/bin/prosto-node-probe
TAG=prosto-probe

install_units() {
    [[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
    install -m 0755 "$(readlink -f "$0")" "$BIN"
    install -d -m 0700 "$STATE_DIR"
    cat > /etc/systemd/system/prosto-node-probe.service <<UNIT
[Unit]
Description=Prosto VPN — обход узлов и тревога в Telegram
After=network-online.target

[Service]
Type=oneshot
ExecStart=$BIN
UNIT
    cat > /etc/systemd/system/prosto-node-probe.timer <<UNIT
[Unit]
Description=Prosto VPN — обход узлов каждые 5 минут

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now prosto-node-probe.timer >/dev/null
    echo "обход поставлен: $BIN, таймер prosto-node-probe.timer"
}

case "${1:-}" in
    --install) install_units; exit 0 ;;
    --status)
        systemctl list-timers --no-pager prosto-node-probe.timer | head -2
        for f in "$STATE_DIR"/*.state; do [[ -f "$f" ]] && echo "$(basename "$f" .state): $(cat "$f")"; done
        journalctl -t "$TAG" --no-pager -n 20
        exit 0
        ;;
esac

[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
[[ -f "$DB" ]] || { echo "нет базы панели $DB"; exit 1; }
install -d -m 0700 "$STATE_DIR"

# --- Telegram ----------------------------------------------------------------
BOT_TOKEN=""; ADMIN_IDS=""
if [[ -f "$BOT_ENV" ]]; then
    BOT_TOKEN="$(sed -nE 's/^BOT_TOKEN=["'"'"']?([^"'"'"']+).*/\1/p' "$BOT_ENV" | head -1)"
    ADMIN_IDS="$(sed -nE 's/^ADMIN_IDS=["'"'"']?([^"'"'"']+).*/\1/p' "$BOT_ENV" | head -1)"
fi

tell() {
    local text="$1"
    logger -t "$TAG" -- "$text"
    [[ -n "$BOT_TOKEN" && -n "$ADMIN_IDS" ]] || return 0
    local id
    for id in ${ADMIN_IDS//,/ }; do
        id="${id// /}"
        [[ -n "$id" ]] || continue
        curl -s -m 10 -o /dev/null -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            --data-urlencode "chat_id=${id}" --data-urlencode "text=${text}" || true
    done
}

# --- узлы из панели ------------------------------------------------------------
# id|name|country|host|vless_port|sni|hy2_port|hy2_stats
mapfile -t NODES < <(sqlite3 -separator '|' "$DB" "
select s.id, s.name, coalesce(s.country, s.name), s.host,
       coalesce((select listen_port from node_endpoints e where e.server_id=s.id and e.kind='VLESS' and e.state='ACTIVE' order by e.priority, e.id limit 1), ''),
       coalesce((select json_extract(params,'$.server_names[0]') from node_endpoints e where e.server_id=s.id and e.kind='VLESS' and e.state='ACTIVE' order by e.priority, e.id limit 1), ''),
       coalesce((select json_extract(params,'$.hy2.port') from node_endpoints e where e.server_id=s.id and e.kind='VLESS' and e.state='ACTIVE' and json_extract(params,'$.hy2.port') is not null order by e.priority, e.id limit 1), ''),
       coalesce((select json_extract(params,'$.hy2.stats_port') from node_endpoints e where e.server_id=s.id and e.kind='VLESS' and e.state='ACTIVE' and json_extract(params,'$.hy2.port') is not null order by e.priority, e.id limit 1), '10086')
from servers s where s.is_active=1 and s.provisioning='SSH' order by s.id")

[[ ${#NODES[@]} -gt 0 ]] || { echo "в панели нет активных узлов"; exit 0; }

# Скрипт, который выполняется на узле и печатает key=value.
read -r -d '' REMOTE <<'REMOTE_EOF'
now=$(date +%s)
echo "awg_up=$(awg show awg0 listen-port >/dev/null 2>&1 && echo 1 || echo 0)"
echo "hs15=$(awg show awg0 latest-handshakes 2>/dev/null | awk -v now=$now '$2>0 && now-$2<900{n++} END{print n+0}')"
echo "xray_active=$(systemctl is-active prosto-xray 2>/dev/null)"
echo "xray_listen=$(ss -Hltn "sport = :${VLESS_PORT:-443}" 2>/dev/null | grep -c .)"
if systemctl cat prosto-hy2 >/dev/null 2>&1; then
  echo "hy2_active=$(systemctl is-active prosto-hy2 2>/dev/null)"
  echo "hy2_listen=$(ss -Hlun "sport = :${HY2_PORT:-443}" 2>/dev/null | grep -c .)"
  online=$(curl -s -m 5 -H "Authorization: $(cat /opt/prosto-hy2/stats.secret 2>/dev/null)" "http://127.0.0.1:${HY2_STATS:-10086}/online" 2>/dev/null)
  echo "hy2_api=$([[ "$online" == \{* ]] && echo 1 || echo 0)"
  echo "hy2_online=$(echo "$online" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sum(int(v) for v in d.values()))' 2>/dev/null || echo 0)"
else
  echo "hy2_active=absent"
fi
echo "redirects=$(iptables -t nat -S PREROUTING 2>/dev/null | grep -c REDIRECT)"
echo "load=$(cut -d' ' -f1 /proc/loadavg)"
echo "kernel=$(uname -r)"
echo "pending_kernel=$(ls /boot/vmlinuz-* 2>/dev/null | sed 's#.*/vmlinuz-##' | sort -V | tail -1)"
echo "reboot_required=$([ -f /var/run/reboot-required ] && echo yes || echo no)"
REMOTE_EOF

report=()
for row in "${NODES[@]}"; do
    IFS='|' read -r id name country host vless_port sni hy2_port hy2_stats <<< "$row"
    problems=()
    info=()

    out="$(VLESS_PORT="$vless_port" HY2_PORT="$hy2_port" HY2_STATS="$hy2_stats" \
        ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
        "root@$host" "VLESS_PORT=$vless_port HY2_PORT=$hy2_port HY2_STATS=$hy2_stats bash -s" <<< "$REMOTE" 2>/dev/null)"
    if [[ -z "$out" ]]; then
        problems+=("SSH не отвечает")
    else
        declare -A v=()
        while IFS='=' read -r k val; do [[ -n "$k" ]] && v["$k"]="$val"; done <<< "$out"
        [[ "${v[awg_up]:-0}" == "1" ]] || problems+=("awg0 лежит")
        info+=("рукопожатий за 15 мин: ${v[hs15]:-?}")
        if [[ -n "$vless_port" ]]; then
            [[ "${v[xray_active]:-}" == "active" ]] || problems+=("xray не работает")
            [[ "${v[xray_listen]:-0}" -ge 1 ]] || problems+=("xray не слушает ${vless_port}/tcp")
        fi
        if [[ -n "$hy2_port" && "${v[hy2_active]:-absent}" != "absent" ]]; then
            [[ "${v[hy2_active]}" == "active" ]] || problems+=("Hysteria2 не работает")
            [[ "${v[hy2_listen]:-0}" -ge 1 ]] || problems+=("Hysteria2 не слушает ${hy2_port}/udp")
            [[ "${v[hy2_api]:-0}" == "1" ]] || problems+=("Hysteria2 API не отвечает")
            info+=("Hysteria2 онлайн: ${v[hy2_online]:-0}")
        fi
        [[ "${v[redirects]:-0}" -ge 1 ]] || problems+=("нет редиректов запасных портов")
        info+=("нагрузка ${v[load]:-?}")

        # Обновление ядра ставится само (unattended-upgrades), а перезагрузка
        # остаётся за человеком: один раз напоминаем про каждое новое ядро.
        if [[ "${v[reboot_required]:-no}" == "yes" && -n "${v[pending_kernel]:-}" && "${v[pending_kernel]}" != "${v[kernel]:-}" ]]; then
            kfile="$STATE_DIR/$id.kernel"
            if [[ "$(cat "$kfile" 2>/dev/null)" != "${v[pending_kernel]}" ]]; then
                echo "${v[pending_kernel]}" > "$kfile"
                tell "ℹ️ Узел $country ($host): установлено ядро ${v[pending_kernel]}, работает ${v[kernel]} — нужна перезагрузка. Модуль AmneziaWG под новое ядро собирает DKMS; после ребута всё поднимается само (проверено 02.09.2026)."
            fi
            info+=("ждёт перезагрузки: ${v[pending_kernel]}")
        fi
    fi

    # Снаружи: Reality обязан ответить сертификатом донора.
    if [[ -n "$vless_port" && -n "$sni" ]]; then
        subject="$(timeout 12 openssl s_client -connect "$host:$vless_port" -servername "$sni" -tls1_3 </dev/null 2>/dev/null | sed -nE 's/^subject=.*CN *= *([^,]+).*/\1/p' | head -1)"
        if [[ -z "$subject" ]]; then
            problems+=("Reality снаружи не отвечает на ${vless_port}/tcp")
        elif [[ "$subject" != "$sni" ]]; then
            problems+=("Reality отдал чужой сертификат: $subject")
        fi
    fi

    state_file="$STATE_DIR/$id.state"
    prev="$(cat "$state_file" 2>/dev/null || echo "unknown")"
    if [[ ${#problems[@]} -gt 0 ]]; then
        cur="down"
        line="⚠️ Узел $country ($host): $(printf '%s; ' "${problems[@]}" | sed 's/; $//')"
    else
        cur="ok"
        line="✅ Узел $country ($host): в порядке — $(printf '%s; ' "${info[@]}" | sed 's/; $//')"
    fi
    report+=("$line")
    if [[ "$cur" != "$prev" ]]; then
        echo "$cur" > "$state_file"
        # Первый прогон молчит про здоровые узлы: тревога — только про перемены.
        if [[ "$cur" == "down" || "$prev" != "unknown" ]]; then
            tell "$line"
        fi
    fi
done

printf '%s\n' "${report[@]}"
exit 0
