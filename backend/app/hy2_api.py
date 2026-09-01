"""
Проверка доступа для Hysteria2 на узлах.

Hysteria2 на узле сам не хранит пользователей: на каждое новое соединение он
спрашивает панель (`auth.type: http`), присылая адрес клиента и пароль из
ссылки. Паролем служит тот же UUID, что и у VLESS-учётки человека на этом
узле, — так у Hysteria2 нет своих учёток, своих досылок на узел и своего
списка отзывов: закрыли доступ VLESS — закрылся и Hysteria2.

Узел узнаётся по адресу, с которого пришёл запрос: у него нет иного способа
представиться, а чужому адресу здесь делать нечего. Ответ — по протоколу
Hysteria2: `{"ok": true, "id": ...}` пускает, всё остальное — нет.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import crypto
from .db import get_db
from .models import EndpointKind, EndpointState, NodeEndpoint, Server, UserEndpointCred
from .security import client_ip

log = logging.getLogger("panel.hy2")

router = APIRouter(prefix="/api/v1/hy2", tags=["hy2"])


class AuthIn(BaseModel):
    addr: str = Field(default="", max_length=128)
    auth: str = Field(default="", max_length=256)
    tx: int = 0


class AuthOut(BaseModel):
    ok: bool
    id: str | None = None


def _node_by_ip(db: OrmSession, ip: str | None) -> Server | None:
    if not ip:
        return None
    return db.scalar(select(Server).where(Server.host == ip))


@router.post("/auth", response_model=AuthOut, response_model_exclude_none=True)
def auth(body: AuthIn, request: Request, db: OrmSession = Depends(get_db)) -> AuthOut:
    ip = client_ip(request)
    server = _node_by_ip(db, ip)
    if server is None:
        log.warning("hy2: запрос доступа не с узла (%s)", ip)
        return AuthOut(ok=False)

    secret = (body.auth or "").strip()
    if not secret or not crypto.available():
        return AuthOut(ok=False)

    cred = db.scalar(
        select(UserEndpointCred)
        .join(NodeEndpoint, NodeEndpoint.id == UserEndpointCred.endpoint_id)
        .where(
            UserEndpointCred.server_id == server.id,
            UserEndpointCred.identity_fp == crypto.blind_index(secret),
            UserEndpointCred.revoked_at.is_(None),
            NodeEndpoint.kind == EndpointKind.VLESS,
            NodeEndpoint.state != EndpointState.RETIRED,
        )
    )
    if cred is None:
        return AuthOut(ok=False)
    return AuthOut(ok=True, id=cred.label or f"cred-{cred.id}")
