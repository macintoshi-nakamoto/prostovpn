#!/usr/bin/env bash
#
# Установка панели Prosto VPN на Ubuntu 22.04/24.04.
#
#   sudo bash deploy/bootstrap.sh                        # доступ по IP, самоподписанный TLS
#   sudo bash deploy/bootstrap.sh panel.example.com      # домен + сертификат Let's Encrypt
#   sudo bash deploy/bootstrap.sh --port 8443            # если 443 уже занят
#
# Скрипт можно запускать повторно: он ничего не ломает и не перезатирает
# уже сгенерированные секреты.
#
# Если 80 и 443 заняты (другой веб-сервер, Docker), скрипт не станет с ними
# спорить: он поднимет панель на отдельном порту и оставит чужое как есть.

set -euo pipefail

DOMAIN=""
HTTPS_PORT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) HTTPS_PORT="$2"; shift 2 ;;
        -*)     echo "неизвестный ключ: $1"; exit 1 ;;
        *)      DOMAIN="$1"; shift ;;
    esac
done
APP_USER="prostovpn"
APP_DIR="/opt/prosto-vpn"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/backend/.env"

log()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { warn "нужен root: sudo bash $0"; exit 1; }

# --- 1. Системные пакеты ----------------------------------------------------

log "Ставим системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential curl ca-certificates gnupg git \
    openssl ufw iproute2

# nginx отдельно и терпимо к ошибке запуска: если 80 занят чужим сервером,
# пакет поставится, но стартовать откажется, и apt вернёт ненулевой код —
# ронять из-за этого установку нельзя, конфиг мы всё равно перепишем ниже.
if ! command -v nginx >/dev/null; then
    apt-get install -y -qq nginx || warn "nginx поставился, но не стартовал — поправим конфигом"
    rm -f /etc/nginx/sites-enabled/default
fi

# Node нужен только на сборку панели. Из NodeSource, потому что в репозитории
# Ubuntu лежит версия старее, чем требует Vite.
if ! command -v node >/dev/null || [[ "$(node -v | cut -c2- | cut -d. -f1)" -lt 18 ]]; then
    log "Ставим Node.js 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    apt-get install -y -qq nodejs
fi

# --- 1а. Порт панели --------------------------------------------------------
#
# Порт выбирается здесь, до генерации .env, а не вместе с конфигом nginx:
# из него собираются PANEL_SITE_URL и PANEL_CORS_ORIGINS. Записанный без
# порта адрес уводил бы возврат с оплаты и ссылки в письмах на 443, который
# на этой машине занят кем-то другим и панели не принадлежит.

port_busy() {
    local listeners
    listeners=$(ss -lntp "sport = :$1" 2>/dev/null | grep LISTEN || true)
    [[ -z "$listeners" ]] && return 1
    # Собственный nginx занятостью не считаем: конфиг мы всё равно
    # переписываем. Иначе повторный запуск скрипта решает, что порт занял
    # кто-то чужой, и уходит на запасной порт от самого себя.
    grep -q '"nginx"' <<<"$listeners" && return 1
    return 0
}

# Порты 80 и 443 могут быть заняты чужим веб-сервером — на этой машине
# вполне может жить что-то ещё. Отбирать их нельзя: чужое перестанет
# работать. Встаём на свободный порт и говорим об этом вслух.
if [[ -z "$HTTPS_PORT" ]]; then
    if port_busy 443; then
        HTTPS_PORT=8443
        OWNER="$(ss -lntp "sport = :443" 2>/dev/null | awk 'NR==2{print $NF}')"
        warn "Порт 443 занят ($OWNER) — панель встанет на $HTTPS_PORT."
    else
        HTTPS_PORT=443
    fi
fi

if port_busy "$HTTPS_PORT"; then
    warn "Порт $HTTPS_PORT тоже занят. Выберите свободный: --port <номер>"
    exit 1
fi

# --- 2. Пользователь и файлы ------------------------------------------------

if ! id "$APP_USER" >/dev/null 2>&1; then
    log "Создаём пользователя $APP_USER"
    # Без домашнего каталога и без входа в систему: под этой учёткой только
    # крутится панель, заходить ей некуда.
    useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

log "Копируем код в $APP_DIR"
mkdir -p "$APP_DIR"
# Исключаем окружения и базу: они на сервере свои.
# `web` — публичный сайт (React + Vite), `site` — прежние статические
# страницы. Второе оставлено намеренно: оно всё ещё содержит оформление
# заказа и оплату, которых у нового сайта пока нет, и его каталог может
# стоять в PANEL_SITE_DIR на уже работающей установке.
tar -C "$SRC_DIR" \
    --exclude=.git --exclude=.venv --exclude=node_modules --exclude=dist \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude=.env \
    --exclude=__pycache__ --exclude=.pytest_cache --exclude=client \
    -cf - backend panel web site deploy README.md 2>/dev/null | tar -C "$APP_DIR" -xf -

# --- 3. Секреты -------------------------------------------------------------

if [[ -f "$ENV_FILE" ]]; then
    log "Конфиг уже есть — секреты не трогаем"
    ADMIN_PASSWORD="$(grep -E '^PANEL_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || echo '(см. .env)')"
    # Адрес берём из уже записанного .env: администратор мог поправить его
    # руками, и напечатанный в конце адрес не должен с ним расходиться.
    PUBLIC_ORIGIN="$(grep -E '^PANEL_SITE_URL=' "$ENV_FILE" | cut -d= -f2- || true)"
else
    log "Генерируем секреты"
    SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n/+=' | head -c 48)"
    # Отдельный ключ шифрования паролей клиентов. Генерируется здесь и
    # больше не меняется никогда: после смены сохранённые пароли станут
    # нечитаемыми, и «показать пароль» в панели перестанет работать.
    SECRETS_KEY="$(openssl rand -base64 48 | tr -d '\n/+=' | head -c 48)"
    MOCK_SECRET="$(openssl rand -base64 32 | tr -d '\n/+=' | head -c 32)"
    ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '\n/+=' | head -c 20)"
    PUBLIC_HOST="${DOMAIN:-$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')}"
    # Адрес с портом: на занятом 443 панель доступна только по :8443, и
    # ссылка возврата с оплаты без порта ведёт туда, где никто не слушает.
    PUBLIC_ORIGIN="https://$PUBLIC_HOST"
    if [[ "$HTTPS_PORT" != 443 ]]; then
        PUBLIC_ORIGIN="$PUBLIC_ORIGIN:$HTTPS_PORT"
    fi

    cat > "$ENV_FILE" <<EOF
# Создано deploy/bootstrap.sh $(date -Is)
PANEL_DATABASE_URL=sqlite:////opt/prosto-vpn/backend/panel.db

PANEL_ADMIN_LOGIN=admin
PANEL_ADMIN_PASSWORD=$ADMIN_PASSWORD
PANEL_SECRET_KEY=$SECRET_KEY

# НЕ МЕНЯТЬ после первого запуска: этим ключом зашифрованы пароли клиентов.
PANEL_SECRETS_KEY=$SECRETS_KEY

PANEL_CLIENT_TOKEN_DAYS=30
PANEL_ADMIN_TOKEN_DAYS=7
PANEL_CURRENCY=RUB

# Панель отдаётся с того же адреса, что и API, поэтому CORS не нужен.
PANEL_CORS_ORIGINS=$PUBLIC_ORIGIN

# Как часто панель обходит узлы по SSH за трафиком, секунд. Задавать интервал
# нужно именно здесь: значение в минутах панель молча игнорирует, пока это
# больше нуля. Каждый такт — два захода awg show на каждый активный узел, так
# что увеличивать значение осмысленно, но ровно на столько же загрубеют
# онлайн-статус и срабатывание лимита трафика. 0 останавливает обход целиком,
# а вместе с ним — автоматическое закрытие доступа по исчерпанному трафику и
# по кончившейся подписке.
PANEL_TRAFFIC_SYNC_SECONDS=60

# --- Сайт ---
# Из этого адреса собираются ссылки возврата с оплаты и ссылки в письмах.
PANEL_SITE_URL=$PUBLIC_ORIGIN
# Собранный одностраничник из web/. Пустое значение — сайт раздаёт nginx.
PANEL_SITE_DIR=../web/dist
# Маршрутизация у одностраничника своя: по прямой ссылке на /account сервер
# обязан вернуть тот же index.html, иначе перезагрузка страницы даёт 404.
PANEL_SITE_SPA=1

# --- Оплата ---
# mock — сайт работает целиком, но деньги не приходят: страница оплаты
# честно написана как демонстрационная. Перед запуском продаж поставьте
# yookassa или cryptocloud и заполните ключи ниже, см. deploy/README.md.
PANEL_PAYMENT_PROVIDER=mock
PANEL_MOCK_SECRET=$MOCK_SECRET
PANEL_MOCK_DELAY_SECONDS=2

PANEL_YOOKASSA_SHOP_ID=
PANEL_YOOKASSA_SECRET_KEY=

PANEL_CRYPTOCLOUD_API_KEY=
PANEL_CRYPTOCLOUD_SHOP_ID=
PANEL_CRYPTOCLOUD_SECRET=

PANEL_ORDER_TTL_HOURS=24

# --- Письма ---
# console — только запись в лог. Пока здесь console, письма с доступом до
# клиентов не доходят: настройте SMTP своего домена или Resend и обязательно
# пропишите SPF, DKIM и DMARC — иначе письмо уедет в спам.
PANEL_MAIL_PROVIDER=console
PANEL_MAIL_FROM=no-reply@$PUBLIC_HOST
PANEL_MAIL_FROM_NAME=Prosto
PANEL_MAIL_SUBJECT=Ваш доступ к сервису Prosto

PANEL_SMTP_HOST=
PANEL_SMTP_PORT=587
PANEL_SMTP_USER=
PANEL_SMTP_PASSWORD=

PANEL_RESEND_API_KEY=
PANEL_TELEGRAM_BOT_TOKEN=

PANEL_DELIVERY_POLL_SECONDS=15

# --- Ограничение частоты ---
PANEL_LOGIN_MAX_ATTEMPTS=5
PANEL_LOGIN_WINDOW_MINUTES=15
PANEL_LOGIN_LOCK_MINUTES=15
PANEL_ORDER_MAX_PER_HOUR=10

# Боевая установка: выдуманных клиентов в базе быть не должно.
PANEL_SEED_DEMO=0
PANEL_DEBUG=0
EOF
    chmod 600 "$ENV_FILE"
fi

# --- 3.1 Доводка существующего конфига --------------------------------------
#
# Публичный сайт переехал со статических страниц (site/) на собранный
# одностраничник (web/dist). Новая установка получает это выше, а
# существующей нужно поправить два ключа: без них обновление тихо продолжит
# отдавать прежний сайт, и правки до людей не доедут.
#
# Трогаем ровно тот случай, когда в конфиге стоит прежний каталог. Пустое
# значение не трогаем: это осознанный выбор — статику отдаёт nginx.

set_env() {
    local key="$1" value="$2"
    if grep -qE "^${key}=" "$ENV_FILE"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

CURRENT_SITE_DIR="$(grep -E '^PANEL_SITE_DIR=' "$ENV_FILE" | cut -d= -f2- || true)"
case "$CURRENT_SITE_DIR" in
    ../site|"$APP_DIR/site")
        log "Переводим сайт на собранный одностраничник"
        set_env PANEL_SITE_DIR ../web/dist
        set_env PANEL_SITE_SPA 1
        ;;
    ../web|"$APP_DIR/web")
        # Сборка, положенная в каталог руками: index.html и assets лежат в
        # самом web/. Дальше туда же распакуются исходники, и index.html
        # окажется тем, что ссылается на /src/main.jsx, — в готовой сборке
        # такого файла нет, и сайт открывался бы пустой страницей. Поэтому
        # прежнюю сборку убираем, а каталогом сайта становится web/dist.
        log "Переносим сайт из web/ в собираемый web/dist"
        rm -rf "$APP_DIR/web/index.html" "$APP_DIR/web/assets"
        set_env PANEL_SITE_DIR ../web/dist
        set_env PANEL_SITE_SPA 1
        ;;
    ../web/dist|"$APP_DIR/web/dist")
        # Уже переведён — но флаг одностраничника мог остаться невыставленным,
        # и тогда прямая ссылка на /account отдавала бы 404.
        set_env PANEL_SITE_SPA 1
        ;;
esac

# --- 4. Бэкенд --------------------------------------------------------------

log "Ставим Python-окружение"
python3 -m venv "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# --- 5. Панель --------------------------------------------------------------

log "Собираем веб-панель"
cd "$APP_DIR/panel"
npm ci --silent 2>/dev/null || npm install --silent
npm run build --silent
cd - >/dev/null

# --- 5.1 Публичный сайт -----------------------------------------------------
#
# Собирается здесь же и по той же причине, что и панель: в репозитории лежат
# исходники, а бэкенд отдаёт готовую сборку из web/dist. Без этого шага
# обновление кода до сайта не доезжает вовсе — на сервере остаётся прежняя
# сборка, и правки страниц выглядят как «выложил и ничего не изменилось».

log "Собираем публичный сайт"
cd "$APP_DIR/web"
npm ci --silent 2>/dev/null || npm install --silent
npm run build --silent
cd - >/dev/null

# Папка под установщики приложения: её раздаёт nginx по /downloads/. Лежит
# вне $APP_DIR намеренно — useradd --create-home делает домашний каталог с
# правами 0750 (HOME_MODE в /etc/login.defs), и nginx от www-data через него
# не пройдёт: каждый запрос установщика получал бы 403.
DOWNLOADS_DIR=/var/www/prosto-downloads
mkdir -p "$DOWNLOADS_DIR"
chmod 0755 "$DOWNLOADS_DIR"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# --- 6. systemd -------------------------------------------------------------

log "Настраиваем службу"
cat > /etc/systemd/system/prosto-panel.service <<EOF
[Unit]
Description=Prosto VPN — панель
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

# Панель слушает только localhost, наружу её пускает nginx. Всё, что можно
# закрыть, закрыто: наружу из этой службы ходит только SSH к VPN-серверам.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/backend
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable prosto-panel.service >/dev/null 2>&1 || true
# Именно restart, а не enable --now: для уже работающей службы «--now» не
# делает ничего, и после обновления кода uvicorn продолжал бы крутить старую
# версию — вместе с невыполненными миграциями из init_db().
systemctl restart prosto-panel.service

# Type=exec отдаёт управление сразу после exec, а упасть на разборе .env
# панель успевает уже после этого — даём ей осесть перед проверкой.
sleep 2
systemctl is-active --quiet prosto-panel.service \
    || warn "панель не поднялась — journalctl -u prosto-panel -n 50"

# --- 7. nginx и TLS ---------------------------------------------------------

log "Настраиваем nginx"
SERVER_NAME="${DOMAIN:-_}"

# Отдельная директива http2 появилась в nginx 1.25.1; в более старых
# версиях это параметр listen, и «http2 on;» там — ошибка конфигурации.
NGINX_VERSION="$(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo 0.0.0)"
if [[ "$(printf '%s\n1.25.1\n' "$NGINX_VERSION" | sort -V | head -1)" == "1.25.1" ]]; then
    LISTEN_HTTP2=""
    HTTP2_DIRECTIVE="    http2 on;"
else
    LISTEN_HTTP2=" http2"
    HTTP2_DIRECTIVE=""
fi

# Переадресация с 80 и проверка Let's Encrypt возможны, только если 80 наш.
HTTP_AVAILABLE=true
port_busy 80 && HTTP_AVAILABLE=false

# Сертификат на случай, когда настоящего нет: без домена вовсе или когда
# Let's Encrypt не смог проверить домен. Браузер будет ругаться, но токен
# администратора хотя бы не поедет по сети открытым текстом.
use_self_signed_cert() {
    CERT="/etc/ssl/prosto/panel.crt"
    KEY="/etc/ssl/prosto/panel.key"
    if [[ ! -f "$CERT" ]]; then
        mkdir -p /etc/ssl/prosto
        openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
            -keyout "$KEY" -out "$CERT" \
            -subj "/CN=$(hostname -I | awk '{print $1}')" >/dev/null 2>&1
        chmod 600 "$KEY"
    fi
}

# Перечитать конфиг, не роняя установку: с битым конфигом nginx остаётся на
# старом, а скрипт доходит до печати пароля и настройки файрвола.
reload_nginx() {
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx || systemctl restart nginx
    else
        warn "конфиг nginx не проходит проверку — nginx оставлен как был."
        warn "  Подробности: nginx -t"
    fi
}

if [[ -n "$DOMAIN" ]]; then
    CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
    CERT="$CERT_DIR/fullchain.pem"
    KEY="$CERT_DIR/privkey.pem"
else
    use_self_signed_cert
fi

# Конфиг собирается двумя кусками, потому что за сертификатом Let's Encrypt
# надо сходить с работающего nginx, а TLS-блок без готового сертификата
# стартовать не даст. Сначала пишем только блок на 80, потом дописываем TLS.

write_http_block() {
cat >> /etc/nginx/sites-available/prosto-panel <<EOF
server {
    listen 80;
    server_name $SERVER_NAME;
    # Всё на HTTPS: панель ходит с токеном в заголовке, по HTTP его читают
    # по дороге. Исключение — проверка Let's Encrypt.
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
}

write_tls_block() {
cat >> /etc/nginx/sites-available/prosto-panel <<EOF
server {
    listen $HTTPS_PORT ssl$LISTEN_HTTP2;
$HTTP2_DIRECTIVE
    server_name $SERVER_NAME;

    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;

    client_max_body_size 2m;

    # Установщики приложения. Кладите сюда .msi, .apk, .dmg и AppImage, а
    # ссылку на файл указывайте в разделе «Версии» — приложение скачает
    # обновление отсюда само.
    location /downloads/ {
        alias $DOWNLOADS_DIR/;
        autoindex off;
        # Крупные файлы отдаём без буферизации в память.
        sendfile on;
        client_max_body_size 0;
        # Кэш задаём через expires, а не add_header: свой add_header в
        # location отменяет наследование серверных заголовков, и установщики
        # уезжали бы клиенту без nosniff и остальных трёх со строк выше.
        expires 1d;
    }

    # Админка на отдельном пути — корень занят публичным сайтом. Открытая
    # всему интернету форма входа в панель приглашает её подбирать; снимите
    # комментарии с одного из вариантов и впишите свои адреса.
    location /admin {
        # allow 203.0.113.7;
        # deny all;
        #
        # либо пароль поверх панели:
        #   apt install apache2-utils
        #   htpasswd -c /etc/nginx/.htpasswd-prosto имя
        # auth_basic "Prosto";
        # auth_basic_user_file /etc/nginx/.htpasswd-prosto;

        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    # Страница успеха показывает логин и пароль — кэшировать её нельзя ни
    # браузеру, ни промежуточным прокси.
    location = /success.html {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        add_header Cache-Control "no-store" always;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        # Реальный адрес клиента. Из него панель пишет IP сессий и — что
        # важнее — сверяет отправителя вебхука со списком платёжного
        # сервиса. Без этого заголовка вебхуки будут отклоняться.
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
}

# Первый проход: только блок на 80.
: > /etc/nginx/sites-available/prosto-panel
if [[ "$HTTP_AVAILABLE" == true ]]; then
    write_http_block
fi

ln -sf /etc/nginx/sites-available/prosto-panel /etc/nginx/sites-enabled/prosto-panel
rm -f /etc/nginx/sites-enabled/default

if [[ -n "$DOMAIN" && "$HTTP_AVAILABLE" == true && ! -f "$CERT" ]]; then
    log "Получаем сертификат Let's Encrypt для $DOMAIN"
    # Только certbot, без python3-certbot-nginx: конфиг мы пишем сами, а
    # плагин --nginx завёл бы рядом свой server-блок на 443 с тем же именем.
    apt-get install -y -qq certbot
    mkdir -p /var/www/html
    reload_nginx
    # certonly --webroot: подтверждение кладётся в каталог, который уже
    # раздаётся блоком выше, и конфиг остаётся нашим. Редирект на HTTPS там
    # тоже уже есть, поэтому --redirect не нужен.
    # deploy-hook обязателен: сам по себе `certbot renew` только кладёт новый
    # файл, а nginx продолжает держать в памяти старый — и через 90 дней
    # отдаёт истёкший сертификат при вполне свежем на диске.
    if ! certbot certonly --webroot -w /var/www/html -d "$DOMAIN" \
            --non-interactive --agree-tos --register-unsafely-without-email \
            --deploy-hook 'systemctl reload nginx'; then
        warn "Let's Encrypt не выдал сертификат для $DOMAIN — проверьте, что"
        warn "  запись A указывает на этот сервер и порт 80 доступен снаружи."
        warn "Пока встаём с самоподписанным; повторите запуск скрипта позже."
        use_self_signed_cert
    fi
elif [[ -n "$DOMAIN" && "$HTTP_AVAILABLE" == false && ! -f "$CERT" ]]; then
    warn "Порт 80 занят — Let's Encrypt не сможет проверить домен."
    warn "Оставляем самоподписанный сертификат."
    use_self_signed_cert
fi

# Второй проход: конфиг целиком, сертификат к этому моменту на месте.
: > /etc/nginx/sites-available/prosto-panel
if [[ "$HTTP_AVAILABLE" == true ]]; then
    write_http_block
fi
write_tls_block

reload_nginx
systemctl enable nginx >/dev/null 2>&1 || true

# --- 8. Файрвол -------------------------------------------------------------

log "Настраиваем файрвол"
# Только то, что нужно панели. Чужие правила не трогаем: на машине может
# работать что-то ещё, и снимать его разрешения нельзя.
ufw allow 22/tcp              >/dev/null
ufw allow "$HTTPS_PORT/tcp"   >/dev/null
ufw allow 51820/udp           >/dev/null   # AmneziaWG
[[ "$HTTP_AVAILABLE" == true ]] && ufw allow 80/tcp >/dev/null
ufw --force enable            >/dev/null

# --- Готово -----------------------------------------------------------------

# Печатаем ровно тот адрес, что записан в .env: разойтись они не должны —
# по нему же собираются ссылки возврата с оплаты и ссылки в письмах.
if [[ -z "${PUBLIC_ORIGIN:-}" ]]; then
    PUBLIC="${DOMAIN:-$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')}"
    PUBLIC_ORIGIN="https://$PUBLIC"
    if [[ "$HTTPS_PORT" != 443 ]]; then
        PUBLIC_ORIGIN="$PUBLIC_ORIGIN:$HTTPS_PORT"
    fi
fi
URL="$PUBLIC_ORIGIN"

# Проверку повторяем здесь: предупреждение из шага 6 могло утонуть в выводе
# npm, nginx и ufw, а не работающая панель — главное, что надо увидеть.
systemctl is-active --quiet prosto-panel.service \
    || warn "панель не работает — journalctl -u prosto-panel -n 50"

log "Готово"
cat <<EOF

  Сайт:    $URL
  Панель:  $URL/admin
  Логин:   admin
  Пароль:  $ADMIN_PASSWORD

  Пароль лежит в $ENV_FILE — смените его после первого входа.

  Состояние:  systemctl status prosto-panel
  Логи:       journalctl -u prosto-panel -f

  Дальше:
    1. Сделать этот сервер первым VPN-сервером:
         sudo bash $APP_DIR/deploy/setup-awg.sh
    2. Настроить приём оплаты и письма — раздел «Приём оплаты» в
       $APP_DIR/deploy/README.md

EOF

warn "Оплата пока в режиме имитации (PANEL_PAYMENT_PROVIDER=mock):"
warn "  сайт работает целиком, но деньги не приходят, и любой посетитель"
warn "  может «оплатить» себе подписку. Перед запуском продаж пропишите"
warn "  ключи платёжного сервиса в $ENV_FILE."
warn "Письма пока не уходят (PANEL_MAIL_PROVIDER=console): настройте SMTP"
warn "  и записи SPF, DKIM, DMARC — без них письмо с доступом уедет в спам."

if [[ -z "$DOMAIN" ]]; then
    warn "Сертификат самоподписанный — браузер покажет предупреждение."
    warn "С доменом будет нормальный: sudo bash $0 panel.example.com --port $HTTPS_PORT"
fi
