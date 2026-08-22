# Reality на общем 443 через SNI-роутинг (боевая раскладка)

На узле один внешний IP, и он же — A-запись prostovpn.cc. Reality нужен на 443
(многие сети пропускают только 80/443), но 443 держит nginx, обслуживающий сайт,
подписку и второй продукт startpayments.link (за Cloudflare).

Решение: nginx-stream + ssl_preread на 443 как SNI-разводящий. nginx остаётся
фронтом, поэтому сайты переживают падение xray.

## Как это собрано
1. `apt install libnginx-mod-stream` (модуль в сборке был как dynamic).
2. Внешний 443 держит stream-сервер (`stream-reality.conf`): по $ssl_preread_server_name
   донорские имена (www.google.com) уходят в `127.0.0.1:8444` (xray Reality),
   всё остальное и ПУСТОЙ SNI (старые сборки по IP) — в `127.0.0.1:4443` (nginx http).
   `proxy_protocol on` — чтобы и nginx, и xray видели адрес клиента, а не петли.
3. Все http-vhost переехали с внешнего 443 на `127.0.0.1:4443 ssl proxy_protocol`.
   real_ip: panel/sub — `real_ip_header proxy_protocol`; startpay за CF —
   добавлен `set_real_ip_from 127.0.0.1`, заголовок остался `CF-Connecting-IP`.
4. xray: vless-точка входа с listen_addr=127.0.0.1, listen_port=8444,
   accept_proxy=true, advertise_port=443 (в подписке отдаётся 443, а не 8444).
   Конфиг пишет панель (services/xray.py), не руками.

## Проверено на бою
- 443 SNI=google → сертификат Google (Google Trust Services);
- 443 SNI=prostovpn.cc → наш Let's Encrypt;
- 443 без SNI (по IP) → 200 (старые сборки живы);
- реальный IP клиента доходит до панели (session.ip = настоящий адрес, не 127.0.0.1);
- prostovpn.cc / www / startpayments.link → 200.

## Откат
Восстановить снимок `/root/nginx-before-reality-*/nginx`, `systemctl reload nginx`,
в панели вывести точку входа vless-front-443 в retired. xray на 2053 при этом
продолжает работать напрямую.
