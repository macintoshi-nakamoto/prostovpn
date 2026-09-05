#!/usr/bin/env bash
#
# Сайт и панель за Cloudflare: настоящий адрес человека и запертый вход.
#
# Что делает:
#   * /etc/nginx/conf.d/cloudflare-realip.conf — nginx верит заголовку
#     CF-Connecting-IP только с адресов Cloudflare: лимиты, fail2ban и
#     панель видят человека, а не край Cloudflare;
#   * ufw: 80 и 443 открыты только с адресов Cloudflare — иначе прокси не
#     защита, а декорация: бить можно напрямую в наш IP, он давно известен.
#
# Диапазоны Cloudflare меняются редко; таймер обновляет их раз в неделю.
#
#   sudo bash cloudflare-origin.sh --nginx-only  # шаг 1: только real_ip, до переключения DNS
#   sudo bash cloudflare-origin.sh               # шаг 2: и ufw тоже (и обновить диапазоны)
#   sudo bash cloudflare-origin.sh --open        # откат: 80/443 снова для всех
set -euo pipefail

REALIP=/etc/nginx/conf.d/cloudflare-realip.conf
CACHE=/var/lib/prosto-cloudflare
BIN=/usr/local/bin/prosto-cloudflare-origin

[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
install -d -m 0755 "$CACHE"

if [[ "${1:-}" == "--open" ]]; then
    # Сначала открываем для всех, потом убираем правила Cloudflare — по тем
    # же диапазонам, что добавляли (кэш), остатки добираем по номерам.
    ufw allow 80/tcp comment 'HTTP (редирект и ACME)' >/dev/null
    ufw allow 443/tcp comment 'HTTPS: сайт, кабинет, API' >/dev/null
    for net in $(cat "$CACHE/ips-v4" "$CACHE/ips-v6" 2>/dev/null); do
        ufw --force delete allow from "$net" to any port 443 proto tcp >/dev/null 2>&1 || true
        ufw --force delete allow from "$net" to any port 80 proto tcp >/dev/null 2>&1 || true
    done
    for rule in $(ufw status numbered | grep -E "Cloudflare" | sed -E 's/^\[ *([0-9]+)\].*/\1/' | sort -rn); do
        yes | ufw delete "$rule" >/dev/null
    done
    echo "80/443 снова открыты для всех; правил Cloudflare осталось: $(ufw status | grep -c Cloudflare)"
    exit 0
fi

echo "== диапазоны Cloudflare"
V4=$(curl -fsSL -m 30 https://www.cloudflare.com/ips-v4)
V6=$(curl -fsSL -m 30 https://www.cloudflare.com/ips-v6)
[[ $(echo "$V4" | grep -c '/') -ge 10 && $(echo "$V6" | grep -c '/') -ge 5 ]] || { echo "список диапазонов подозрительно короткий — ничего не трогаю"; exit 1; }
printf '%s\n' "$V4" > "$CACHE/ips-v4"
printf '%s\n' "$V6" > "$CACHE/ips-v6"
echo "  v4: $(echo "$V4" | wc -l), v6: $(echo "$V6" | wc -l)"

echo "== nginx: настоящий адрес из CF-Connecting-IP"
{
    echo "# Сгенерировано $BIN — не править руками."
    for net in $V4 $V6; do echo "set_real_ip_from $net;"; done
    echo "real_ip_header CF-Connecting-IP;"
} > "$REALIP"
nginx -t >/dev/null && systemctl reload nginx
echo "  nginx перезагружен"

if [[ "${1:-}" == "--nginx-only" ]]; then
    echo "ufw не трогаем (--nginx-only): сначала переключить DNS, потом закрывать вход"
    exit 0
fi

echo "== ufw: 80/443 только с Cloudflare"
# Сначала добавляем новые правила, потом снимаем общие: сайт не должен
# остаться закрытым даже на секунду между этими шагами.
for net in $V4 $V6; do
    ufw allow from "$net" to any port 443 proto tcp comment 'Cloudflare' >/dev/null
    ufw allow from "$net" to any port 80 proto tcp comment 'Cloudflare' >/dev/null
done
# Общие правила снимаем по их же тексту, а не по номерам строк: номера
# плывут после каждого удаления, а по тексту ufw убирает v4 и v6 разом.
# 05.09.2026 цикл по номерам ничего не нашёл, и вход остался открытым —
# заметили только проверкой напрямую в IP.
ufw --force delete allow 80/tcp >/dev/null 2>&1 || true
ufw --force delete allow 443/tcp >/dev/null 2>&1 || true
echo "  правил Cloudflare: $(ufw status | grep -c Cloudflare)"
if ufw status | grep -qE "^(80|443)/tcp( \(v6\))? +ALLOW +Anywhere"; then
    echo "  ВНИМАНИЕ: общее правило на 80/443 осталось — смотреть ufw status numbered"
    exit 1
fi

if [[ "$(readlink -f "$0")" != "$BIN" ]]; then
    install -m 0755 "$(readlink -f "$0")" "$BIN"
    cat > /etc/systemd/system/prosto-cloudflare-origin.service <<UNIT
[Unit]
Description=Prosto VPN — обновить диапазоны Cloudflare (nginx real_ip, ufw)
[Service]
Type=oneshot
ExecStart=$BIN
UNIT
    cat > /etc/systemd/system/prosto-cloudflare-origin.timer <<UNIT
[Unit]
Description=Prosto VPN — диапазоны Cloudflare раз в неделю
[Timer]
OnCalendar=Mon *-*-* 04:40:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now prosto-cloudflare-origin.timer >/dev/null
fi
echo "готово"
