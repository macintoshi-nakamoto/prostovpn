#!/usr/bin/env bash
#
# Открывает SSH на дополнительном порту для одного конкретного адреса.
#
# Нужен, когда провайдер режет исходящий порт 22: высокие порты у него
# обычно открыты, и достаточно повесить sshd ещё и на такой порт.
#
#   sudo bash deploy/open-remote-access.sh 89.125.138.227
#   sudo bash deploy/open-remote-access.sh 89.125.138.227 22222
#
# Порт 22 остаётся как был — доступ через веб-консоль хостера не теряется.
# Закрыть обратно: sudo bash deploy/open-remote-access.sh --close

set -euo pipefail

PORT="${2:-22222}"
DROPIN="/etc/systemd/system/ssh.socket.d/extra-port.conf"
SSHD_DROPIN="/etc/ssh/sshd_config.d/99-extra-port.conf"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0 ..."; exit 1; }

# --- Закрыть доступ ---------------------------------------------------------

if [[ "${1:-}" == "--close" ]]; then
    log "Убираем дополнительный порт"
    rm -f "$DROPIN" "$SSHD_DROPIN"
    systemctl daemon-reload
    systemctl restart ssh.socket 2>/dev/null || systemctl restart ssh
    # Снимаем только правила нашего доп. порта, кем бы они ни были заведены.
    # Номер берём из строки, где порт стоит сразу после «[ N]», то есть в
    # колонке To: иначе под удаление попадёт первое попавшееся правило —
    # 22/tcp, 443/tcp, 51820/udp — и сервер останется без доступа вообще.
    # Номера пересчитываются после каждого удаления, поэтому список
    # перечитываем заново на каждом шаге.
    if command -v ufw >/dev/null && ufw status >/dev/null 2>&1; then
        while :; do
            num=$(ufw status numbered 2>/dev/null \
                  | grep -E "^\[[ 0-9]+\][[:space:]]+${PORT}(/(tcp|udp))?([[:space:]]|$)" \
                  | head -1 | grep -oE '^\[[ 0-9]+\]' | tr -d '[] ' || true)
            [[ -n "$num" ]] || break
            # `yes` уходит по SIGPIPE (141), и без «|| true» pipefail с set -e
            # уронят скрипт сразу после первого удаления.
            yes | ufw delete "$num" >/dev/null || true
        done
    fi
    warn "Дополнительный доступ закрыт. Порт 22 не тронут."
    exit 0
fi

ALLOW_IP="${1:-}"
[[ -n "$ALLOW_IP" ]] || { warn "укажите адрес: sudo bash $0 89.125.138.227"; exit 1; }

# --- 1. Второй порт для sshd ------------------------------------------------

# В Ubuntu 24.04 sshd поднимается через сокет systemd, и директива Port в
# sshd_config при этом не действует — порт задаётся сокетом. Поддерживаем
# оба случая, потому что на 22.04 всё наоборот.
if systemctl is-enabled ssh.socket >/dev/null 2>&1; then
    log "sshd работает через systemd-сокет — правим сокет"
    mkdir -p "$(dirname "$DROPIN")"
    cat > "$DROPIN" <<EOF
[Socket]
# Пустое значение сбрасывает список из основного юнита, иначе порты
# накапливаются и 22 продублируется.
ListenStream=
ListenStream=22
ListenStream=$PORT
EOF
    systemctl daemon-reload
    systemctl restart ssh.socket
else
    log "sshd работает как обычная служба — правим sshd_config"
    mkdir -p "$(dirname "$SSHD_DROPIN")"
    printf 'Port 22\nPort %s\n' "$PORT" > "$SSHD_DROPIN"
    sshd -t || { warn "конфиг sshd не проходит проверку, откатываем"; rm -f "$SSHD_DROPIN"; exit 1; }
    systemctl restart ssh
fi

# --- 2. Файрвол ------------------------------------------------------------

log "Открываем порт $PORT только для $ALLOW_IP"
if command -v ufw >/dev/null; then
    # Если ufw ещё не включён, сначала разрешаем то, без чего потеряем сервер.
    if ! ufw status | grep -q "Status: active"; then
        ufw allow 22/tcp    >/dev/null
        ufw allow 80/tcp    >/dev/null
        ufw allow 443/tcp   >/dev/null
        ufw allow 51820/udp >/dev/null
    fi
    ufw allow from "$ALLOW_IP" to any port "$PORT" proto tcp >/dev/null
    ufw --force enable >/dev/null
else
    warn "ufw не установлен — порт $PORT открыт всему интернету."
    warn "Поставьте: apt-get install -y ufw, затем запустите скрипт заново."
fi

# --- 3. Проверка ------------------------------------------------------------

log "Проверяем"
sleep 1
if ss -lntp | grep -q ":$PORT "; then
    echo "  sshd слушает порт $PORT"
else
    warn "порт $PORT не слушается — смотрите: journalctl -u ssh -n 30"
    exit 1
fi

PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')"

cat <<EOF

  Готово.

  Адрес:     $PUBLIC_IP
  Порт:      $PORT
  Открыт:    только для $ALLOW_IP
  Порт 22:   не тронут

  Проверка со стороны клиента:
      ssh -p $PORT root@$PUBLIC_IP

  Закрыть обратно, когда всё будет сделано:
      sudo bash $0 --close

EOF

warn "Пока порт открыт, вход по паролю root доступен с адреса $ALLOW_IP."
warn "После настройки закройте порт и смените пароль: passwd root"
