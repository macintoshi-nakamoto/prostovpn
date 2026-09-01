#!/usr/bin/env bash
#
# Проверка доступа Hysteria2 на узле: <addr> <auth> <tx> → stdout id, код 0 = пускать.
# Ставится deploy/setup-hy2.sh в /usr/local/bin/prosto-hy2-auth, зовётся
# самим hysteria (auth.type: command) на каждое новое соединение.
#
# Спрашивает панель (POST /api/v1/hy2/auth; паролем служит UUID VLESS-учётки
# человека на этом узле). Ответ панели запоминается: когда панель не отвечает
# (перезапуск, сбой сети), знакомый пароль пускается по кэшу до недели, а
# явный отказ панели кэш чистит. Так узел не зависит от каждой секунды жизни
# панели, а отозванный доступ всё равно закрывается: панель отвечает «нет»,
# и живую сессию она же выкидывает через /kick.

set -u

CONF=/etc/prosto-hy2-auth.conf
CACHE=/var/lib/prosto-hy2/allowed
TTL=$((7 * 24 * 3600))

[[ -f "$CONF" ]] && . "$CONF"
PANEL_URL="${PANEL_URL:-https://prostovpn.cc}"

addr="${1:-}"
auth="${2:-}"
tx="${3:-0}"
[[ "$auth" =~ ^[A-Za-z0-9._:@-]{8,128}$ ]] || exit 1
[[ "$tx" =~ ^[0-9]+$ ]] || tx=0
key="$(printf '%s' "$auth" | sha256sum | cut -c1-64)"
now="$(date +%s)"

exec 9>>"$CACHE.lock"
flock -w 3 9 || true
touch "$CACHE"

nl=$'\n'
body="{\"addr\":\"${addr//\"/}\",\"auth\":\"$auth\",\"tx\":$tx}"
resp="$(curl -s -m 6 -w "${nl}%{http_code}" -X POST -H 'Content-Type: application/json' \
    -d "$body" "$PANEL_URL/api/v1/hy2/auth" 2>/dev/null)"
code="${resp##*"$nl"}"
json="${resp%"$nl"*}"

if [[ "$code" == "200" ]]; then
    if [[ "$json" == *'"ok":true'* ]]; then
        id="$(printf '%s' "$json" | sed -nE 's/.*"id":"([^"]+)".*/\1/p')"
        [[ -n "$id" ]] || id="${key:0:16}"
        { grep -v "^$key " "$CACHE"; printf '%s %s %s\n' "$key" "$id" "$now"; } > "$CACHE.tmp" 2>/dev/null
        mv "$CACHE.tmp" "$CACHE"
        printf '%s' "$id"
        exit 0
    fi
    grep -v "^$key " "$CACHE" > "$CACHE.tmp" 2>/dev/null
    mv "$CACHE.tmp" "$CACHE"
    exit 1
fi

# Панель не ответила — по памяти.
line="$(grep "^$key " "$CACHE" 2>/dev/null | head -1)"
if [[ -n "$line" ]]; then
    id="$(awk '{print $2}' <<< "$line")"
    ts="$(awk '{print $3}' <<< "$line")"
    if [[ "$ts" =~ ^[0-9]+$ ]] && (( now - ts < TTL )); then
        logger -t prosto-hy2-auth -- "панель не ответила ($code), пускаем по кэшу: $id"
        printf '%s' "$id"
        exit 0
    fi
fi
exit 1
