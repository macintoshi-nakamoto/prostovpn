#!/usr/bin/env bash

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


log "Ставим системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential curl ca-certificates gnupg git \
    openssl ufw iproute2

if ! command -v nginx >/dev/null; then
    apt-get install -y -qq nginx || warn "nginx поставился, но не стартовал — поправим конфигом"
    rm -f /etc/nginx/sites-enabled/default
fi

if ! command -v node >/dev/null || [[ "$(node -v | cut -c2- | cut -d. -f1)" -lt 18 ]]; then
    log "Ставим Node.js 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    apt-get install -y -qq nodejs
fi


port_busy() {
    local listeners
    listeners=$(ss -lntp "sport = :$1" 2>/dev/null | grep LISTEN || true)
    [[ -z "$listeners" ]] && return 1
    grep -q '"nginx"' <<<"$listeners" && return 1
    return 0
}

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


if ! id "$APP_USER" >/dev/null 2>&1; then
    log "Создаём пользователя $APP_USER"
    useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

log "Копируем код в $APP_DIR"
mkdir -p "$APP_DIR"
tar -C "$SRC_DIR" \
    --exclude=.git --exclude=.venv --exclude=node_modules --exclude=dist \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude=.env \
    --exclude=__pycache__ --exclude=.pytest_cache --exclude=client \
    -cf - backend panel web site deploy README.md 2>/dev/null | tar -C "$APP_DIR" -xf -


if [[ -f "$ENV_FILE" ]]; then
    log "Конфиг уже есть — секреты не трогаем"
    ADMIN_PASSWORD="$(grep -E '^PANEL_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || echo '(см. .env)')"
    PUBLIC_ORIGIN="$(grep -E '^PANEL_SITE_URL=' "$ENV_FILE" | cut -d= -f2- || true)"
else
    log "Генерируем секреты"
    SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n/+=' | head -c 48)"
    SECRETS_KEY="$(openssl rand -base64 48 | tr -d '\n/+=' | head -c 48)"
    MOCK_SECRET="$(openssl rand -base64 32 | tr -d '\n/+=' | head -c 32)"
    ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '\n/+=' | head -c 20)"
    PUBLIC_HOST="${DOMAIN:-$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')}"
    PUBLIC_ORIGIN="https://$PUBLIC_HOST"
    if [[ "$HTTPS_PORT" != 443 ]]; then
        PUBLIC_ORIGIN="$PUBLIC_ORIGIN:$HTTPS_PORT"
    fi

    cat > "$ENV_FILE" <<EOF
PANEL_DATABASE_URL=sqlite:////opt/prosto-vpn/backend/panel.db

PANEL_ADMIN_LOGIN=admin
PANEL_ADMIN_PASSWORD=$ADMIN_PASSWORD
PANEL_SECRET_KEY=$SECRET_KEY

PANEL_SECRETS_KEY=$SECRETS_KEY

PANEL_CLIENT_TOKEN_DAYS=30
PANEL_ADMIN_TOKEN_DAYS=7
PANEL_CURRENCY=RUB

PANEL_CORS_ORIGINS=$PUBLIC_ORIGIN

PANEL_TRAFFIC_SYNC_SECONDS=60

PANEL_SITE_URL=$PUBLIC_ORIGIN
PANEL_SITE_DIR=../web/dist
PANEL_SITE_SPA=1

PANEL_PAYMENT_PROVIDER=mock
PANEL_MOCK_SECRET=$MOCK_SECRET
PANEL_MOCK_DELAY_SECONDS=2

PANEL_YOOKASSA_SHOP_ID=
PANEL_YOOKASSA_SECRET_KEY=

PANEL_CRYPTOCLOUD_API_KEY=
PANEL_CRYPTOCLOUD_SHOP_ID=
PANEL_CRYPTOCLOUD_SECRET=

PANEL_ORDER_TTL_HOURS=24

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

PANEL_LOGIN_MAX_ATTEMPTS=5
PANEL_LOGIN_WINDOW_MINUTES=15
PANEL_LOGIN_LOCK_MINUTES=15
PANEL_ORDER_MAX_PER_HOUR=10

PANEL_SEED_DEMO=0
PANEL_DEBUG=0
EOF
    chmod 600 "$ENV_FILE"
fi


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
        log "Переносим сайт из web/ в собираемый web/dist"
        rm -rf "$APP_DIR/web/index.html" "$APP_DIR/web/assets"
        set_env PANEL_SITE_DIR ../web/dist
        set_env PANEL_SITE_SPA 1
        ;;
    ../web/dist|"$APP_DIR/web/dist")
        set_env PANEL_SITE_SPA 1
        ;;
esac


log "Ставим Python-окружение"
python3 -m venv "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"


log "Собираем веб-панель"
cd "$APP_DIR/panel"
npm ci --silent 2>/dev/null || npm install --silent
npm run build --silent
cd - >/dev/null


log "Собираем публичный сайт"
cd "$APP_DIR/web"
npm ci --silent 2>/dev/null || npm install --silent
npm run build --silent
cd - >/dev/null

DOWNLOADS_DIR=/var/www/prosto-downloads
mkdir -p "$DOWNLOADS_DIR"
chmod 0755 "$DOWNLOADS_DIR"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"


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
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
Restart=always
RestartSec=3

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
systemctl restart prosto-panel.service

sleep 2
systemctl is-active --quiet prosto-panel.service \
    || warn "панель не поднялась — journalctl -u prosto-panel -n 50"


log "Настраиваем nginx"
SERVER_NAME="${DOMAIN:-_}"

NGINX_VERSION="$(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo 0.0.0)"
if [[ "$(printf '%s\n1.25.1\n' "$NGINX_VERSION" | sort -V | head -1)" == "1.25.1" ]]; then
    LISTEN_HTTP2=""
    HTTP2_DIRECTIVE="    http2 on;"
else
    LISTEN_HTTP2=" http2"
    HTTP2_DIRECTIVE=""
fi

HTTP_AVAILABLE=true
port_busy 80 && HTTP_AVAILABLE=false

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


write_http_block() {
cat >> /etc/nginx/sites-available/prosto-panel <<EOF
server {
    listen 80;
    server_name $SERVER_NAME;
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

    location /downloads/ {
        alias $DOWNLOADS_DIR/;
        autoindex off;
        sendfile on;
        client_max_body_size 0;
        expires 1d;
    }

    location /admin {

        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

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
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
}

: > /etc/nginx/sites-available/prosto-panel
if [[ "$HTTP_AVAILABLE" == true ]]; then
    write_http_block
fi

ln -sf /etc/nginx/sites-available/prosto-panel /etc/nginx/sites-enabled/prosto-panel
rm -f /etc/nginx/sites-enabled/default

if [[ -n "$DOMAIN" && "$HTTP_AVAILABLE" == true && ! -f "$CERT" ]]; then
    log "Получаем сертификат Let's Encrypt для $DOMAIN"
    apt-get install -y -qq certbot
    mkdir -p /var/www/html
    reload_nginx
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

: > /etc/nginx/sites-available/prosto-panel
if [[ "$HTTP_AVAILABLE" == true ]]; then
    write_http_block
fi
write_tls_block

reload_nginx
systemctl enable nginx >/dev/null 2>&1 || true


log "Настраиваем файрвол"
ufw allow 22/tcp              >/dev/null
ufw allow "$HTTPS_PORT/tcp"   >/dev/null
ufw allow 51820/udp           >/dev/null   # AmneziaWG
[[ "$HTTP_AVAILABLE" == true ]] && ufw allow 80/tcp >/dev/null
ufw --force enable            >/dev/null


if [[ -z "${PUBLIC_ORIGIN:-}" ]]; then
    PUBLIC="${DOMAIN:-$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')}"
    PUBLIC_ORIGIN="https://$PUBLIC"
    if [[ "$HTTPS_PORT" != 443 ]]; then
        PUBLIC_ORIGIN="$PUBLIC_ORIGIN:$HTTPS_PORT"
    fi
fi
URL="$PUBLIC_ORIGIN"

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
