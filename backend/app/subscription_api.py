from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session as OrmSession

from . import geo, provisioning, services
from .api_client import (
    _notice_for,
    _ports_for,
    _serve_targets,
    _subscription_out,
    _with_chosen_port,
)
from .config import settings
from .db import get_db
from .models import Provisioning, Server, SubscriptionToken, UserKey
from .security import client_ip, ip_tag, token_hash

log = logging.getLogger("panel.subscription_api")

router = APIRouter(tags=["subscription"])

SUB_VERSION = 1

_CACHE = {"Cache-Control": "private, max-age=0, must-revalidate"}

_RATE_WINDOW_MIN = 1
_RATE_PER_TOKEN = 60
_RATE_PER_IP = 300


def _etag(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest() + '"'


def _if_none_match(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    return any(part.strip() == etag for part in header.split(","))


def _rate_ok(db: OrmSession, token: str, ip: str | None) -> None:
    for key, limit in (
        (f"sub-tok:{token_hash(token)[:16]}", _RATE_PER_TOKEN),
        (f"sub-ip:{ip_tag(ip)}", _RATE_PER_IP),
    ):
        verdict = services.ratelimit.hit(
            db, key, limit=limit, window_minutes=_RATE_WINDOW_MIN, lock_minutes=0
        )
        if not verdict.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "слишком часто, попробуйте позже",
                headers={"Retry-After": str(verdict.retry_after)},
            )


def _endpoints_for(db: OrmSession, server: Server, key: UserKey | None) -> list[dict]:
    base = provisioning.serving_config(server, key)
    if not base:
        return []
    primary = _with_chosen_port(db, server, key, base)
    main_port, spare_ports = _ports_for(db, server, key)
    chosen = provisioning.endpoint_port(primary) or main_port
    wheel = [chosen] + [p for p in ([main_port] + spare_ports) if p != chosen]

    interface, peer = provisioning.config_sections(primary)
    obf: dict[str, int | str] = {}
    for name in provisioning.AWG_PARAMS:
        if name in interface:
            value = interface[name]
            obf[name] = int(value) if value.lstrip("-").isdigit() else value

    mtu_raw = interface.get("MTU", "1280")
    mtu = int(mtu_raw) if mtu_raw.isdigit() else 1280
    dns = [d.strip() for d in interface.get("DNS", "").split(",") if d.strip()]
    allowed = [
        a.strip() for a in peer.get("AllowedIPs", "0.0.0.0/0, ::/0").split(",") if a.strip()
    ]
    address = (key.address if key is not None else None) or interface.get("Address", "")

    out: list[dict] = []
    for priority, port in enumerate(wheel):
        out.append(
            {
                "_rank": (0, priority),
                "protocol": "awg",
                "transport": "udp",
                "host": server.host,
                "port": port,
                "priority": priority,
                "credentials": {
                    "type": "amneziawg",
                    "config": provisioning.with_endpoint_port(primary, port),
                    "private_key": interface.get("PrivateKey", ""),
                    "address": address,
                    "server_public_key": peer.get("PublicKey", ""),
                    "dns": dns,
                    "mtu": mtu,
                    "allowed_ips": allowed,
                    "obfuscation": obf,
                },
            }
        )
    return out


def _vless_endpoints_for(
    db: OrmSession, server: Server, user, device_id: str
) -> list[dict]:
    from .models import EndpointKind
    from .services import xray

    live = [
        ep
        for ep in server.endpoints
        if ep.kind == EndpointKind.VLESS and ep.is_live
    ]
    if not live:
        return []

    out: list[dict] = []
    for rank, endpoint in enumerate(sorted(live, key=lambda e: (e.priority, e.id))):
        creds = xray.live_creds(db, user, server, device_id)
        cred = next((c for c in creds if c.endpoint_id == endpoint.id), None)
        if cred is None:
            if not endpoint.accepts_new:
                continue
            try:
                cred = xray.issue_cred(db, user, server, endpoint, device_id)
            except Exception:
                log.exception("точка входа %s: не выдан доступ", endpoint.handle)
                continue

        identity = cred.identity
        if not identity:
            continue
        if not xray.is_on_node(endpoint):
            log.info("точка входа %s ещё не синхронизирована — пропускаем", endpoint.handle)
            continue
        params = endpoint.params or {}
        extra = cred.extra or {}
        link = xray.share_link(endpoint, cred, server)
        out.append(
            {
                "_rank": (1, rank),
                "protocol": "vless",
                "transport": endpoint.transport,
                "host": endpoint.public_host(server),
                "port": (endpoint.params or {}).get("advertise_port") or endpoint.listen_port,
                "priority": 0,
                "credentials": {
                    "type": "vless-reality",
                    "id": identity,
                    "flow": extra.get("flow", ""),
                    "security": params.get("security", "reality"),
                    "sni": (params.get("server_names") or [""])[0],
                    "public_key": params.get("public_key", ""),
                    "short_id": extra.get("short_id", ""),
                    "fingerprint": params.get("fingerprint", "chrome"),
                    "url": link or "",
                },
            }
        )
    return out


def _payload(db: OrmSession, tok: SubscriptionToken, background: BackgroundTasks | None) -> dict:
    user = tok.user
    servers_json: list[dict] = []
    revision = 1
    for server, key in _serve_targets(db, user, tok.device_id, background):
        if server.provisioning != Provisioning.SSH:
            continue
        try:
            endpoints = _endpoints_for(db, server, key)
        except Exception:
            log.exception("сервер «%s» пропущен: не собрались endpoints", server.name)
            continue
        if not endpoints:
            continue

        try:
            endpoints += _vless_endpoints_for(db, server, user, tok.device_id)
        except Exception:
            log.exception("сервер «%s»: не собрались vless-endpoints", server.name)

        endpoints.sort(key=lambda item: item.pop("_rank"))
        for index, item in enumerate(endpoints):
            item["priority"] = index

        revision = max(revision, server.endpoint_rev or 1)
        for endpoint in server.endpoints:
            if endpoint.is_live:
                revision = max(revision, endpoint.rev or 1)
        servers_json.append(
            {
                "id": server.id,
                "name": server.country or server.name,
                "country": server.country,
                "country_en": server.country_en
                or geo.country_en(server.country_code, server.country),
                "city": server.city,
                "city_en": server.city_en or server.city,
                "country_code": server.country_code,
                "endpoints": endpoints,
            }
        )
    return {
        "version": SUB_VERSION,
        "revision": revision,
        "subscription": _subscription_out(user).model_dump(mode="json"),
        "servers": servers_json,
        "notice": _notice_for(db, user, servers_json),
    }


def _amnezia_body(db: OrmSession, tok: SubscriptionToken, background: BackgroundTasks | None) -> str:
    import base64

    user = tok.user
    links: list[str] = []
    for server, key in _serve_targets(db, user, tok.device_id, background):
        if server.provisioning != Provisioning.SSH:
            continue
        config = provisioning.serving_config(server, key)
        if not config:
            continue
        try:
            config = _with_chosen_port(db, server, key, config)
            links.append(
                provisioning.build_vpn_key(
                    server.host,
                    config,
                    port=provisioning.endpoint_port(config) or server.port,
                    name=server.country or server.name,
                    address=key.address if key is not None else None,
                )
            )
        except Exception:
            log.exception("сервер «%s» пропущен: не собралась ссылка vpn://", server.name)
    return base64.b64encode("\n".join(links).encode()).decode()


def _vless_body(db: OrmSession, tok: SubscriptionToken, background: BackgroundTasks | None) -> str:
    """
    Список `vless://` строк для сторонних приложений, как принято у всех:
    ссылки через перевод строки, всё вместе в base64.

    Отдаём все узлы разом. В стороннем клиенте они станут списком, между
    которыми человек переключается сам — своего перебора протоколов там нет,
    и запасной путь ему приходится выбирать руками.
    """
    import base64
    from .models import EndpointKind
    from .services import xray

    user = tok.user
    links: list[str] = []
    for server, _key in _serve_targets(db, user, tok.device_id, background):
        if server.provisioning != Provisioning.SSH:
            continue
        live = [
            ep
            for ep in server.endpoints
            if ep.kind == EndpointKind.VLESS and ep.is_live and xray.is_on_node(ep)
        ]
        if not live:
            continue
        endpoint = sorted(live, key=lambda e: (e.priority, e.id))[0]
        try:
            creds = xray.live_creds(db, user, server, tok.device_id)
            cred = next((c for c in creds if c.endpoint_id == endpoint.id), None)
            if cred is None:
                if not endpoint.accepts_new:
                    continue
                cred = xray.issue_cred(db, user, server, endpoint, tok.device_id)
            link = xray.share_link(endpoint, cred, server)
            if link:
                links.append(link)
        except Exception:
            log.exception("сервер «%s» пропущен: не собралась ссылка vless://", server.name)
    return base64.b64encode("\n".join(links).encode()).decode()


# Приложения представляются в User-Agent, и по нему видно, что человеку
# отдавать. Список неполон намеренно: неизвестный клиент получит JSON, а он
# разберётся или спросит формат явно.
_VLESS_AGENTS = ("happ", "hiddify", "v2rayng", "nekobox", "streisand", "sing-box", "clash", "v2box", "shadowrocket")

_AMNEZIA_AGENTS = ("amnezia",)


def _wanted_format(explicit: str | None, agent: str | None, accept: str | None) -> str:
    """
    Какой формат отдать. Явный параметр сильнее всего остального.

    Без параметра смотрим, кто пришёл: приложение честно называет себя в
    User-Agent, и человеку не приходится разбираться, какую ссылку куда
    вставлять — он копирует одну и ту же.
    """
    if explicit:
        return explicit.strip().lower()

    ua = (agent or "").lower()
    if any(name in ua for name in _VLESS_AGENTS):
        return "vless"
    if any(name in ua for name in _AMNEZIA_AGENTS):
        return "amnezia"

    # Старое поведение: text/plain без json просил AmneziaVPN до того, как
    # начал представляться.
    if accept is not None and "text/plain" in accept and "json" not in accept:
        return "amnezia"
    return "json"


def _profile_headers(db: OrmSession, tok: SubscriptionToken) -> dict[str, str]:
    """
    Заголовки, по которым приложение показывает остаток и само обновляется.

    Формат общий для всех клиентов, понимающих подписки: трафик в байтах,
    срок — секундами эпохи. Ноль в `total` означает «без лимита», и клиенты
    это понимают правильно — полосу не рисуют.
    """
    import base64

    user = tok.user
    limit = user.effective_traffic_limit()
    used = user.traffic_used_bytes
    ends = user.access_ends_if_resumed()

    parts = [f"upload=0", f"download={used}", f"total={limit or 0}"]
    if ends is not None:
        parts.append(f"expire={int(ends.replace(tzinfo=dt.timezone.utc).timestamp())}")

    title = base64.b64encode("ProstoVPN".encode()).decode()
    return {
        "Subscription-Userinfo": "; ".join(parts),
        "Profile-Title": f"base64:{title}",
        "Profile-Update-Interval": "12",
        "Profile-Web-Page-Url": settings().site_url.rstrip("/") + "/account",
    }


@router.get("/s/{token}")
def subscription(
    token: str,
    request: Request,
    background: BackgroundTasks,
    format: str | None = None,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    accept: str | None = Header(default=None),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    db: OrmSession = Depends(get_db),
) -> Response:
    _rate_ok(db, token, client_ip(request))

    tok = services.subscription.resolve(db, token)
    if tok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "подписка не найдена")
    services.subscription.touch(db, tok)

    wanted = _wanted_format(format, user_agent, accept)

    # Заголовки профиля идут со всеми ответами: приложение берёт из них
    # остаток трафика, срок и то, как часто перечитывать подписку.
    try:
        profile = _profile_headers(db, tok)
    except Exception:
        log.exception("заголовки профиля не собрались")
        profile = {}

    if wanted in ("amnezia", "vless"):
        body = (
            _amnezia_body(db, tok, background)
            if wanted == "amnezia"
            else _vless_body(db, tok, background)
        )
        etag = _etag(body.encode())
        headers = {**_CACHE, **profile, "ETag": etag}
        if _if_none_match(if_none_match, etag):
            return Response(status_code=304, headers=headers)
        return PlainTextResponse(body, headers=headers)

    raw = json.dumps(_payload(db, tok, background), ensure_ascii=False, sort_keys=True).encode()
    etag = _etag(raw)
    headers = {**_CACHE, **profile, "ETag": etag}
    if _if_none_match(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(raw, media_type="application/json", headers=headers)
