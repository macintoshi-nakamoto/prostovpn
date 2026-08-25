#!/usr/bin/env bash

set -euo pipefail

DOMAIN="${1-}"
CF_TOKEN="${2:-${CF_API_TOKEN:-}}"
REPO="${PROSTO_REPO:-https://github.com/macintoshi-nakamoto/prostovpn.git}"
SRC="/root/prosto-vpn"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root"; exit 1; }


log "Забираем код"
apt-get update -qq
apt-get install -y -qq git curl jq >/dev/null

if [[ -d "$SRC/.git" ]]; then
    git -C "$SRC" pull --ff-only
else
    git clone --depth 1 "$REPO" "$SRC"
fi
ok "код в $SRC"

if [[ ! -d "$SRC/backend" ]]; then
    warn "в репозитории нет каталога backend/."
    warn "Похоже, склонирован репозиторий клиента, а не монорепозиторий с панелью."
    warn "Укажите нужный: PROSTO_REPO=https://... bash go.sh $DOMAIN"
    exit 1
fi


if [[ -n "$CF_TOKEN" && -n "$DOMAIN" ]]; then
    log "Настраиваем DNS в Cloudflare"
    IP="$(curl -fsS --max-time 10 https://api.ipify.org)"

    ZONE_NAME="$(echo "$DOMAIN" | awk -F. '{print $(NF-1)"."$NF}')"
    ZONE_ID="$(curl -fsS -H "Authorization: Bearer $CF_TOKEN" \
        "https://api.cloudflare.com/client/v4/zones?name=$ZONE_NAME" | jq -r '.result[0].id // empty')"

    if [[ -z "$ZONE_ID" ]]; then
        warn "зона $ZONE_NAME в Cloudflare не найдена или токен не подошёл."
        warn "Проверьте токен и что домен добавлен в аккаунт. DNS настроим позже вручную."
    else
        EXISTING="$(curl -fsS -H "Authorization: Bearer $CF_TOKEN" \
            "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?type=A&name=$DOMAIN" \
            | jq -r '.result[0].id // empty')"

        BODY="$(jq -nc --arg n "$DOMAIN" --arg c "$IP" \
            '{type:"A",name:$n,content:$c,ttl:120,proxied:false}')"

        if [[ -n "$EXISTING" ]]; then
            curl -fsS -X PUT -H "Authorization: Bearer $CF_TOKEN" \
                -H "Content-Type: application/json" --data "$BODY" \
                "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$EXISTING" >/dev/null
            ok "запись A обновлена: $DOMAIN → $IP"
        else
            curl -fsS -X POST -H "Authorization: Bearer $CF_TOKEN" \
                -H "Content-Type: application/json" --data "$BODY" \
                "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" >/dev/null
            ok "запись A создана: $DOMAIN → $IP"
        fi

        log "Ждём, пока домен начнёт указывать сюда"
        for _ in $(seq 1 30); do
            RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)"
            [[ "$RESOLVED" == "$IP" ]] && { ok "$DOMAIN → $IP"; break; }
            sleep 4
        done
    fi
fi


log "Ставим панель и сайт"
bash "$SRC/deploy/bootstrap.sh" ${DOMAIN:+"$DOMAIN"}


log "Делаем эту машину VPN-узлом"
bash "$SRC/deploy/setup-awg.sh" "Нидерланды" "Амстердам" NL

if [[ "$(cat /proc/sys/net/ipv4/ip_forward)" != "1" ]]; then
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    grep -q '^net.ipv4.ip_forward' /etc/sysctl.conf \
        || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
    ok "включена пересылка пакетов"
fi


log "Проверяем"
BASE="https://${DOMAIN:-$(curl -fsS https://api.ipify.org)}"

VERSION="$(curl -sk "$BASE/openapi.json" | jq -r '.info.version // "нет ответа"')"
echo "   версия панели: $VERSION"
[[ "$VERSION" == "2.0.0" ]] && warn "это старая сборка — панель не обновилась"

PLANS="$(curl -sk "$BASE/api/v1/plans" | jq -r 'if type=="array" then length else "не JSON" end')"
echo "   тарифов на витрине: $PLANS"

systemctl is-active --quiet prosto-panel && ok "служба панели работает" || warn "панель не запустилась"
systemctl is-active --quiet awg-quick@awg0 && ok "туннель поднят" || warn "туннель не поднялся"

PEERS="$(awg show awg0 peers 2>/dev/null | grep -c . || echo 0)"
echo "   пиров на узле: $PEERS"

cat <<EOF

────────────────────────────────────────────────────────────
  Сайт:    $BASE
  Панель:  $BASE/admin

  Дальше в панели:
    1. «Серверы» → «Проверить» — должно быть «Рабочий»
    2. «Тарифы» — выставить цены
    3. «Версии» — ссылки на установщики приложения
    4. .env — ключи платёжного сервиса и почты

  Приложение собирать с адресом этой панели:
    cmake -DPROSTO_PANEL_URL="$BASE" ...
────────────────────────────────────────────────────────────

EOF

warn "Смените пароль root и пароль администратора панели: они передавались в переписке."
