#!/usr/bin/env bash
#
# Прокси Cloudflare для сайта, кабинета и API — включить, выключить, посмотреть.
#
#   sudo bash cloudflare-proxy.sh status
#   sudo bash cloudflare-proxy.sh on      # с пробой режима SSL: при Flexible откажется
#   sudo bash cloudflare-proxy.sh off     # аварийный откат: DNS снова прямо на сервер
#
# Узлы (media-*.prostovpn.cc) не трогает никогда: их трафик через Cloudflare
# не ходит. Токен — тот же, что у certbot (/root/.cloudflare.ini), у него
# права только на DNS, поэтому режим SSL зоны отсюда не переключить — его
# ставит владелец в панели Cloudflare: SSL/TLS → Full (strict).
#
# Почему проба обязательна: 05.09.2026 зона оказалась в режиме Flexible —
# Cloudflare ходил на наш порт 80, nginx отвечал редиректом на https,
# и сайт три минуты крутился в бесконечном 301. Проба ловит именно это:
# ответ 301 на самого себя.
set -euo pipefail

ZONE="prostovpn.cc"
NAMES=("prostovpn.cc" "www.prostovpn.cc" "sub.prostovpn.cc" "rusvpn.prostovpn.cc")
ORIGIN="103.114.43.45"
API="https://api.cloudflare.com/client/v4"

TOKEN=$(grep -oE "dns_cloudflare_api_token *= *\S+" /root/.cloudflare.ini | sed 's/.*= *//')
[[ -n "$TOKEN" ]] || { echo "нет токена в /root/.cloudflare.ini"; exit 1; }
H="Authorization: Bearer $TOKEN"

zone_id() {
    curl -s -H "$H" "$API/zones?name=$ZONE" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"][0]["id"])'
}

records() {
    curl -s -H "$H" "$API/zones/$1/dns_records?type=A&per_page=100" | python3 -c '
import sys, json
for r in json.load(sys.stdin)["result"]:
    print(r["id"], r["name"], r["content"], r["proxied"])'
}

set_proxied() {  # zone id, record id, true|false
    curl -s -X PATCH -H "$H" -H "Content-Type: application/json" "$API/zones/$1/dns_records/$2" \
        --data "{\"proxied\":$3}" | python3 -c 'import sys,json; r=json.load(sys.stdin); print("ok" if r.get("success") else r.get("errors"))'
}

probe_ssl_mode() {  # печатает full | flexible | unknown
    local zid="$1" name="cf-probe-$RANDOM" rid host
    rid=$(curl -s -X POST -H "$H" -H "Content-Type: application/json" "$API/zones/$zid/dns_records" \
        --data "{\"type\":\"A\",\"name\":\"$name\",\"content\":\"$ORIGIN\",\"proxied\":true,\"ttl\":1}" \
        | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["result"]["id"] if r.get("success") else "")')
    [[ -n "$rid" ]] || { echo unknown; return; }
    host="$name.$ZONE"
    sleep 12
    local code location
    code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://$host/api/health" || true)
    location=$(curl -s -D - -o /dev/null -m 20 "https://$host/api/health" 2>/dev/null | grep -i '^location:' | tr -d '\r' | sed 's/^[Ll]ocation: *//')
    curl -s -X DELETE -H "$H" "$API/zones/$zid/dns_records/$rid" >/dev/null
    # Редирект на самого себя (тот же хост) — Cloudflare пришёл на порт 80.
    if [[ "$code" == "301" || "$code" == "302" ]] && [[ "$location" == "https://$host/"* ]]; then
        echo flexible
    elif [[ "$code" =~ ^(200|301|302|404)$ ]]; then
        echo full
    else
        echo unknown
    fi
}

ZID=$(zone_id)
case "${1:-status}" in
    status)
        records "$ZID" | while read -r id name content proxied; do
            printf "  %-26s %-16s proxied=%s\n" "$name" "$content" "$proxied"
        done
        ;;
    on)
        echo "== проба режима SSL"
        mode=$(probe_ssl_mode "$ZID")
        echo "  режим: $mode"
        if [[ "$mode" != "full" ]]; then
            echo "  Не включаю. В панели Cloudflare: SSL/TLS → Overview → Full (strict), потом снова."
            exit 1
        fi
        echo "== включаем прокси"
        records "$ZID" | while read -r id name content proxied; do
            for want in "${NAMES[@]}"; do
                [[ "$name" == "$want" ]] && printf "  %-26s → %s\n" "$name" "$(set_proxied "$ZID" "$id" true)"
            done
        done
        echo "Дальше: подождать 5 минут (TTL) и закрыть вход: bash cloudflare-origin.sh"
        ;;
    off)
        echo "== выключаем прокси (аварийный откат)"
        records "$ZID" | while read -r id name content proxied; do
            for want in "${NAMES[@]}"; do
                [[ "$name" == "$want" ]] && printf "  %-26s → %s\n" "$name" "$(set_proxied "$ZID" "$id" false)"
            done
        done
        echo "Если вход был закрыт на Cloudflare: bash cloudflare-origin.sh --open"
        ;;
    *)
        echo "использование: cloudflare-proxy.sh status|on|off"; exit 1;;
esac
