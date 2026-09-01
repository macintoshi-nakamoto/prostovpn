#!/usr/bin/env bash
#
# Хук certbot на веб-сервере: после выпуска/продления wildcard-сертификата
# `*.prostovpn.cc` (lineage prostovpn-nodes) раскладывает его по узлам и
# перезапускает службы, которые им пользуются (xray — XHTTP/WS+TLS и dest
# для Reality, Hysteria2). Узлы берутся из базы панели.
#
# Ставится в /etc/letsencrypt/renewal-hooks/deploy/prosto-nodes.sh — certbot
# зовёт его сам после каждого удачного продления с RENEWED_LINEAGE в
# окружении. Ручной прогон: sudo bash prosto-nodes.sh --force
#
# Сертификат выпущен через DNS-01 (Cloudflare, токен в /root/.cloudflare.ini):
#   certbot certonly --dns-cloudflare --dns-cloudflare-credentials /root/.cloudflare.ini \
#     --dns-cloudflare-propagation-seconds 30 -d '*.prostovpn.cc' --cert-name prostovpn-nodes

set -u

LINEAGE_NAME="${LINEAGE_NAME:-prostovpn-nodes}"
LIVE="/etc/letsencrypt/live/${LINEAGE_NAME}"
DB="${PANEL_DB:-/opt/prosto-vpn/backend/panel.db}"
KEY="${NODE_KEY:-/root/.ssh/prosto_nodes}"
DEST=/opt/prosto-tls
TAG=prosto-certs

if [[ "${1:-}" != "--force" ]]; then
    case "${RENEWED_LINEAGE:-}" in
        */"${LINEAGE_NAME}") ;;
        *) exit 0 ;;   # продлился другой сертификат — не наше дело
    esac
fi

[[ -s "$LIVE/fullchain.pem" && -s "$LIVE/privkey.pem" ]] || { logger -t "$TAG" -- "нет файлов в $LIVE"; exit 1; }

mapfile -t HOSTS < <(sqlite3 "$DB" "select host from servers where is_active=1 and provisioning='SSH' order by id")
failed=0
for host in "${HOSTS[@]}"; do
    if scp -q -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$LIVE/fullchain.pem" "$LIVE/privkey.pem" "root@$host:$DEST/" \
        && ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "root@$host" \
            "chown root:prosto-tls $DEST/fullchain.pem $DEST/privkey.pem && chmod 0640 $DEST/fullchain.pem $DEST/privkey.pem \
             && (systemctl try-restart prosto-xray 2>/dev/null; systemctl try-restart prosto-hy2 2>/dev/null; true)"; then
        logger -t "$TAG" -- "сертификат разложен на $host"
    else
        logger -t "$TAG" -- "НЕ удалось разложить сертификат на $host"
        failed=1
    fi
done
exit $failed
