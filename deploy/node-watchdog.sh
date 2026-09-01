#!/usr/bin/env bash
#
# Сторож узла ProstoVPN. Раз в минуту проверяет, что всё, от чего зависит
# связь, на месте, и молча возвращает то, что пропало:
#
#   * интерфейс awg0 поднят и слушает; MTU совпадает с конфигом;
#   * форвардинг включён;
#   * правила из PostUp конфига awg0 (FORWARD, MASQUERADE, клампинг MSS)
#     стоят — ufw при перезапуске их стирает;
#   * редиректы запасных UDP-портов на порт awg (/etc/prosto-extra-ports.conf);
#   * xray жив и слушает каждый порт VLESS из своего конфига;
#   * на внешнем интерфейсе не fq: он считает туннель одним потоком и режет
#     его по flow_limit — так на одном узле потерялось 415 тысяч пакетов.
#
# Чинит только то, что явно сломано, и пишет в журнал (logger -t prosto-watchdog)
# лишь когда что-то починил. Проверять: journalctl -t prosto-watchdog.
#
#   sudo bash deploy/node-watchdog.sh --install   # поставить и включить таймер
#   sudo bash deploy/node-watchdog.sh             # разовый прогон
#   sudo bash deploy/node-watchdog.sh --status

set -u

AWG_IF="${AWG_IF:-awg0}"
AWG_CONF="/etc/amnezia/amneziawg/${AWG_IF}.conf"
PORTS_FILE="/etc/prosto-extra-ports.conf"
XRAY_UNIT="prosto-xray"
XRAY_CONFIG="/opt/prosto-xray/config.json"
BIN="/usr/local/bin/prosto-node-watchdog"
TAG="prosto-watchdog"

say() { logger -t "$TAG" -- "$*"; echo "$*"; }

install_units() {
    [[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
    install -m 0755 "$(readlink -f "$0")" "$BIN"
    cat > /etc/systemd/system/prosto-node-watchdog.service <<UNIT
[Unit]
Description=Prosto VPN — сторож узла (awg, редиректы, xray)
After=network-online.target awg-quick@${AWG_IF}.service prosto-extra-ports.service prosto-xray.service

[Service]
Type=oneshot
ExecStart=$BIN
UNIT
    cat > /etc/systemd/system/prosto-node-watchdog.timer <<UNIT
[Unit]
Description=Prosto VPN — сторож узла, раз в минуту

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now prosto-node-watchdog.timer >/dev/null
    echo "сторож поставлен: $BIN, таймер prosto-node-watchdog.timer"
    systemctl list-timers --no-pager prosto-node-watchdog.timer | head -2
}

case "${1:-}" in
    --install) install_units; exit 0 ;;
    --status)
        systemctl list-timers --no-pager prosto-node-watchdog.timer | head -2
        journalctl -t "$TAG" --no-pager -n 20
        exit 0
        ;;
esac

[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }

fixed=0
WAN="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"

# --- awg0 -------------------------------------------------------------------
if [[ -f "$AWG_CONF" ]]; then
    if ! awg show "$AWG_IF" listen-port >/dev/null 2>&1; then
        say "$AWG_IF не отвечает — поднимаем awg-quick@$AWG_IF"
        systemctl restart "awg-quick@$AWG_IF" && fixed=1
        # После подъёма редиректы и правила ставятся ниже по списку.
        sleep 2
    fi

    want_mtu="$(awk -F= '/^[[:space:]]*MTU[[:space:]]*=/{gsub(/[[:space:]]/,"",$2); print $2; exit}' "$AWG_CONF")"
    have_mtu="$(cat "/sys/class/net/$AWG_IF/mtu" 2>/dev/null || true)"
    if [[ -n "$want_mtu" && -n "$have_mtu" && "$want_mtu" != "$have_mtu" ]]; then
        say "MTU $AWG_IF $have_mtu вместо $want_mtu — ставим"
        ip link set "$AWG_IF" mtu "$want_mtu" && fixed=1
    fi

    # Правила из PostUp: каждое «-A» проверяем через «-C» и ставим, если нет.
    postup="$(sed -nE 's/^[[:space:]]*PostUp[[:space:]]*=[[:space:]]*//p' "$AWG_CONF" | head -1)"
    if [[ -n "$postup" ]]; then
        IFS=';' read -ra cmds <<< "$postup"
        for cmd in "${cmds[@]}"; do
            cmd="${cmd//%i/$AWG_IF}"
            cmd="$(echo "$cmd" | xargs 2>/dev/null || true)"
            [[ "$cmd" == iptables\ * ]] || continue
            [[ "$cmd" == *" -A "* ]] || continue
            check="${cmd/ -A / -C }"
            # shellcheck disable=SC2086
            if ! $check >/dev/null 2>&1; then
                # shellcheck disable=SC2086
                if $cmd >/dev/null 2>&1; then
                    say "восстановлено правило: $cmd"
                    fixed=1
                else
                    say "не удалось поставить правило: $cmd"
                fi
            fi
        done
    fi
fi

# --- форвардинг -------------------------------------------------------------
if [[ "$(sysctl -n net.ipv4.ip_forward 2>/dev/null)" != "1" ]]; then
    say "ip_forward выключен — включаем"
    sysctl -w net.ipv4.ip_forward=1 >/dev/null && fixed=1
fi

# --- редиректы запасных портов ----------------------------------------------
if [[ -f "$PORTS_FILE" && -n "$WAN" ]]; then
    awg_port="$(awg show "$AWG_IF" listen-port 2>/dev/null || echo 51820)"
    while IFS=: read -r port target; do
        [[ "$port" =~ ^[0-9]+$ ]] || continue
        [[ "$target" =~ ^[0-9]+$ ]] || target="$awg_port"
        if ! iptables -t nat -C PREROUTING -i "$WAN" -p udp --dport "$port" -j REDIRECT --to-ports "$target" 2>/dev/null; then
            if iptables -t nat -A PREROUTING -i "$WAN" -p udp --dport "$port" -j REDIRECT --to-ports "$target"; then
                say "восстановлен редирект UDP $port → $target"
                fixed=1
            fi
        fi
    done < "$PORTS_FILE"
fi

# --- xray -------------------------------------------------------------------
if [[ -f "$XRAY_CONFIG" ]] && systemctl cat "$XRAY_UNIT" >/dev/null 2>&1; then
    if ! systemctl is-active --quiet "$XRAY_UNIT"; then
        say "$XRAY_UNIT не работает — перезапускаем"
        systemctl restart "$XRAY_UNIT" && fixed=1
    else
        ports="$(python3 - "$XRAY_CONFIG" <<'PY' 2>/dev/null
import json, sys
cfg = json.load(open(sys.argv[1]))
print(" ".join(str(i["port"]) for i in cfg.get("inbounds", []) if i.get("protocol") == "vless" and isinstance(i.get("port"), int)))
PY
)"
        for p in $ports; do
            if ! ss -Hltn "sport = :$p" 2>/dev/null | grep -q .; then
                say "xray не слушает $p/tcp — перезапускаем"
                systemctl restart "$XRAY_UNIT" && fixed=1
                break
            fi
        done
    fi
fi

# --- очередь на внешнем интерфейсе ------------------------------------------
if [[ -n "$WAN" ]] && tc qdisc show dev "$WAN" 2>/dev/null | head -1 | grep -qE '^qdisc (fq|pfifo_fast) '; then
    say "на $WAN очередь $(tc qdisc show dev "$WAN" | awk 'NR==1{print $2}') — ставим fq_codel"
    tc qdisc replace dev "$WAN" root fq_codel && fixed=1
fi

exit 0
