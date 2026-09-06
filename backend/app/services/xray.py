from __future__ import annotations

import json
import logging
import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, provisioning
from ..models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Server,
    User,
    UserEndpointCred,
    utcnow,
)
from .errors import PanelError

log = logging.getLogger("panel.xray")

XRAY_DIR = "/opt/prosto-xray"
XRAY_BIN = f"{XRAY_DIR}/xray"
XRAY_CONFIG = f"{XRAY_DIR}/config.json"
XRAY_LOCK = f"{XRAY_DIR}/.config.lock"
XRAY_UNIT = "prosto-xray"
SERVICE_USER = "prosto-xray"

API_PORT = 10085

FLOW = "xtls-rprx-vision"


def _label() -> str:
    return secrets.token_hex(8)


def generate_reality_keypair(server: Server) -> tuple[str, str]:
    out = provisioning.run_over_ssh(server, f"{XRAY_BIN} x25519")
    private = public = ""
    for line in out.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        flat = label.lower().replace(" ", "").replace("_", "")
        value = value.strip()
        if not value:
            continue
        if "privatekey" in flat:
            private = value
        elif "publickey" in flat:
            public = value
    if not private or not public:
        raise PanelError(f"xray не вернул пару ключей Reality: {out!r}")
    return private, public


def create_vless_endpoint(
    db: OrmSession,
    server: Server,
    *,
    listen_port: int,
    server_names: list[str],
    dest: str | None = None,
    handle: str | None = None,
    capacity: int | None = None,
    note: str | None = None,
    listen_addr: str = "0.0.0.0",
    accept_proxy: bool = False,
    advertise_port: int | None = None,
) -> NodeEndpoint:
    if not crypto.available():
        raise PanelError(
            "не задан PANEL_SECRETS_KEY — без него креды VLESS негде хранить безопасно"
        )
    if not server_names:
        raise PanelError("нужен хотя бы один донорский домен")

    listen_port = int(listen_port)
    if not (0 < listen_port < 65536):
        raise PanelError("порт вне диапазона")
    # Другие точки входа мешают только своим транспортом: Reality живёт на
    # TCP, AWG — на UDP, и 443 у них общий лишь по номеру. Пока проверка была
    # общей, объявленный у AWG запасной 443/UDP закрывал дорогу Reality на
    # 443/TCP, хотя на узле они спокойно уживаются: xray слушает TCP, а
    # iptables заворачивает UDP на awg.
    for ep in server.endpoints:
        if (ep.transport or "udp") != "tcp":
            continue
        if ep.listen_port == listen_port or listen_port in ep.alt_port_list():
            raise PanelError(f"порт {listen_port} на этом узле уже занят по TCP")

    # А вот основной порт узла — особый случай, и дело не в сокетах. На нём
    # физически сидит awg, туда же ведут все редиректы запасных портов, и
    # вешать рядом Reality значит запутать и себя, и разбор трафика. Запасные
    # порты этого не касаются: они всего лишь UDP-редиректы, TCP там свободен.
    if listen_port == server.port:
        raise PanelError(
            f"порт {listen_port} — основной порт узла, на нём слушает AmneziaWG"
        )

    handle = handle or f"vless-reality-{listen_port}"
    if any(ep.handle == handle for ep in server.endpoints):
        raise PanelError(f"точка входа {handle} уже есть")

    private_key, public_key = generate_reality_keypair(server)
    short_ids = [secrets.token_hex(4), secrets.token_hex(8)]

    endpoint = NodeEndpoint(
        server_id=server.id,
        kind=EndpointKind.VLESS,
        transport="tcp",
        handle=handle,
        listen_port=listen_port,
        alt_ports="",
        subnet=None,
        params={
            "security": "reality",
            "flow": FLOW,
            "public_key": public_key,
            "short_ids": short_ids,
            "server_names": list(server_names),
            "dest": dest or f"{server_names[0]}:443",
            "fingerprint": "chrome",
            "api_port": API_PORT,
            "listen_addr": listen_addr,
            "accept_proxy": bool(accept_proxy),
            "advertise_port": advertise_port,
        },
        secret_enc=crypto.encrypt(private_key),
        priority=100,
        capacity=capacity,
        state=EndpointState.DRAFT,
        counter_mode="absolute",
        note=note,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    log.info("заведена точка входа %s (порт %s, донор %s)", handle, listen_port, server_names[0])
    return endpoint


def _host_cidr(host: str) -> str | None:
    import ipaddress

    try:
        address = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return None
    return f"{address}/{'32' if address.version == 4 else '128'}"


def build_config(db: OrmSession, server: Server) -> dict:
    inbounds: list[dict] = []
    inbounds.append(
        {
            "tag": "api-in",
            "listen": "127.0.0.1",
            "port": API_PORT,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        }
    )

    endpoints = db.scalars(
        select(NodeEndpoint)
        .where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
        )
        .order_by(NodeEndpoint.id)
    )
    for endpoint in endpoints:
        if endpoint.state == EndpointState.RETIRED:
            continue
        params = endpoint.params or {}
        private_key = ""
        if endpoint.secret_enc:
            try:
                private_key = crypto.decrypt(endpoint.secret_enc)
            except crypto.SecretsUnavailable:
                log.error("точка входа %s: приватный ключ Reality не читается", endpoint.handle)
                continue

        base_clients = []
        for cred in db.scalars(
            select(UserEndpointCred).where(
                UserEndpointCred.endpoint_id == endpoint.id,
                UserEndpointCred.revoked_at.is_(None),
            )
        ):
            identity = cred.identity
            if not identity:
                continue
            base_clients.append({"id": identity, "email": cred.label})

        for spec in inbound_specs(endpoint):
            clients = [{**c, "flow": spec["flow"]} for c in base_clients]
            if spec["network"] == "tcp":
                stream_settings = {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": params.get("dest", ""),
                        "serverNames": params.get("server_names", []),
                        "privateKey": private_key,
                        "shortIds": params.get("short_ids", []),
                    },
                }
                if params.get("accept_proxy"):
                    stream_settings["tcpSettings"] = {"acceptProxyProtocol": True}
            else:
                # Обычный TLS с настоящим сертификатом своего домена — то, чем
                # отвечает Reality всем, кто пришёл без его ключа, и что
                # видит DPI: сайт, чьё имя совпадает с адресом.
                tls = params.get("tls") or {}
                stream_settings = {
                    "network": spec["network"],
                    "security": "tls",
                    "tlsSettings": {
                        "certificates": [
                            {"certificateFile": tls.get("cert", ""), "keyFile": tls.get("key", "")}
                        ],
                        "alpn": spec["alpn"],
                        "minVersion": "1.2",
                    },
                }
                if spec["network"] == "xhttp":
                    stream_settings["xhttpSettings"] = {"path": spec["path"]}
                else:
                    stream_settings["wsSettings"] = {"path": spec["path"]}

            inbounds.append(
                {
                    "tag": spec["tag"],
                    "listen": spec["listen"],
                    "port": spec["port"],
                    "protocol": "vless",
                    "settings": {"clients": clients, "decryption": "none"},
                    "streamSettings": stream_settings,
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
                }
            )

    return {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "services": ["HandlerService", "StatsService"]},
        "stats": {},
        "policy": {
            # statsUserOnline — счётчик живых соединений на учётку
            # (активность за последние 20 секунд): по нему панель видит
            # «в VPN» у Happ и подобных даже без заметного трафика.
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True,
                    "statsUserOnline": True,
                }
            },
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "inbounds": inbounds,
        "outbounds": [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"},
                {
                    "type": "field",
                    "ip": ["geoip:private", "127.0.0.0/8", "10.8.0.0/16"],
                    "outboundTag": "block",
                },
                *(
                    [
                        {
                            "type": "field",
                            "ip": [_host_cidr(server.host)],
                            "port": "22,22222,8000,8080,8081,8443,10085",
                            "outboundTag": "block",
                        }
                    ]
                    if _host_cidr(server.host)
                    else []
                ),
                {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
            ],
        },
    }


def apply_config(db: OrmSession, server: Server, *, restart: bool = True) -> None:
    payload = json.dumps(build_config(db, server), ensure_ascii=False, indent=2)
    script = f"""set -e
exec 9>>{XRAY_LOCK}
flock 9
umask 077
tmp="$(mktemp {XRAY_DIR}/.config.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp"
# Битый JSON демон не переживёт: он не поднимется вовсе, а это отказ всех
# доступов узла разом. Проверяем ДО подмены.
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$tmp"
# Владельца и режим восстанавливаем явно: новый файл создан от root, а демон
# работает под своим пользователем и с 0640 просто не смог бы его прочитать.
chown --reference={XRAY_CONFIG} "$tmp" 2>/dev/null || chown root:{SERVICE_USER} "$tmp"
chmod 0640 "$tmp"
mv "$tmp" {XRAY_CONFIG}
sync
"""
    provisioning.run_over_ssh_with_input(server, script, payload)
    if restart:
        provisioning.run_over_ssh(server, f"systemctl restart {XRAY_UNIT}")


def _api_addr(endpoint: NodeEndpoint) -> str:
    port = (endpoint.params or {}).get("api_port") or API_PORT
    return f"127.0.0.1:{int(port)}"


def _inbound_tag(endpoint: NodeEndpoint) -> str:
    return f"in-{endpoint.handle}"


def inbound_specs(endpoint: NodeEndpoint) -> list[dict]:
    """
    Все входы xray одной точки VLESS: Reality на её порту и, если у точки
    есть настоящий сертификат (params.tls), ещё XHTTP+TLS на loopback (в него
    Reality отдаёт всех, кто пришёл без ключа, — так один 443 обслуживает и
    Reality, и обычный TLS) и WS+TLS на своём порту. Учётки во всех входах
    одни и те же, различается только flow: vision живёт лишь на TCP-Reality.
    """
    params = endpoint.params or {}
    specs = [
        {
            "tag": _inbound_tag(endpoint),
            "listen": params.get("listen_addr") or "0.0.0.0",
            "port": int(endpoint.listen_port),
            "network": "tcp",
            "flow": params.get("flow", FLOW),
            "path": "",
            "alpn": [],
        }
    ]
    tls = params.get("tls") or {}
    if tls.get("cert") and tls.get("key"):
        xhttp = params.get("xhttp") or {}
        if xhttp.get("port"):
            specs.append(
                {
                    "tag": f"{_inbound_tag(endpoint)}-xhttp",
                    "listen": xhttp.get("listen") or "127.0.0.1",
                    "port": int(xhttp["port"]),
                    "network": "xhttp",
                    "flow": "",
                    "path": xhttp.get("path") or "/",
                    "alpn": ["h2", "http/1.1"],
                }
            )
        ws = params.get("ws") or {}
        if ws.get("port"):
            specs.append(
                {
                    "tag": f"{_inbound_tag(endpoint)}-ws",
                    "listen": ws.get("listen") or "0.0.0.0",
                    "port": int(ws["port"]),
                    "network": "ws",
                    "flow": "",
                    "path": ws.get("path") or "/",
                    "alpn": ["http/1.1"],
                }
            )
    return specs


def _client_of(cred: UserEndpointCred, endpoint: NodeEndpoint) -> dict | None:
    identity = cred.identity
    if not identity:
        return None
    return {"id": identity, "email": cred.label}


_TOTAL = re.compile(r"(Added|Removed) (\d+) user\(s\) in total")


def _count(out: str, word: str) -> int:
    """«Added 1 user(s) in total.» → 1; строки нет → -1."""
    for match in _TOTAL.finditer(out or ""):
        if match.group(1) == word:
            return int(match.group(2))
    return -1


def hot_add(server: Server, endpoint: NodeEndpoint, clients: list[dict]) -> bool:
    """
    Добавляет учётки в работающий xray через его API, без перезапуска.

    Перезапуск рвёт все соединения Reality на узле разом, а учётки
    выдаются часто: каждый новый ключ в Happ ронял бы всех, кто уже
    сидит на этом узле. API-вход ждёт тот же JSON, что и конфиг, но
    только с клиентами; порт и адрес обязательны — без них xray не
    сопоставит вход и молча ничего не добавит.

    Учётка, которая на узле уже есть, — не ошибка: так бывает после
    перезапуска по свежему конфигу, где она уже записана.
    """
    if not clients:
        return True
    specs = inbound_specs(endpoint)
    payload = json.dumps(
        {
            "inbounds": [
                {
                    "tag": spec["tag"],
                    "listen": spec["listen"],
                    "port": spec["port"],
                    "protocol": "vless",
                    "settings": {
                        "clients": [{**c, "flow": spec["flow"]} for c in clients],
                        "decryption": "none",
                    },
                }
                for spec in specs
            ]
        },
        ensure_ascii=False,
    )
    script = f"""set -e
umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp"
{XRAY_BIN} api adu -s {_api_addr(endpoint)} -t 5 "$tmp" 2>&1 || true
"""
    out = provisioning.run_over_ssh_with_input(server, script, payload)
    added = _count(out, "Added")
    present = (out or "").count("already exists")
    ok = added >= 0 and added + present >= len(clients) * len(specs)
    if not ok:
        log.warning(
            "узел %s: xray не принял учётки через API: %s", server.name, (out or "").strip()[-400:]
        )
    return ok


def hot_remove(server: Server, endpoint: NodeEndpoint, emails: list[str]) -> bool:
    """Снимает учётки с работающего xray. Уже отсутствующие — не ошибка."""
    emails = [e for e in emails if e]
    if not emails:
        return True
    args = " ".join(provisioning._quote(e) for e in emails)
    command = " ; ".join(
        f"{XRAY_BIN} api rmu -s {_api_addr(endpoint)} -t 5 "
        f"-tag={provisioning._quote(spec['tag'])} {args} 2>&1"
        for spec in inbound_specs(endpoint)
    ) + " ; true"
    out = provisioning.run_over_ssh(server, command)
    removed = sum(int(m.group(2)) for m in _TOTAL.finditer(out or "") if m.group(1) == "Removed")
    missing = (out or "").count("not found")
    ok = removed + missing >= len(emails) * len(inbound_specs(endpoint))
    if not ok:
        log.warning(
            "узел %s: xray не снял учётки через API: %s", server.name, (out or "").strip()[-400:]
        )
    return ok


def _mark_dirty(db: OrmSession, endpoint: NodeEndpoint) -> None:
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()


def push_to_node(
    db: OrmSession,
    server: Server,
    *,
    add: list[tuple[NodeEndpoint, dict]] | None = None,
    remove: list[tuple[NodeEndpoint, str]] | None = None,
) -> bool:
    """
    Доносит конфиг VLESS до узла.

    Без add/remove — полный перезапуск xray: так применяются изменения самих
    точек входа (донор, ключи, порт). С ними — конфиг на диск пишется тот же
    (после перезагрузки узел поднимется в актуальном виде), а живому демону
    учётки досылаются через API, и чужие соединения не рвутся. Не вышло
    через API — перезапуск, как раньше: доступ важнее плавности.
    """
    hot = add is not None or remove is not None
    try:
        apply_config(db, server, restart=not hot)
    except Exception as exc:
        log.warning("узел %s: конфиг VLESS не записан (%s), починим обходом", server.name, exc)
        return False

    if hot:
        live = True
        try:
            adds: dict[int, tuple[NodeEndpoint, list[dict]]] = {}
            for endpoint, client in add or []:
                adds.setdefault(endpoint.id, (endpoint, []))[1].append(client)
            for endpoint, clients in adds.values():
                live = hot_add(server, endpoint, clients) and live
            gone: dict[int, tuple[NodeEndpoint, list[str]]] = {}
            for endpoint, email in remove or []:
                gone.setdefault(endpoint.id, (endpoint, []))[1].append(email)
            for endpoint, emails in gone.values():
                live = hot_remove(server, endpoint, emails) and live
        except Exception as exc:
            log.warning("узел %s: API xray недоступен (%s), перезапускаем", server.name, exc)
            live = False
        if not live:
            try:
                provisioning.run_over_ssh(server, f"systemctl restart {XRAY_UNIT}")
            except Exception as exc:
                log.warning("узел %s: xray не перезапущен (%s), починим обходом", server.name, exc)
                return False

    applied = utcnow()
    for endpoint in db.scalars(
        select(NodeEndpoint).where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
        )
    ):
        params = dict(endpoint.params or {})
        params["applied_rev"] = endpoint.rev
        params["applied_at"] = applied.isoformat()
        endpoint.params = params
    db.commit()
    return True


def sync_pending(db: OrmSession, server: Server) -> bool:
    stale = [
        endpoint
        for endpoint in db.scalars(
            select(NodeEndpoint).where(
                NodeEndpoint.server_id == server.id,
                NodeEndpoint.kind == EndpointKind.VLESS,
                NodeEndpoint.state != EndpointState.DRAFT,
            )
        )
        if (endpoint.params or {}).get("applied_rev") != endpoint.rev
    ]
    if not stale:
        return True
    log.info("узел %s: досылаем конфиг VLESS (%d точек входа)", server.name, len(stale))
    return push_to_node(db, server)


def issue_cred(
    db: OrmSession,
    user: User,
    server: Server,
    endpoint: NodeEndpoint,
    device_id: str = "",
) -> UserEndpointCred:
    device_id = (device_id or "").strip()
    existing = db.scalar(
        select(UserEndpointCred).where(
            UserEndpointCred.endpoint_id == endpoint.id,
            UserEndpointCred.user_id == user.id,
            UserEndpointCred.device_id == device_id,
        )
    )
    if existing is not None and existing.revoked_at is None:
        return existing

    if not crypto.available():
        raise PanelError("не задан PANEL_SECRETS_KEY — выдать доступ VLESS нечем")

    params = endpoint.params or {}
    short_ids = params.get("short_ids") or [""]

    if existing is not None:
        cred = existing
        cred.revoked_at = None
    else:
        cred = UserEndpointCred(
            user_id=user.id,
            server_id=server.id,
            endpoint_id=endpoint.id,
            device_id=device_id,
        )
        db.add(cred)

    cred.cred_type = "vless"
    # Отозванной учётке возвращаем ЕЁ ЖЕ UUID и short_id: vless-ссылка у
    # человека сохранена, и после разморозки или продления она должна
    # заработать как была, без переимпорта.
    if not cred.identity_enc:
        identity = str(uuid.uuid4())
        cred.identity_enc = crypto.encrypt(identity)
        cred.identity_fp = crypto.blind_index(identity)
    cred.label = cred.label or _label()
    if not cred.extra:
        cred.extra = {
            "flow": params.get("flow", FLOW),
            "short_id": secrets.choice(short_ids),
        }
    db.commit()
    db.refresh(cred)

    # Точка входа на узле в актуальном виде — досылаем одну учётку через
    # API. Если же у неё накопились неприменённые изменения, нужен полный
    # перезапуск, и учётка уедет вместе с ними.
    was_live = is_on_node(endpoint)
    _mark_dirty(db, endpoint)
    client = _client_of(cred, endpoint)
    if was_live and client is not None:
        push_to_node(db, server, add=[(endpoint, client)])
    else:
        push_to_node(db, server)
    return cred


def is_on_node(endpoint: NodeEndpoint) -> bool:
    return (endpoint.params or {}).get("applied_rev") == endpoint.rev


def revoke_cred(db: OrmSession, cred: UserEndpointCred) -> None:
    cred.revoked_at = utcnow()
    db.commit()
    endpoint = db.get(NodeEndpoint, cred.endpoint_id)
    if endpoint is not None:
        was_live = is_on_node(endpoint)
        _mark_dirty(db, endpoint)
        if was_live and cred.label:
            push_to_node(db, endpoint.server, remove=[(endpoint, cred.label)])
        else:
            push_to_node(db, endpoint.server)
        # Hysteria2 спрашивает панель только при подключении — живую сессию
        # отозванного надо выкинуть отдельно.
        from . import hy2

        hy2.kick(endpoint.server, [cred.label or ""])


def revoke_for_user(db: OrmSession, user_id: int, device_id: str | None = None) -> int:
    query = select(UserEndpointCred).where(
        UserEndpointCred.user_id == user_id,
        UserEndpointCred.revoked_at.is_(None),
    )
    if device_id is not None:
        query = query.where(UserEndpointCred.device_id == (device_id or "").strip())
    rows = list(db.scalars(query))
    if not rows:
        return 0

    now = utcnow()
    server_ids = set()
    endpoint_ids = set()
    for cred in rows:
        cred.revoked_at = now
        server_ids.add(cred.server_id)
        endpoint_ids.add(cred.endpoint_id)
    db.commit()

    # Снимаем через API, пока точки входа на узле в актуальном виде; хоть
    # одна отстала — этот узел получает полный перезапуск.
    hot_servers = set(server_ids)
    removals: dict[int, list[tuple[NodeEndpoint, str]]] = {sid: [] for sid in server_ids}
    for endpoint_id in endpoint_ids:
        endpoint = db.get(NodeEndpoint, endpoint_id)
        if endpoint is None:
            continue
        if not is_on_node(endpoint):
            hot_servers.discard(endpoint.server_id)
        _mark_dirty(db, endpoint)
        for cred in rows:
            if cred.endpoint_id == endpoint.id and cred.label:
                removals[endpoint.server_id].append((endpoint, cred.label))
    for server_id in server_ids:
        server = db.get(Server, server_id)
        if server is None:
            continue
        if server_id in hot_servers:
            push_to_node(db, server, remove=removals[server_id])
        else:
            push_to_node(db, server)
        from . import hy2

        hy2.kick(server, [label for _endpoint, label in removals[server_id]])
    return len(rows)


def live_creds(db: OrmSession, user: User, server: Server, device_id: str = "") -> list[UserEndpointCred]:
    device_id = (device_id or "").strip()
    return list(
        db.scalars(
            select(UserEndpointCred).where(
                UserEndpointCred.user_id == user.id,
                UserEndpointCred.server_id == server.id,
                UserEndpointCred.device_id == device_id,
                UserEndpointCred.revoked_at.is_(None),
            )
        )
    )


def _parse_stats(raw: str) -> dict[str, tuple[int, int]]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}

    out: dict[str, list[int]] = {}
    for item in data.get("stat") or []:
        name = item.get("name") or ""
        if not name.startswith("user>>>"):
            continue
        parts = name.split(">>>")
        if len(parts) < 4:
            continue
        label, direction = parts[1], parts[-1]
        value = int(item.get("value") or 0)
        bucket = out.setdefault(label, [0, 0])
        if direction == "uplink":
            bucket[0] = value
        elif direction == "downlink":
            bucket[1] = value
    return {label: (values[0], values[1]) for label, values in out.items()}


ONLINE_MARK = "@@ONLINE@@"


def _parse_online(raw: str) -> set[str]:
    """
    Учётки с живым соединением прямо сейчас — ответ `xray api
    statsgetallonlineusers`: `{"users": ["user>>><label>>>>online", …]}`
    (нужна политика statsUserOnline в конфиге; обычный statsquery эти
    счётчики не отдаёт — проверено на Xray 26.3.27).
    """
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return set()
    online: set[str] = set()
    for name in (data.get("users") if isinstance(data, dict) else None) or []:
        parts = str(name).split(">>>")
        if len(parts) == 3 and parts[0] == "user" and parts[2] == "online" and parts[1]:
            online.add(parts[1])
    return online


IPS_MARK = "@@IPS@@"


def _parse_ips(raw: str) -> dict[str, set[str]]:
    """
    С каких адресов сидит каждая учётка прямо сейчас.

    Ответ `xray api statsonlineiplist` — `{"ips": {"1.2.3.4": <время>}, …}`,
    перед каждым идёт метка `@@U@@<учётка>`. Считаем именно адреса, а не
    соединения: телефон держит их пачками, и по ним не понять, сколько
    человек за ключом.
    """
    out: dict[str, set[str]] = {}
    label = ""
    chunk: list[str] = []

    def flush() -> None:
        if not label or not chunk:
            return
        try:
            data = json.loads("".join(chunk))
        except json.JSONDecodeError:
            return
        ips = data.get("ips") if isinstance(data, dict) else None
        if isinstance(ips, dict) and ips:
            out.setdefault(label, set()).update(str(ip) for ip in ips)

    for line in (raw or "").splitlines():
        if line.startswith("@@U@@"):
            flush()
            label = line[len("@@U@@") :].strip()
            chunk = []
            continue
        chunk.append(line)
    flush()
    return out


def _split_stats(raw: str) -> tuple[str, str]:
    """Две выдачи одной командой: счётчики трафика и список онлайна."""
    if ONLINE_MARK not in (raw or ""):
        return raw or "", ""
    head, tail = raw.split(ONLINE_MARK, 1)
    return head, tail


def sync_traffic(db: OrmSession, server: Server) -> dict[str, object]:
    from sqlalchemy import update as sql_update

    from ..models import TrafficSample

    has_vless = db.scalar(
        select(NodeEndpoint.id).where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
            NodeEndpoint.state != EndpointState.RETIRED,
        )
    )
    if not has_vless:
        return {"server_id": server.id, "skipped": "нет точек входа VLESS"}

    try:
        # Третьим куском — адреса, с которых сидит каждая живая учётка.
        # Цикл крутится на узле, чтобы не делать по заходу SSH на человека.
        raw = provisioning.run_over_ssh(
            server,
            f"{XRAY_BIN} api statsquery --server=127.0.0.1:{API_PORT} "
            f"-pattern 'user>>>' -reset=false; echo '{ONLINE_MARK}'; "
            f"{XRAY_BIN} api statsgetallonlineusers --server=127.0.0.1:{API_PORT} 2>/dev/null; "
            f"echo '{IPS_MARK}'; "
            f"for u in $({XRAY_BIN} api statsgetallonlineusers --server=127.0.0.1:{API_PORT} "
            f"2>/dev/null | grep -o 'user>>>[^>]*' | cut -d'>' -f4 | sort -u); do "
            f"echo \"@@U@@$u\"; {XRAY_BIN} api statsonlineiplist "
            f"--server=127.0.0.1:{API_PORT} -email \"$u\" 2>/dev/null; done",
        )
    except Exception as exc:
        log.warning("узел %s: счётчики VLESS не сняты: %s", server.name, exc)
        return {"server_id": server.id, "error": str(exc)}

    stats_raw, online_raw = _split_stats(raw)
    online_raw, ips_raw = (
        online_raw.split(IPS_MARK, 1) if IPS_MARK in online_raw else (online_raw, "")
    )
    return apply_stats(db, server, stats_raw, online_raw, ips_raw)


def apply_stats(
    db: OrmSession, server: Server, stats_raw: str, online_raw: str, ips_raw: str
) -> dict[str, object]:
    """
    Зачисляет выдачи `xray api statsquery / statsgetallonlineusers /
    statsonlineiplist` — снятые по SSH или присланные агентом узла. Счётчики
    абсолютные, дельта считается от базы, поэтому источник можно менять.
    """
    from sqlalchemy import update as sql_update

    from ..models import TrafficSample

    counters = _parse_stats(stats_raw)
    addresses = _parse_ips(ips_raw)
    # Живые соединения — тем же заходом по SSH. Трафик за минуту может быть
    # нулевым (открытая вкладка, ничего не грузится), а соединение при
    # этом есть — раньше такой человек через три минуты «отключался».
    online = _parse_online(online_raw)
    if not counters and not online:
        return {"server_id": server.id, "peers": 0, "added_bytes": 0}

    now = utcnow()
    updated = 0
    added_bytes = 0
    live_now = 0
    creds = db.scalars(
        select(UserEndpointCred).where(
            UserEndpointCred.server_id == server.id,
            UserEndpointCred.revoked_at.is_(None),
        )
    )
    seen_ips: dict[int, set[str]] = {}
    for cred in creds:
        if cred.label and cred.label in online:
            cred.last_seen_at = now
            live_now += 1
        if cred.label and addresses.get(cred.label):
            seen_ips.setdefault(cred.user_id, set()).update(addresses[cred.label])
        pair = counters.get(cred.label or "")
        if pair is None:
            continue
        rx, tx = pair
        if rx == cred.rx_bytes and tx == cred.tx_bytes:
            # Без изменений — без записи (агент присылает снимок каждые 15 с).
            updated += 1
            continue
        delta_rx = rx - cred.rx_bytes if rx >= cred.rx_bytes else rx
        delta_tx = tx - cred.tx_bytes if tx >= cred.tx_bytes else tx
        delta = max(0, delta_rx + delta_tx)

        cred.rx_bytes = rx
        cred.tx_bytes = tx
        cred.traffic_synced_at = now
        if delta > 0:
            cred.last_seen_at = now
            db.execute(
                sql_update(User)
                .where(User.id == cred.user_id)
                .values(traffic_used_bytes=User.traffic_used_bytes + delta)
                .execution_options(synchronize_session="fetch")
            )
            db.add(
                TrafficSample(
                    user_id=cred.user_id,
                    server_id=server.id,
                    delta_bytes=delta,
                    rx_bytes=rx,
                    tx_bytes=tx,
                    sampled_at=now,
                )
            )
            added_bytes += delta
        updated += 1

    db.commit()
    return {
        "server_id": server.id,
        "peers": updated,
        "added_bytes": added_bytes,
        "online": live_now,
        "ips": {user_id: sorted(ips) for user_id, ips in seen_ips.items()},
    }


def share_link(endpoint: NodeEndpoint, cred: UserEndpointCred, server: Server) -> str | None:
    identity = cred.identity
    if not identity:
        return None
    params = endpoint.params or {}
    extra = cred.extra or {}
    host = endpoint.public_host(server)
    names = params.get("server_names") or [""]
    query = {
        "type": "tcp",
        "security": "reality",
        "pbk": params.get("public_key", ""),
        "fp": params.get("fingerprint", "chrome"),
        "sni": names[0],
        "sid": extra.get("short_id", ""),
        "flow": extra.get("flow", FLOW),
    }
    from urllib.parse import quote, urlencode

    tail = urlencode({k: v for k, v in query.items() if v})
    from .. import geo

    name = quote(f"{geo.flag(server.country_code)} {server.country or server.name}")
    port = (params.get("advertise_port")) or endpoint.listen_port
    return f"vless://{identity}@{host}:{port}?{tail}#{name}"


def tls_links(endpoint: NodeEndpoint, cred: UserEndpointCred, server: Server) -> list[str]:
    """
    Ссылки vless:// обычного TLS на свой домен: XHTTP (через 443 — Reality
    пропускает к нему всех без своего ключа) и WebSocket на отдельном порту.
    Для сотовых сетей это главный путь: DPI видит HTTPS к сайту, чьё имя
    совпадает с адресом и сертификат настоящий.
    """
    params = endpoint.params or {}
    tls = params.get("tls") or {}
    identity = cred.identity
    if not identity or not tls.get("host"):
        return []
    from urllib.parse import quote, urlencode

    from .. import geo

    host = endpoint.public_host(server)
    sni = tls["host"]
    # Отпечаток TLS — из параметров точки: по наблюдениям 2026 года ТСПУ
    # метит chrome/safari/ios, а firefox проходит (см. память).
    fingerprint = params.get("fingerprint", "chrome")
    label = f"{geo.flag(server.country_code)} {server.country or server.name}"
    out: list[str] = []
    xhttp = params.get("xhttp") or {}
    if xhttp.get("port"):
        port = xhttp.get("advertise_port") or endpoint.listen_port
        query = {
            "type": "xhttp",
            "security": "tls",
            "sni": sni,
            "host": sni,
            "fp": fingerprint,
            "path": xhttp.get("path") or "/",
            "mode": "auto",
            "alpn": "h2,http/1.1",
        }
        out.append(f"vless://{identity}@{host}:{port}?{urlencode(query)}#{quote(label + ' · LTE')}")
    ws = params.get("ws") or {}
    if ws.get("port"):
        query = {
            "type": "ws",
            "security": "tls",
            "sni": sni,
            "host": sni,
            "fp": fingerprint,
            "path": ws.get("path") or "/",
            "alpn": "http/1.1",
        }
        out.append(
            f"vless://{identity}@{host}:{int(ws['port'])}?{urlencode(query)}#{quote(label + ' · LTE 2')}"
        )
    return out


def hy2_link(endpoint: NodeEndpoint, cred: UserEndpointCred, server: Server) -> str | None:
    """
    Ссылка hysteria2:// для того же узла и той же учётки.

    Hysteria2 на узле (deploy/setup-hy2.sh) своих пользователей не хранит:
    на каждое соединение он спрашивает панель, а паролем служит UUID
    VLESS-учётки — поэтому ссылка собирается из той же креды. Порты после
    двоеточия — основной и диапазон «прыгающих»: Happ сам выбирает один и
    время от времени переходит на другой. Сертификат самоподписанный,
    отсюда insecure=1; DPI видит только SNI, и он совпадает с донором Reality.
    """
    hy2 = (endpoint.params or {}).get("hy2") or {}
    if not hy2.get("port"):
        return None
    identity = cred.identity
    if not identity:
        return None
    from urllib.parse import quote, urlencode

    host = endpoint.public_host(server)
    ports = str(hy2["port"])
    if hy2.get("hop"):
        ports += f",{hy2['hop']}"
    query = {"sni": hy2.get("sni") or ""}
    if hy2.get("tls") != "real":
        query["insecure"] = "1"
    if hy2.get("obfs"):
        query["obfs"] = "salamander"
        query["obfs-password"] = str(hy2["obfs"])
    tail = urlencode({k: v for k, v in query.items() if v})
    from .. import geo

    name = quote(f"{geo.flag(server.country_code)} {server.country or server.name} · LTE 3")
    return f"hysteria2://{identity}@{host}:{ports}/?{tail}#{name}"
