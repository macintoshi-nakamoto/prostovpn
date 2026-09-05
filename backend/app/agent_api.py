"""
Приём снимков от агентов на узлах (agent/prosto-node).

Узел представляется токеном, который панель выдала ему при установке
(`tools/agent_token.py`), и обязан прийти со своего адреса: токен, утёкший
с узла, с чужой машины не работает. Ничего, кроме снимка, узел прислать не
может, и ничего, кроме «принято» и желаемого интервала, не получает.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from . import services
from .config import settings
from .db import get_db
from .security import client_ip

log = logging.getLogger("panel.agent")

router = APIRouter(prefix="/api/v1/node", tags=["node"])


class ReportOut(BaseModel):
    ok: bool
    interval: int


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен узла")
    return authorization.split(" ", 1)[1].strip()


@router.post("/report", response_model=ReportOut)
def report(
    request: Request,
    snapshot: dict = Body(...),
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> ReportOut:
    server = services.agent.server_by_token(db, _bearer(authorization))
    if server is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен узла не принят")

    ip = client_ip(request)
    if ip and server.host and ip != server.host:
        log.warning("агент узла «%s» пришёл с чужого адреса %s", server.name, ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "запрос не с адреса узла")

    if len(json.dumps(snapshot)) > services.agent.MAX_REPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "снимок слишком большой")

    problems = services.agent.store_report(db, server, snapshot)
    if problems:
        log.info("узел «%s»: %s", server.name, "; ".join(problems))
    return ReportOut(ok=True, interval=settings().agent_interval_seconds)
