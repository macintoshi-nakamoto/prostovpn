"""
Подписка для Happ в виде готовых конфигов Xray (JSON), а не голых ссылок.

Голая ссылка vless:// даёт приложению только адрес и ключ: весь трафик
идёт в туннель, сервер человек выбирает руками, на сотовой сети он сам
должен догадаться переключиться. Полный конфиг решает это на нашей стороне:

* российские сайты и адреса идут напрямую (`geosite:category-ru`,
  `geoip:ru`) — банки, госуслуги и маркетплейсы не ломаются от чужого IP,
  а туннель не тащит лишнее;
* «Лучший сервер» — балансировщик по всем узлам и обоим протоколам:
  приложение раз в минуту меряет каждый выход и держит трафик на живом,
  само уходя с задушенного узла или протокола;
* название с флагом страны и подпись протокола — так Happ рисует флаг
  слева, а не значок «интернет».

Happ применяет JSON как есть: его собственные правила маршрутизации к
такому конфигу не подмешиваются (документация happ.su), поэтому всё, что
нужно, должно быть внутри. Синтаксис выхода Hysteria2 и наблюдателя взят
из рабочих конфигов Happ — в чистом Xray их нет.
"""

from __future__ import annotations

import copy

from . import geo

# Локальные входы приложения — так же, как Happ пишет их сам.
INBOUNDS: list[dict] = [
    {
        "tag": "socks",
        "listen": "127.0.0.1",
        "port": 10808,
        "protocol": "socks",
        "settings": {"auth": "noauth", "udp": True},
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": False},
    },
    {
        "tag": "http",
        "listen": "127.0.0.1",
        "port": 10809,
        "protocol": "http",
        "settings": {"allowTransparent": False},
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": False},
    },
]

DNS: dict = {"servers": ["1.1.1.1", "1.0.0.1"], "queryStrategy": "UseIP"}

# Что не заворачивать в туннель. Порядок важен: правила читаются сверху.
DIRECT_RULES: list[dict] = [
    {"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"},
    {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
    {"type": "field", "domain": ["domain:2ip.ru", "geosite:category-ru"], "outboundTag": "direct"},
    {"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"},
]

TAIL_OUTBOUNDS: list[dict] = [
    {"protocol": "freedom", "tag": "direct"},
    {"protocol": "blackhole", "tag": "block"},
]

BEST_TAG = "best_server"


def reality_outbound(
    tag: str,
    host: str,
    port: int,
    identity: str,
    *,
    public_key: str,
    short_id: str,
    server_name: str,
    fingerprint: str = "chrome",
    flow: str = "xtls-rprx-vision",
) -> dict:
    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": host,
                    "port": int(port),
                    "users": [{"id": identity, "encryption": "none", "flow": flow}],
                }
            ]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "tcpSettings": {},
            "realitySettings": {
                "fingerprint": fingerprint,
                "publicKey": public_key,
                "serverName": server_name,
                "shortId": short_id,
            },
        },
    }


def hysteria_outbound(tag: str, host: str, port: int, identity: str, *, server_name: str) -> dict:
    """Выход Hysteria2 в записи Happ. Сертификат узла самоподписанный — allowInsecure."""
    return {
        "tag": tag,
        "protocol": "hysteria",
        "settings": {"address": host, "port": int(port), "version": 2},
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                "alpn": ["h3"],
                "serverName": server_name,
                "fingerprint": "chrome",
                "enableSessionResumption": False,
                "allowInsecure": True,
            },
            "hysteriaSettings": {"auth": identity, "version": 2},
            "finalmask": {"quicParams": {"congestion": "bbr", "debug": False}},
        },
    }


def config(remarks: str, outbounds: list[dict], *, description: str | None = None) -> dict:
    """Конфиг с одним или несколькими выходами; несколько — под балансировщик."""
    out = {
        "remarks": remarks,
        "log": {"loglevel": "warning"},
        "dns": copy.deepcopy(DNS),
        "inbounds": copy.deepcopy(INBOUNDS),
        "outbounds": [*copy.deepcopy(outbounds), *copy.deepcopy(TAIL_OUTBOUNDS)],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "domainMatcher": "hybrid",
            "rules": copy.deepcopy(DIRECT_RULES),
        },
    }
    if description:
        out["meta"] = {"serverDescription": description}

    if len(outbounds) > 1:
        # Наблюдатель раз в минуту дёргает generate_204 через каждый выход;
        # балансировщик держит трафик на самом быстром из живых и меняет
        # его, когда тот начинает проседать. Никого не осталось — напрямую:
        # русские сайты и так шли мимо, а «нет интернета вовсе» хуже.
        out["burstObservatory"] = {
            "subjectSelector": ["proxy"],
            "pingConfig": {
                "destination": "http://www.gstatic.com/generate_204",
                "interval": "1m",
                "timeout": "3s",
                "sampling": 1,
                "connectivity": "",
            },
        }
        out["routing"]["balancers"] = [
            {
                "tag": BEST_TAG,
                "selector": ["proxy"],
                "fallbackTag": "direct",
                "strategy": {
                    "type": "leastLoad",
                    "settings": {
                        "expected": 2,
                        "maxRTT": "1s",
                        "tolerance": 0.01,
                        "baselines": ["1s"],
                    },
                },
            }
        ]
        out["routing"]["rules"].append(
            {"type": "field", "network": "tcp,udp", "balancerTag": BEST_TAG}
        )
    return out


def name(country_code: str | None, label: str) -> str:
    return f"{geo.flag(country_code)} {label}".strip()
