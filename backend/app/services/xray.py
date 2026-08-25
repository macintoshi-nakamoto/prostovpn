from __future__ import annotations

import json
import logging
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
    for ep in server.endpoints:
        if ep.listen_port == listen_port or listen_port in ep.alt_port_list():
            raise PanelError(f"порт {listen_port} на этом узле уже занят")
    if listen_port == server.port or listen_port in server.alt_port_list():
        raise PanelError(f"порт {listen_port} уже объявлен у самого узла")

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

        clients = []
        for cred in db.scalars(
            select(UserEndpointCred).where(
                UserEndpointCred.endpoint_id == endpoint.id,
                UserEndpointCred.revoked_at.is_(None),
            )
        ):
            identity = cred.identity
            if not identity:
                continue
            clients.append(
                {"id": identity, "flow": params.get("flow", FLOW), "email": cred.label}
            )

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

        inbounds.append(
            {
                "tag": f"in-{endpoint.handle}",
                "listen": params.get("listen_addr") or "0.0.0.0",
                "port": endpoint.listen_port,
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
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}},
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


def apply_config(db: OrmSession, server: Server) -> None:
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
    provisioning.run_over_ssh(server, f"systemctl restart {XRAY_UNIT}")


def _mark_dirty(db: OrmSession, endpoint: NodeEndpoint) -> None:
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()


def push_to_node(db: OrmSession, server: Server) -> bool:
    try:
        apply_config(db, server)
    except Exception as exc:
        log.warning("узел %s: конфиг VLESS не записан (%s), починим обходом", server.name, exc)
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

    identity = str(uuid.uuid4())
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
    cred.identity_enc = crypto.encrypt(identity)
    cred.identity_fp = crypto.blind_index(identity)
    cred.label = cred.label or _label()
    cred.extra = {
        "flow": params.get("flow", FLOW),
        "short_id": secrets.choice(short_ids),
    }
    db.commit()
    db.refresh(cred)

    _mark_dirty(db, endpoint)
    push_to_node(db, server)
    return cred


def is_on_node(endpoint: NodeEndpoint) -> bool:
    return (endpoint.params or {}).get("applied_rev") == endpoint.rev


def revoke_cred(db: OrmSession, cred: UserEndpointCred) -> None:
    cred.revoked_at = utcnow()
    db.commit()
    endpoint = db.get(NodeEndpoint, cred.endpoint_id)
    if endpoint is not None:
        _mark_dirty(db, endpoint)
        push_to_node(db, endpoint.server)


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

    for endpoint_id in endpoint_ids:
        endpoint = db.get(NodeEndpoint, endpoint_id)
        if endpoint is not None:
            _mark_dirty(db, endpoint)
    for server_id in server_ids:
        server = db.get(Server, server_id)
        if server is not None:
            push_to_node(db, server)
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
        raw = provisioning.run_over_ssh(
            server,
            f"{XRAY_BIN} api statsquery --server=127.0.0.1:{API_PORT} "
            f"-pattern 'user>>>' -reset=false",
        )
    except Exception as exc:
        log.warning("узел %s: счётчики VLESS не сняты: %s", server.name, exc)
        return {"server_id": server.id, "error": str(exc)}

    counters = _parse_stats(raw)
    if not counters:
        return {"server_id": server.id, "peers": 0, "added_bytes": 0}

    now = utcnow()
    updated = 0
    added_bytes = 0
    creds = db.scalars(
        select(UserEndpointCred).where(
            UserEndpointCred.server_id == server.id,
            UserEndpointCred.revoked_at.is_(None),
        )
    )
    for cred in creds:
        pair = counters.get(cred.label or "")
        if pair is None:
            continue
        rx, tx = pair
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
    return {"server_id": server.id, "peers": updated, "added_bytes": added_bytes}


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
    name = quote(f"{server.country or server.name}")
    port = (params.get("advertise_port")) or endpoint.listen_port
    return f"vless://{identity}@{host}:{port}?{tail}#{name}"
