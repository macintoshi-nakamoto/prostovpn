#!/usr/bin/env bash
#
# Полная установка Prosto одной командой — для веб-консоли хостера.
#
# Зачем отдельный скрипт вместо «зайдите по SSH и выполните три шага»:
# на машине разработчика исходящий порт 22 закрыт на сетевом уровне, и
# зайти на сервер оттуда нельзя вообще. Остаётся веб-консоль хостера, а в
# ней набирают руками — значит, команда должна быть одна, а не три, и
# отменяемых шагов в ней быть не должно.
#
#   bash go.sh                                # домен из первого аргумента, TLS от Let's Encrypt
#   bash go.sh example.com CF_TOKEN          # плюс проверка записи A в Cloudflare
#   bash go.sh ""                             # без домена, самоподписанный TLS
#
# Если запись A уже создана и указывает на этот сервер, то
# токен Cloudflare нужен только если адрес сервера сменится.
#
# Делает по порядку:
#   1. забирает код,
#   2. (если дан токен) создаёт в Cloudflare запись A на этот сервер,
#   3. ставит панель, сайт и nginx с сертификатом,
#   4. делает эту же машину первым VPN-узлом,
#   5. проверяет, что клиент действительно сможет подключиться.
#
# Запускать можно повторно: секреты и база не перезатираются.

set -euo pipefail

# Домен по умолчанию — рабочий домен сервиса. Токен Cloudflare по умолчанию
# не задаётся и в репозитории не хранится: секрет в git — это секрет,
# который уже утёк.
# Форма ${1-...} без двоеточия: явно переданная пустая строка должна
# сохраниться, иначе задокументированный выше `bash go.sh ""` («без домена»)
# молча поставит домен по умолчанию и уйдёт за сертификатом для чужого имени.
DOMAIN="${1-}"
CF_TOKEN="${2:-${CF_API_TOKEN:-}}"
REPO="${PROSTO_REPO:-https://github.com/macintoshi-nakamoto/prostovpn.git}"
SRC="/root/prosto-vpn"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root"; exit 1; }

# --- 1. Код -----------------------------------------------------------------

log "Забираем код"
apt-get update -qq
apt-get install -y -qq git curl jq >/dev/null

if [[ -d "$SRC/.git" ]]; then
    git -C "$SRC" pull --ff-only
else
    git clone --depth 1 "$REPO" "$SRC"
fi
ok "код в $SRC"

# Панель, сайт и бэкенд лежат в отдельном репозитории, если этот — только
# клиент. Проверяем и говорим понятно, а не падаем на отсутствующем пути.
if [[ ! -d "$SRC/backend" ]]; then
    warn "в репозитории нет каталога backend/."
    warn "Похоже, склонирован репозиторий клиента, а не монорепозиторий с панелью."
    warn "Укажите нужный: PROSTO_REPO=https://... bash go.sh $DOMAIN"
    exit 1
fi

# --- 2. Cloudflare ----------------------------------------------------------

if [[ -n "$CF_TOKEN" && -n "$DOMAIN" ]]; then
    log "Настраиваем DNS в Cloudflare"
    IP="$(curl -fsS --max-time 10 https://api.ipify.org)"

    # Зона — это домен второго уровня: для vpn.example.com зона example.com.
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

        # proxied=false обязателен. Через оранжевое облако Cloudflare ходит
        # только HTTP и HTTPS, а VPN — это UDP 51820; спрятав узел за прокси,
        # мы спрячем его и от клиентов.
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

# --- 3. Панель, сайт, TLS ---------------------------------------------------

log "Ставим панель и сайт"
bash "$SRC/deploy/bootstrap.sh" ${DOMAIN:+"$DOMAIN"}

# --- 4. VPN-узел ------------------------------------------------------------

log "Делаем эту машину VPN-узлом"
bash "$SRC/deploy/setup-awg.sh" "Нидерланды" "Амстердам" NL

# Пересылка пакетов. Без неё туннель поднимается, клиент видит «подключено»,
# а сайты не открываются — самая тихая и самая обидная поломка.
if [[ "$(cat /proc/sys/net/ipv4/ip_forward)" != "1" ]]; then
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    grep -q '^net.ipv4.ip_forward' /etc/sysctl.conf \
        || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
    ok "включена пересылка пакетов"
fi

# --- 5. Проверка ------------------------------------------------------------

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
