#!/usr/bin/env bash
#
# Зеркало боевых конфигов веб-сервера 103.114.43.45 и способ их применить.
#
# Файлы в этом каталоге — РОВНО то, что лежит на сервере (сняты 06.09.2026;
# до этого репозиторий хранил шаблоны и старый вариант с reality-443, а живой
# nginx правился на месте и разошёлся с ними). Правило простое: меняем здесь,
# применяем этим скриптом, коммитим. Скрипт кладёт файлы на место с бэкапом,
# проверяет nginx -t и fail2ban-client -t, при ошибке возвращает бэкап.
#
#   sudo bash apply.sh            # применить всё, что отличается
#   sudo bash apply.sh --check    # только показать, что отличается
#
# Не трогает: /etc/nginx/conf.d/cloudflare-realip.conf (его пишет
# prosto-cloudflare-origin по актуальным диапазонам Cloudflare).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%Y%m%d-%H%M%S)
BK=/root/live-conf.before-$STAMP

declare -A MAP=(
    ["nginx/nginx.conf"]="/etc/nginx/nginx.conf"
    ["nginx/sites-available/prosto-panel"]="/etc/nginx/sites-available/prosto-panel"
    ["nginx/sites-available/sub-prostovpn"]="/etc/nginx/sites-available/sub-prostovpn"
    ["nginx/sites-available/rusvpn-prostovpn"]="/etc/nginx/sites-available/rusvpn-prostovpn"
    ["nginx/conf.d/prosto-hardening.conf"]="/etc/nginx/conf.d/prosto-hardening.conf"
    ["nginx/conf.d/prosto-limits.conf"]="/etc/nginx/conf.d/prosto-limits.conf"
    ["fail2ban/jail.local"]="/etc/fail2ban/jail.local"
    ["fail2ban/filter.d/nginx-bad-request.conf"]="/etc/fail2ban/filter.d/nginx-bad-request.conf"
    ["fail2ban/filter.d/nginx-panel-auth.conf"]="/etc/fail2ban/filter.d/nginx-panel-auth.conf"
    ["systemd/prosto-panel.service"]="/etc/systemd/system/prosto-panel.service"
    ["systemd/prosto-bot.service"]="/etc/systemd/system/prosto-bot.service"
)
# Файлы, которых на сервере может ещё не быть (новые действия fail2ban и т.п.),
# добавляются в MAP выше — скрипт одинаково кладёт и новые, и изменённые.
for f in "$HERE"/fail2ban/action.d/*.conf; do
    [[ -f "$f" ]] && MAP["fail2ban/action.d/$(basename "$f")"]="/etc/fail2ban/action.d/$(basename "$f")"
done

changed=()
for rel in "${!MAP[@]}"; do
    src="$HERE/$rel"; dst="${MAP[$rel]}"
    [[ -f "$src" ]] || continue
    if [[ ! -f "$dst" ]] || ! cmp -s "$src" "$dst"; then
        changed+=("$rel")
    fi
done

if [[ ${#changed[@]} -eq 0 ]]; then
    echo "сервер совпадает с зеркалом — применять нечего"
    exit 0
fi
echo "отличаются:"
for rel in "${changed[@]}"; do
    echo "  $rel → ${MAP[$rel]}"
    [[ "${1:-}" == "--check" ]] && diff -u "${MAP[$rel]}" "$HERE/$rel" | head -40 || true
done
[[ "${1:-}" == "--check" ]] && exit 0
[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }

mkdir -p "$BK"
touch_nginx=0; touch_f2b=0; touch_systemd=0
for rel in "${changed[@]}"; do
    dst="${MAP[$rel]}"
    [[ -f "$dst" ]] && install -D -m 0644 "$dst" "$BK/$rel"
    install -D -m 0644 "$HERE/$rel" "$dst"
    case "$rel" in
        nginx/*) touch_nginx=1;;
        fail2ban/*) touch_f2b=1;;
        systemd/*) touch_systemd=1;;
    esac
done
echo "бэкап: $BK"

# Файл deny для действия fail2ban nginx-deny: nginx включает conf.d/*.conf,
# и файл должен существовать (пусть пустой) раньше первого бана и раньше
# nginx -t ниже. actionstart у действия делает то же, но при старте fail2ban.
DENY=/etc/nginx/conf.d/f2b-deny.conf
if [[ -f "$HERE/fail2ban/action.d/nginx-deny.conf" && ! -f "$DENY" ]]; then
    install -m 0644 /dev/null "$DENY" && echo "создан пустой $DENY"
fi

restore() {
    echo "ОТКАТ: возвращаю файлы из $BK"
    for rel in "${changed[@]}"; do
        if [[ -f "$BK/$rel" ]]; then
            install -m 0644 "$BK/$rel" "${MAP[$rel]}"
        else
            rm -f "${MAP[$rel]}"
        fi
    done
}

if [[ $touch_nginx -eq 1 ]]; then
    if nginx -t 2>&1 | tail -2; then
        # reload молча не срабатывает, если у зоны limit_req/limit_conn
        # сменился ключ (06.09.2026: nginx -t прошёл, а воркеры остались
        # старые, и узлы ещё час ловили 429 по прежней зоне). Признак —
        # воркеры с прежними pid; тогда нужен restart (сотня миллисекунд).
        before=$(pgrep -P "$(cat /run/nginx.pid)" | sort | tr '\n' ' ')
        systemctl reload nginx; sleep 2
        after=$(pgrep -P "$(cat /run/nginx.pid)" | sort | tr '\n' ' ')
        if [[ "$before" == "$after" ]]; then
            echo "nginx: reload не сменил воркеры (смена ключа зоны?) — делаю restart"
            grep "\[emerg\]" /var/log/nginx/error.log | tail -2
            systemctl restart nginx
        fi
        echo "nginx: $(systemctl is-active nginx), воркеры: $(pgrep -cP "$(cat /run/nginx.pid)")"
    else
        restore; nginx -t; exit 1
    fi
fi
if [[ $touch_f2b -eq 1 ]]; then
    if fail2ban-client -t >/dev/null 2>&1; then
        systemctl reload fail2ban && echo "fail2ban: перезагружен ($(fail2ban-client status | sed -n 's/.*Jail list:\s*//p'))"
    else
        fail2ban-client -t 2>&1 | tail -5; restore; systemctl reload fail2ban || true; exit 1
    fi
fi
if [[ $touch_systemd -eq 1 ]]; then
    systemctl daemon-reload
    echo "systemd: юниты перечитаны; перезапуск служб — отдельно и осознанно (systemctl restart prosto-panel / prosto-bot)"
fi
echo "готово"
