"""
Приём снимков от агентов на узлах (agent/prosto-node).

Узел представляется токеном, который панель выдала ему при установке
(`tools/agent_token.py`), и обязан прийти со своего адреса: токен, утёкший
с узла, с чужой машины не работает. Ничего, кроме снимка, узел прислать не
может, и ничего, кроме «принято» и желаемого интервала, не получает.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, Header, HTTPException, Request, status
from pydantic import BaseModel

from . import services
from .config import settings
from .db import SessionLocal
from .security import client_ip

log = logging.getLogger("panel.agent")

router = APIRouter(prefix="/api/v1/node", tags=["node"])


class ReportOut(BaseModel):
    ok: bool
    interval: int
    # Панель зачисляет трафик по снимкам: агент может обнулять счётчики
    # Hysteria2 (/traffic?clear=1) и слать дельты с пометкой cleared.
    account: bool = True
    # Задания узлу (services/node_tasks.py): что поставить, снять, записать.
    tasks: list[dict] = []


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен узла")
    return authorization.split(" ", 1)[1].strip()


@router.post("/report", response_model=ReportOut)
async def report(
    request: Request,
    snapshot: dict = Body(...),
    authorization: str | None = Header(default=None),
) -> ReportOut:
    """
    Снимок с узла. Ручка асинхронная: приняв снимок, она держит ответ, пока
    для узла не появится задание (или не выйдет время), — так задание
    доезжает до агента мгновенно, а не через интервал снимков. Работа с
    базой — в потоке, как у остальных ручек.
    """
    token = _bearer(authorization)
    ip = client_ip(request)
    if len(json.dumps(snapshot)) > services.agent.MAX_REPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "снимок слишком большой")

    def accept() -> tuple[int, str, list[str], bool]:
        with SessionLocal() as db:
            server = services.agent.server_by_token(db, token)
            if server is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен узла не принят")
            if ip and server.host and ip != server.host:
                log.warning("агент узла «%s» пришёл с чужого адреса %s", server.name, ip)
                raise HTTPException(status.HTTP_403_FORBIDDEN, "запрос не с адреса узла")
            problems = services.agent.store_report(db, server, snapshot)
            services.node_tasks.ack(db, server, snapshot.get("acks"))
            return (
                server.id,
                server.name,
                problems,
                services.node_tasks.supports_tasks(server.agent_version),
            )

    server_id, name, problems, tasky = await asyncio.to_thread(accept)
    if problems:
        log.info("узел «%s»: %s", name, "; ".join(problems))

    interval = settings().agent_interval_seconds
    tasks: list[dict] = []
    if tasky:
        hold = min(services.node_tasks.HOLD_SECONDS, max(0, interval - 3))
        tasks = await services.node_tasks.pending(server_id, hold)
    return ReportOut(ok=True, interval=interval, tasks=tasks)
