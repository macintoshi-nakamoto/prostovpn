"""
Раздача ключей: у каждого пользователя свой конфиг на каждом сервере.

Здесь же правило «сервер добавили — он появился у всех»: ключи не привязаны
к моменту регистрации пользователя, а досоздаются по факту.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import Provisioning, Server, User, UserKey, utcnow
from .errors import PanelError

# Потолок на всю раздачу ключей внутри одного запроса. Недоступных серверов
# может быть сколько угодно, и без общего срока запрос administратора
# растягивается на минуты. Пропущенные серверы досоздадутся при следующем
# обращении: ensure_keys вызывается и из приложения при каждом входе.
ENSURE_DEADLINE_SECONDS = 20


def active_servers(db: OrmSession) -> list[Server]:
    return list(
        db.scalars(
            select(Server).where(Server.is_active.is_(True)).order_by(Server.sort_order, Server.id)
        )
    )


def ensure_keys(db: OrmSession, user: User) -> list[str]:
    """
    Досоздаёт пользователю ключи на всех включённых серверах.

    Вызывается и при создании пользователя, и при добавлении сервера, и при
    каждом запросе списка серверов из приложения: так новый сервер
    появляется у всех сам, без ручной раздачи.

    Возвращает список предупреждений — сервер может быть недоступен, и это
    не повод валить всю операцию: остальные серверы человек получить должен.
    """
    warnings: list[str] = []
    existing = {key.server_id for key in user.keys if key.revoked_at is None}
    deadline = time.monotonic() + ENSURE_DEADLINE_SECONDS

    for server in active_servers(db):
        if server.id in existing:
            continue
        if server.provisioning == Provisioning.SHARED:
            # Общий ключ лежит на самом сервере, отдельная запись не нужна
            continue
        if time.monotonic() >= deadline:
            # Дальше не идём: пользователь уже создан и с частью серверов
            # работает, а остальные подтянутся сами при следующем входе.
            warnings.append(f"{server.name}: не успели за отведённое время, ключ будет создан позже")
            continue
        try:
            issue_key(db, user, server)
        except Exception as exc:  # сервер недоступен или шаблон кривой
            warnings.append(f"{server.name}: {exc}")
    return warnings


def issue_key(db: OrmSession, user: User, server: Server) -> UserKey:
    """
    Создаёт пару ключей, занимает свободный адрес и заводит пира на сервере.

    Адрес выбираем из уже выданных ключей, а не из состояния сервера: иначе
    два одновременных создания пользователя получат один и тот же адрес.
    """
    if not server.awg_template:
        raise PanelError("не задан шаблон конфига")

    private_key, public_key = provisioning.generate_keypair()

    taken = list(
        db.scalars(
            select(UserKey.address).where(
                UserKey.server_id == server.id, UserKey.address.is_not(None)
            )
        )
    )
    address = provisioning.next_address(taken)
    config = provisioning.render_from_template(server.awg_template, private_key, address)

    provisioning.add_peer_over_ssh(server, public_key, address)

    key = UserKey(
        user_id=user.id,
        server_id=server.id,
        config=config,
        public_key=public_key,
        address=address,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


def revoke_key(db: OrmSession, key: UserKey) -> None:
    """Убирает пира с сервера и помечает ключ отозванным."""
    server = key.server
    if server.provisioning == Provisioning.SSH and key.public_key:
        provisioning.remove_peer_over_ssh(server, key.public_key)
    key.revoked_at = utcnow()
    db.commit()
