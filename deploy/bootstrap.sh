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
tar -C "$SRC_DIR" \
    --exclude=.git --exclude=.venv --exclude=node_modules --exclude=dist \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude=.env \
    --exclude=__pycache__ --exclude=.pytest_cache --exclude=client \
    -cf - backend panel deploy README.md 2>/dev/null | tar -C "$APP_DIR" -xf -

# --- 3. Секреты -------------------------------------------------------------

if [[ -f "$ENV_FILE" ]]; then
    log "Конфиг уже есть — секреты не трогаем"
    ADMIN_PASSWORD="$(grep -E '^PANEL_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || echo '(см. .env)')"
else
    log "Генерируем секреты"
    SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n/+=' | head -c 48)"
    ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '\n/+=' | head -c 20)"
    PUBLIC_HOST="${DOMAIN:-$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')}"

    cat > "$ENV_FILE" <<EOF
# Создано deploy/bootstrap.sh $(date -Is)
PANEL_DATABASE_URL=sqlite:////opt/prosto-vpn/backend/panel.db

PANEL_ADMIN_LOGIN=admin
PANEL_ADMIN_PASSWORD=$ADMIN_PASSWORD
PANEL_SECRET_KEY=$SECRET_KEY

PANEL_CLIENT_TOKEN_DAYS=30
PANEL_ADMIN_TOKEN_DAYS=7
PANEL_CURRENCY=RUB

# Панель отдаётся с того же адреса, что и API, поэтому CORS не нужен.
PANEL_CORS_ORIGINS=https://$PUBLIC_HOST

PANEL_TRAFFIC_SYNC_MINUTES=15

# Боевая установка: выдуманных клиентов в базе быть не должно.
PANEL_SEED_DEMO=0
PANEL_DEBUG=0
EOF
    chmod 600 "$ENV_FILE"
fi

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

# Папка под установщики приложения: её раздаёт nginx по /downloads/.
mkdir -p "$APP_DIR/downloads"

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
systemctl enable --now prosto-panel.service

# --- 7. nginx и TLS ---------------------------------------------------------

log "Настраиваем nginx"
SERVER_NAME="${DOMAIN:-_}"

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

# Переадресация с 80 и проверка Let's Encrypt возможны, только если 80 наш.
HTTP_AVAILABLE=true
port_busy 80 && HTTP_AVAILABLE=false

if [[ -n "$DOMAIN" ]]; then
    CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
    CERT="$CERT_DIR/fullchain.pem"
    KEY="$CERT_DIR/privkey.pem"
else
    # Без домена сертификат самоподписанный: браузер будет ругаться, но
    # токен администратора хотя бы не поедет по сети открытым текстом.
    CERT="/etc/ssl/prosto/panel.crt"
    KEY="/etc/ssl/prosto/panel.key"
    if [[ ! -f "$CERT" ]]; then
        mkdir -p /etc/ssl/prosto
        openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
            -keyout "$KEY" -out "$CERT" \
            -subj "/CN=$(hostname -I | awk '{print $1}')" >/dev/null 2>&1
        chmod 600 "$KEY"
    fi
fi

: > /etc/nginx/sites-available/prosto-panel

if [[ "$HTTP_AVAILABLE" == true ]]; then
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
fi

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
        alias $APP_DIR/downloads/;
        autoindex off;
        # Крупные файлы отдаём без буферизации в память.
        sendfile on;
        client_max_body_size 0;
        add_header Cache-Control "public, max-age=86400";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        # Реальный адрес клиента — из него панель пишет IP сессий.
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/prosto-panel /etc/nginx/sites-enabled/prosto-panel
rm -f /etc/nginx/sites-enabled/default

if [[ -n "$DOMAIN" && "$HTTP_AVAILABLE" == true && ! -f "$CERT" ]]; then
    log "Получаем сертификат Let's Encrypt для $DOMAIN"
    apt-get install -y -qq certbot python3-certbot-nginx
    # Пока сертификата нет, nginx с TLS-блоком не стартует, а certbot без
    # работающего nginx не пройдёт проверку домена. Поэтому сначала только
    # блок на 80, потом сертификат, потом полный конфиг.
    sed -i "/listen $HTTPS_PORT ssl;/,\$d" /etc/nginx/sites-available/prosto-panel
    systemctl reload nginx || systemctl restart nginx
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
elif [[ -n "$DOMAIN" && "$HTTP_AVAILABLE" == false ]]; then
    warn "Порт 80 занят — Let's Encrypt не сможет проверить домен."
    warn "Оставляем самоподписанный сертификат."
fi

nginx -t && { systemctl reload nginx || systemctl restart nginx; }
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

PUBLIC="${DOMAIN:-$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')}"
URL="https://$PUBLIC"
[[ "$HTTPS_PORT" != 443 ]] && URL="https://$PUBLIC:$HTTPS_PORT"

log "Готово"
cat <<EOF

  Панель:  $URL
  Логин:   admin
  Пароль:  $ADMIN_PASSWORD

  Пароль лежит в $ENV_FILE — смените его после первого входа.

  Состояние:  systemctl status prosto-panel
  Логи:       journalctl -u prosto-panel -f

  Дальше — сделать этот сервер первым VPN-сервером:
      sudo bash $APP_DIR/deploy/setup-awg.sh

EOF

if [[ -z "$DOMAIN" ]]; then
    warn "Сертификат самоподписанный — браузер покажет предупреждение."
    warn "С доменом будет нормальный: sudo bash $0 panel.example.com --port $HTTPS_PORT"
fi
