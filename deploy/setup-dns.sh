#!/usr/bin/env bash
#
# DNS без рекламы на узле: свой рекурсивный резолвер Unbound со списком
# рекламных и следящих доменов (RPZ от hagezi).
#
# Кто им пользуется: только те, у кого в кабинете включено «Без рекламы» —
# панель подставляет им адрес узла в DNS конфига. Остальные как ходили
# к 1.1.1.1, так и ходят. Слушает на публичном адресе узла и на адресах
# интерфейсов AmneziaWG, но отвечает лишь своим: подсетям туннеля и
# другим нашим узлам (через них уходит DNS у Happ с балансировкой).
#
#   sudo bash setup-dns.sh <ip узла 1> <ip узла 2> ...   # все наши узлы, включая этот
#   sudo bash setup-dns.sh --status
#
# Список обновляется раз в сутки таймером prosto-dns-update; проверить:
#   dig @<ip узла> mc.yandex.ru       → NXDOMAIN
#   dig @<ip узла> ya.ru             → адрес
set -euo pipefail

RPZ_URL="https://raw.githubusercontent.com/hagezi/dns-blocklists/main/rpz/pro.txt"
RPZ_FILE="/var/lib/unbound/prosto-ads.rpz"
CONF="/etc/unbound/unbound.conf.d/prosto.conf"
UPDATER="/usr/local/bin/prosto-dns-update"

[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }

if [[ "${1:-}" == "--status" ]]; then
    systemctl --no-pager --lines=3 status unbound prosto-dns-update.timer || true
    PUB=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
    echo; echo "реклама (ждём пусто):"; dig +short @"$PUB" mc.yandex.ru | head -2 || true
    echo "обычный сайт:"; dig +short @"$PUB" ya.ru | head -2 || true
    exit 0
fi

[[ $# -ge 1 ]] || { echo "использование: setup-dns.sh <ip узла> [<ip узла> ...]"; exit 1; }
NODE_IPS=("$@")

PUBLIC_IP=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
[[ -n "$PUBLIC_IP" ]] || { echo "не понял публичный адрес узла"; exit 1; }

echo "== unbound"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q unbound dnsutils >/dev/null
# resolv.conf узла не трогаем: у него свой резолвер systemd, наш — для людей.
systemctl disable --now unbound-resolvconf.service >/dev/null 2>&1 || true

echo "== список рекламы"
cat > "$UPDATER" <<'SH'
#!/usr/bin/env bash
# Свежий RPZ-список рекламы; при любой заминке оставляем прежний.
set -u
URL="__RPZ_URL__"
FILE="__RPZ_FILE__"
TMP="$FILE.new"
if curl -fsSL -m 120 -o "$TMP" "$URL" && [ "$(wc -c < "$TMP")" -gt 200000 ] && grep -q "CNAME" "$TMP"; then
    mv -f "$TMP" "$FILE"
    chown unbound:unbound "$FILE" 2>/dev/null || true
    systemctl reload unbound
    logger -t prosto-dns "список рекламы обновлён: $(grep -c CNAME "$FILE") правил"
else
    rm -f "$TMP"
    logger -t prosto-dns "список рекламы не обновился, остаёмся на прежнем"
    exit 1
fi
SH
sed -i "s#__RPZ_URL__#$RPZ_URL#; s#__RPZ_FILE__#$RPZ_FILE#" "$UPDATER"
chmod 0755 "$UPDATER"
install -d -o unbound -g unbound /var/lib/unbound
if [[ ! -s "$RPZ_FILE" ]]; then
    curl -fsSL -m 120 -o "$RPZ_FILE" "$RPZ_URL"
    chown unbound:unbound "$RPZ_FILE"
fi
echo "  правил в списке: $(grep -c CNAME "$RPZ_FILE")"

cat > /etc/systemd/system/prosto-dns-update.service <<UNIT
[Unit]
Description=Prosto VPN — обновление списка рекламы для DNS
[Service]
Type=oneshot
ExecStart=$UPDATER
UNIT
cat > /etc/systemd/system/prosto-dns-update.timer <<UNIT
[Unit]
Description=Prosto VPN — список рекламы раз в сутки
[Timer]
OnCalendar=*-*-* 05:20:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
UNIT

echo "== конфиг"
{
    echo "server:"
    echo "    # Публичный адрес узла и шлюзы туннелей AmneziaWG. ip-freebind —"
    echo "    # чтобы Unbound поднимался и до того, как поднялись интерфейсы awg."
    echo "    interface: $PUBLIC_IP"
    for addr in $(grep -h '^Address' /etc/amnezia/amneziawg/awg*.conf 2>/dev/null | sed 's/.*= *//; s#/.*##'); do
        echo "    interface: $addr"
    done
    echo "    ip-freebind: yes"
    echo "    port: 53"
    echo "    do-ip6: no"
    echo "    # Отвечаем только своим: подсети туннелей и наши узлы."
    echo "    access-control: 127.0.0.0/8 allow"
    echo "    access-control: 10.0.0.0/8 allow"
    for ip in "${NODE_IPS[@]}"; do
        echo "    access-control: $ip/32 allow"
    done
    echo "    access-control: 0.0.0.0/0 refuse"
    echo "    hide-identity: yes"
    echo "    hide-version: yes"
    echo "    qname-minimisation: yes"
    echo "    prefetch: yes"
    echo "    cache-min-ttl: 60"
    echo "    msg-cache-size: 64m"
    echo "    rrset-cache-size: 128m"
    echo "    num-threads: 1"
    echo "    module-config: \"respip validator iterator\""
    echo ""
    echo "rpz:"
    echo "    name: \"prosto-ads\""
    echo "    zonefile: \"$RPZ_FILE\""
    echo "    rpz-action-override: nxdomain"
    echo "    rpz-log: no"
} > "$CONF"
unbound-checkconf >/dev/null

echo "== доступ"
# Клиенты приходят через туннель (источник 10.x), Happ с балансировкой —
# через другие наши узлы. Снаружи порт 53 закрыт.
ufw allow from 10.0.0.0/8 to any port 53 comment 'DNS без рекламы (туннели)' >/dev/null
for ip in "${NODE_IPS[@]}"; do
    ufw allow from "$ip" to any port 53 comment 'DNS без рекламы (наши узлы)' >/dev/null
done

systemctl daemon-reload
systemctl enable --now prosto-dns-update.timer >/dev/null
systemctl enable unbound >/dev/null 2>&1 || true
systemctl restart unbound
sleep 2
systemctl is-active unbound

echo "== проверка"
# mc.yandex.ru — счётчик Метрики, он в списке всегда; апекс doubleclick.net в списке нет.
echo "  реклама → $(dig +short +time=3 @"$PUBLIC_IP" mc.yandex.ru | head -1 || true) (пусто = NXDOMAIN, так и надо)"
echo "  ya.ru   → $(dig +short +time=3 @"$PUBLIC_IP" ya.ru | head -1)"
echo "готово: DNS без рекламы на $PUBLIC_IP"
