"""
Подписка: `GET /s/{token}` на поддомене sub.prostovpn.cc.

Отдаёт актуальные точки подключения по отзываемому токену — без Bearer.
Формат по умолчанию — JSON с массивом `endpoints[]` («протокол + транспорт +
host + port + приоритет + креды»), это и есть контракт под будущие протоколы.
Второй формат `?format=amnezia` — base64 из ссылок `vpn://` для импорта в
приложение AmneziaVPN.

Допуск (подписка активна, iOS-слоты чужие, демо-узлы отсеяны) и подбор порта —
ровно те же, что у /api/v1/servers: обе выдачи ходят через _serve_targets и
_with_chosen_port, чтобы не разойтись.
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session as OrmSession

from . import geo, provisioning, services
from .api_client import _notice_for, _serve_targets, _subscription_out, _with_chosen_port
from .db import get_db
from .models import Provisioning, Server, SubscriptionToken, UserKey
from .security import client_ip, token_hash

log = logging.getLogger("panel.subscription_api")

router = APIRouter(tags=["subscription"])

# Версия контракта подписки — растёт при несовместимом изменении формы ответа.
SUB_VERSION = 1

# Ревалидация, а не запрет кэша: no-store конфликтует с 304 по ETag, из-за
# которого опрос раз в полчаса почти всегда не тянет полное тело. private —
# ответ персональный, посредникам его не кэшировать.
_CACHE = {"Cache-Control": "private, max-age=0, must-revalidate"}

# Лимит частоты: окно без штрафного запирания (lock_minutes=0). Клиент
# опрашивает подписку раз в ~30 мин и при каждом неуспешном коннекте — щедрого
# потолка на минуту хватает и happy-eyeballs, и не запирает платящего.
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
        (f"sub-ip:{ip or 'unknown'}", _RATE_PER_IP),
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
    """
    Точки подключения узла: по записи на порт, приоритет по порядку.

    Первым (priority 0) идёт залипший рабочий порт — тот же, что _with_chosen_port
    подставляет в конфиг и закрепляет за ключом. Клиент, читающий только
    endpoints[0].credentials.config, получает готовый рабочий wg-quick; клиент
    с happy-eyeballs (фаза 4) перебирает остальные по priority.
    """
    base = provisioning.serving_config(server, key)
    if not base:
        return []
    primary = _with_chosen_port(db, server, key, base)
    chosen = provisioning.endpoint_port(primary) or server.port
    wheel = [chosen] + [p for p in ([server.port] + server.alt_port_list()) if p != chosen]

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


def _payload(db: OrmSession, tok: SubscriptionToken, background: BackgroundTasks | None) -> dict:
    user = tok.user
    servers_json: list[dict] = []
    revision = 1
    for server, key in _serve_targets(db, user, tok.device_id, background):
        # SHARED-узлы в фазе 1 подпиской не покрыты: их host принадлежит чужому
        # узлу, structured-endpoints и vpn:// по ним собрались бы неверно. На
        # бою SHARED нет; /api/v1/servers их по-прежнему отдаёт как раньше.
        if server.provisioning != Provisioning.SSH:
            continue
        try:
            endpoints = _endpoints_for(db, server, key)
        except Exception:  # noqa: BLE001 — один битый узел не роняет всю подписку
            log.exception("сервер «%s» пропущен: не собрались endpoints", server.name)
            continue
        if not endpoints:
            continue
        revision = max(revision, server.endpoint_rev or 1)
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
    """base64 из ссылок vpn:// — родной формат импорта AmneziaVPN (не v2ray)."""
    import base64

    user = tok.user
    links: list[str] = []
    for server, key in _serve_targets(db, user, tok.device_id, background):
        # SHARED в фазе 1 не покрыт (см. _payload).
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
        except Exception:  # noqa: BLE001 — битый узел (напр. кривой shared) не роняет ссылку
            log.exception("сервер «%s» пропущен: не собралась ссылка vpn://", server.name)
    return base64.b64encode("\n".join(links).encode()).decode()


@router.get("/s/{token}")
def subscription(
    token: str,
    request: Request,
    background: BackgroundTasks,
    format: str | None = None,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    accept: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> Response:
    """
    Актуальные точки подключения по токену подписки.

    Невалидный, отозванный и просроченный токен — одинаковый 404 без намёка,
    что из них: иначе ответ работал бы оракулом существования токенов.
    """
    _rate_ok(db, token, client_ip(request))

    tok = services.subscription.resolve(db, token)
    if tok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "подписка не найдена")
    services.subscription.touch(db, tok)

    wants_amnezia = format == "amnezia" or (
        format is None and accept is not None and "text/plain" in accept and "json" not in accept
    )

    if wants_amnezia:
        body = _amnezia_body(db, tok, background)
        etag = _etag(body.encode())
        if _if_none_match(if_none_match, etag):
            return Response(status_code=304, headers={**_CACHE, "ETag": etag})
        return PlainTextResponse(body, headers={**_CACHE, "ETag": etag})

    raw = json.dumps(_payload(db, tok, background), ensure_ascii=False, sort_keys=True).encode()
    etag = _etag(raw)
    if _if_none_match(if_none_match, etag):
        return Response(status_code=304, headers={**_CACHE, "ETag": etag})
    return Response(raw, media_type="application/json", headers={**_CACHE, "ETag": etag})
