"""
Куда селить пользователя: выбор точки входа на узле.

Правило первое и главное: **точка входа существующей строки не меняется
никогда**. Пир живёт на конкретном интерфейсе, у интерфейса свой набор
обфускации и свой адрес в своей подсети; переселение — это новая пара ключей,
новый адрес и разрыв туннеля до того момента, когда приложение перечитает
список серверов. Поэтому переселение — отдельная осознанная операция, а не
побочный эффект обычной выдачи.

Правило второе: устройства одного человека держим вместе. Не ради красоты —
так у него на всех устройствах один набор обфускации и один порт, и «на
телефоне работает, на ноутбуке нет» перестаёт быть загадкой.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import EndpointKind, EndpointState, NodeEndpoint, Server, User, UserKey
from . import endpoints as endpoints_service
from .errors import PanelError

log = logging.getLogger("panel.placement")

# Выбор точки входа — read-then-write: посчитали занятость, выбрали, записали.
# Между этими шагами вклинивается параллельная выдача (вход в приложении и
# фоновая раздача идут одновременно), и потолок capacity переберётся. Замок
# внутрипроцессный: панель работает в один воркер (см. deploy/prosto-panel.service),
# и этого достаточно, а межпроцессную гонку всё равно ловит уникальный индекс
# по адресу.
_PICK_LOCK = threading.Lock()


def pick_endpoint(
    db: OrmSession, user: User, server: Server, device_id: str = ""
) -> NodeEndpoint | None:
    """
    Точка входа для пары (пользователь, устройство) на этом узле.

    `None` — на узле точек входа нет вовсе (узел старше фазы 2): вызывающий
    работает по-старому, с историческим awg0 и шаблоном сервера.
    """
    device_id = (device_id or "").strip()

    awg_endpoints = [ep for ep in server.endpoints if ep.kind == EndpointKind.AWG]
    if not awg_endpoints:
        return None

    with _PICK_LOCK:
        # 1. У этой строки уже есть точка входа — она и остаётся. Всегда, даже
        #    если точка входа в «сливе»: сменить её значит порвать туннель.
        existing = db.scalar(
            select(UserKey).where(
                UserKey.user_id == user.id,
                UserKey.server_id == server.id,
                UserKey.device_id == device_id,
            )
        )
        if existing is not None and existing.endpoint_id is not None:
            endpoint = db.get(NodeEndpoint, existing.endpoint_id)
            if endpoint is not None:
                return endpoint

        # 1a. Строка уже где-то живёт, но точка входа не проставлена — это ключ
        #     старше фазы 2. Его пир стоит на историческом интерфейсе, а адрес
        #     взят из ЕГО подсети. Отдать сюда новую точку входа значит завести
        #     пира с чужим адресом на чужом интерфейсе: туннель поднимется,
        #     трафик не пойдёт, и со стороны клиента это неотличимо от молчащего
        #     сервера. Возвращаем ту, что описывает исторический интерфейс.
        if existing is not None and existing.address:
            legacy = next(
                (ep for ep in awg_endpoints if ep.handle == provisioning.INTERFACE), None
            )
            return legacy

        live = [ep for ep in awg_endpoints if ep.is_live]
        if not live:
            raise PanelError("на узле нет работающих точек входа")

        # 2. Липкость по человеку: где уже живут его другие устройства.
        siblings = db.scalars(
            select(UserKey.endpoint_id).where(
                UserKey.user_id == user.id,
                UserKey.server_id == server.id,
                UserKey.endpoint_id.is_not(None),
            )
        )
        sibling_ids = {value for value in siblings if value is not None}
        for endpoint in live:
            if endpoint.id in sibling_ids and endpoint.accepts_new:
                return endpoint

        # 3. Иначе — самая свободная из принимающих новых.
        accepting = [ep for ep in live if ep.accepts_new]
        if not accepting:
            raise PanelError("все точки входа узла закрыты для новых подключений")

        busy = endpoints_service.live_count(db, [ep.id for ep in accepting])
        ranked = sorted(
            accepting,
            key=lambda ep: (busy.get(ep.id, 0), ep.id),
        )
        for endpoint in ranked:
            if endpoint.capacity is None or busy.get(endpoint.id, 0) < endpoint.capacity:
                return endpoint

        # 4. Мест нет. Молча селить в первую попавшуюся нельзя: потолок ставят,
        #    чтобы отпечаток дробился, и переполнение — это повод завести
        #    интерфейс, а не тихо его нарушить.
        raise PanelError(
            "на узле кончились места: все точки входа заполнены, заведите ещё одну"
        )


def capacity_report(db: OrmSession, server: Server) -> list[dict]:
    """Заполненность точек входа — для панели и диагностики."""
    awg_endpoints = [ep for ep in server.endpoints if ep.kind == EndpointKind.AWG]
    busy = endpoints_service.live_count(db, [ep.id for ep in awg_endpoints])
    out = []
    for ep in sorted(awg_endpoints, key=lambda e: e.id):
        used = busy.get(ep.id, 0)
        out.append(
            {
                "id": ep.id,
                "handle": ep.handle,
                "state": ep.state.value if isinstance(ep.state, EndpointState) else ep.state,
                "port": ep.listen_port,
                "subnet": ep.subnet,
                "used": used,
                "capacity": ep.capacity,
            }
        )
    return out
