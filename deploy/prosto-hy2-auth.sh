#!/usr/bin/env bash
#
# Проверка доступа Hysteria2 на узле: <addr> <auth> <tx> → stdout id, код 0 = пускать.
# Ставится deploy/setup-hy2.sh в /usr/local/bin/prosto-hy2-auth, зовётся
# самим hysteria (auth.type: command) на каждое новое соединение.
#
# Спрашивает панель (POST /api/v1/hy2/auth; паролем служит UUID VLESS-учётки
# человека на этом узле), но не на каждое соединение — иначе любой, кто
# шлёт на 443/udp мусорные пароли, превращает узел в фабрику bash+curl, а
# панель — в жертву. Поэтому:
#   - свежий ответ «да» (POS_TTL) и «нет» (NEG_TTL) отдаётся из кэша без
#     похода в панель;
#   - обращений к панели не больше BUDGET_MAX за BUDGET_WIN секунд; сверх
#     бюджета отвечаем только по кэшу — знакомых пускаем, чужих нет. Так
#     атакующий с уникальными паролями не забивает панель, а свои клиенты
#     продолжают подключаться;
#   - когда панель недоступна (5xx, 52x Cloudflare, таймаут), знакомый пароль
#     пускается по кэшу до TTL, а явный отказ панели кэш чистит. Отозванный
#     доступ всё равно закрывается: живую сессию панель выкидывает через /kick.

set -u

CONF=/etc/prosto-hy2-auth.conf
CACHE=/var/lib/prosto-hy2/allowed
DENIED="$CACHE.denied"
BUDGET="$CACHE.budget"
TTL=$((6 * 3600))   # офлайн-запас: столько живёт «да», пока панель молчит
POS_TTL=60          # свежее «да» — без похода в панель
NEG_TTL=90          # свежее «нет» — без похода в панель
BUDGET_WIN=10       # окно бюджета, секунд
BUDGET_MAX=40       # обращений к панели за окно (≈240/мин с узла)

[[ -f "$CONF" ]] && . "$CONF"
PANEL_URL="${PANEL_URL:-https://prostovpn.cc}"

addr="${1:-}"
auth="${2:-}"
tx="${3:-0}"
[[ "$auth" =~ ^[A-Za-z0-9._:@-]{8,128}$ ]] || exit 1
[[ "$tx" =~ ^[0-9]+$ ]] || tx=0
key="$(printf '%s' "$auth" | sha256sum | cut -c1-64)"
now="$(date +%s)"

# Замок держим только на чтение/запись файлов кэша (миллисекунды), а не на
# время curl: иначе под штормом сотни процессов стоят в очереди за замком,
# и hysteria упирается в TasksMax, отказывая всем. Не дождались замка —
# пишем ничего не будем (чтение безопасно: файлы меняются только через mv),
# а ответим как при исчерпанном бюджете, по кэшу.
have_lock=0
lock()   { exec 9>>"$CACHE.lock"; if flock -w 2 9; then have_lock=1; else have_lock=0; fi; }
unlock() { exec 9>&-; have_lock=0; }

# --- Шаг A: кэш и бюджет ---------------------------------------------------
lock
[[ -f "$CACHE" && -f "$DENIED" && -f "$BUDGET" ]] || touch "$CACHE" "$DENIED" "$BUDGET"

c_id=""; c_ts=0
line="$(awk -v k="$key" '$1 == k { print $2, $3; exit }' "$CACHE" 2>/dev/null)"
if [[ -n "$line" ]]; then
    c_id="${line%% *}"; c_ts="${line##* }"
    [[ "$c_ts" =~ ^[0-9]+$ ]] || c_ts=0
fi
if [[ -n "$c_id" ]] && (( now - c_ts < POS_TTL )); then
    unlock
    printf '%s' "$c_id"
    exit 0
fi

d_ts="$(awk -v k="$key" '$1 == k { print $2; exit }' "$DENIED" 2>/dev/null)"
if [[ "$d_ts" =~ ^[0-9]+$ ]] && (( now - d_ts < NEG_TTL )); then
    unlock
    exit 1
fi

cache_only=1
if (( have_lock )); then
    win=""; cnt=""
    read -r win cnt < "$BUDGET" 2>/dev/null || true
    [[ "$win" =~ ^[0-9]+$ && "$cnt" =~ ^[0-9]+$ ]] || { win=$now; cnt=0; }
    (( now - win >= BUDGET_WIN )) && { win=$now; cnt=0; }
    if (( cnt < BUDGET_MAX )); then
        cache_only=0
        printf '%s %s\n' "$win" "$((cnt + 1))" > "$BUDGET"
    fi
fi
unlock
if (( cache_only )); then
    # Бюджет исчерпан (или замок занят) — только по кэшу. Незнакомый пароль
    # в denied не пишем: это не ответ панели, а наша экономия.
    if [[ -n "$c_id" ]] && (( now - c_ts < TTL )); then
        logger -t prosto-hy2-auth -- "бюджет панели исчерпан, пускаем по кэшу: $c_id"
        printf '%s' "$c_id"
        exit 0
    fi
    exit 1
fi

# --- Шаг B: панель (без замка) ---------------------------------------------
nl=$'\n'
body="{\"addr\":\"${addr//\"/}\",\"auth\":\"$auth\",\"tx\":$tx}"
resp="$(curl -s -m 3 -w "${nl}%{http_code}" -X POST -H 'Content-Type: application/json' \
    -d "$body" "$PANEL_URL/api/v1/hy2/auth" 2>/dev/null)"
code="${resp##*"$nl"}"
json="${resp%"$nl"*}"

# --- Шаг C: запись ответа в кэш (снова под замком; без замка — не пишем) ---
remember_ok() {
    (( have_lock )) || return 0
    { grep -v "^$key " "$CACHE"; printf '%s %s %s\n' "$key" "$1" "$now"; } > "$CACHE.tmp" 2>/dev/null
    mv "$CACHE.tmp" "$CACHE"
    grep -v "^$key " "$DENIED" > "$DENIED.tmp" 2>/dev/null
    mv "$DENIED.tmp" "$DENIED"
}
remember_denied() {
    # Панель сказала «нет»: строку из «да» убираем, в «нет» пишем с чисткой
    # протухших записей — иначе файл растёт с каждым мусорным паролем.
    (( have_lock )) || return 0
    grep -v "^$key " "$CACHE" > "$CACHE.tmp" 2>/dev/null
    mv "$CACHE.tmp" "$CACHE"
    {
        awk -v now="$now" -v ttl="$NEG_TTL" -v k="$key" '$1 != k && $2 ~ /^[0-9]+$/ && now - $2 < ttl' "$DENIED" 2>/dev/null
        printf '%s %s\n' "$key" "$now"
    } > "$DENIED.tmp"
    mv "$DENIED.tmp" "$DENIED"
}

if [[ "$code" == "200" ]]; then
    if [[ "$json" == *'"ok":true'* ]]; then
        id="$(printf '%s' "$json" | sed -nE 's/.*"id":"([^"]+)".*/\1/p')"
        [[ -n "$id" ]] || id="${key:0:16}"
        lock; remember_ok "$id"; unlock
        printf '%s' "$id"
        exit 0
    fi
    lock; remember_denied; unlock
    exit 1
fi

case "$code" in
    400|401|403|422)
        # Панель ответила и отказала (плохой запрос, не узел) — это вердикт,
        # а не сбой: по кэшу не пускаем. Но 403/400 умеют отдавать и Cloudflare
        # (WAF, проверка на бота), и nginx — HTML-страницей; к паролю такой
        # отказ не относится, и принять его за вердикт значило бы вычистить
        # кэш и закрыть Hysteria2 всем на узле. Ответ панели — JSON с "detail",
        # по нему и различаем; остальное — «панель недоступна».
        if [[ "$json" == *'"detail"'* ]]; then
            lock; remember_denied; unlock
            exit 1
        fi
        ;;
esac

# Панель недоступна (5xx, 52x от Cloudflare, 000 — таймаут/сеть): по памяти.
if [[ -n "$c_id" ]] && (( now - c_ts < TTL )); then
    logger -t prosto-hy2-auth -- "панель не ответила ($code), пускаем по кэшу: $c_id"
    printf '%s' "$c_id"
    exit 0
fi
exit 1
