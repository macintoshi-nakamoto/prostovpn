"""
Отключение устройства: и токен, и пир.

Раньше «Отключить» гасило только сессию. Со стороны панели это выглядело
работающим — строка пропадала из списка, — а на деле человек оставался в
VPN: приложение уже держало поднятый туннель, конфиг лежал у него на диске,
и узел про отзыв ничего не знал. Кнопка обещала одно, делала другое.

Отключение — это три вещи разом:

  1. токен погашен, приложение получит 401 и попросит войти заново;
  2. пир этого устройства снят с каждого узла — туннель падает сразу,
     а поднять его старым конфигом уже нельзя;
  3. лимит устройств освободился, и на его место можно войти с нового.

Второй пункт возможен только потому, что пир заводится на устройство
(`UserKey.device_id`), а не на учётку: общий пир нельзя было снять, не
выкинув заодно все остальные устройства человека.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session as OrmSession

from ..models import Provisioning, Session, User, UserKey, utcnow

log = logging.getLogger("panel.devices")


def device_keys(user: User, device_id: str) -> list[UserKey]:
    """Живые ключи одного устройства на всех серверах."""
    wanted = (device_id or "").strip()
    return [
        key for key in user.keys if key.revoked_at is None and (key.device_id or "") == wanted
    ]


def _shared_key_still_needed(user: User, exclude: Session) -> bool:
    """
    Остались ли входы, которым нужен «ключ учётки».

    Приложения старых версий не присылают идентификатор установки, и все
    такие входы одного человека делят один пир. Снять его при отключении
    одного из них значит отключить и остальные — поэтому сначала смотрим,
    не остался ли кто-то ещё.
    """
    return any(
        session.id != exclude.id and session.is_device and not session.device_key
        for session in user.live_sessions()
    )


def disconnect(db: OrmSession, session: Session, reason: str = "") -> list[str]:
    """
    Отключает устройство: гасит сессию и снимает его пиры с узлов.

    Возвращает список узлов, которые не ответили, — доступ там мог остаться,
    и знать об этом важнее, чем отрапортовать успех. Сама сессия гасится в
    любом случае: недоступный узел не повод оставлять живой токен, а
    оставшийся пир подчистит сверка `reconcile_peers`.
    """
    user = session.user
    now = utcnow()
    device_id = session.device_key

    # Токен гасим первым: даже если ни один узел не ответит, приложение
    # получит 401 при ближайшем обращении и опустит туннель само.
    if session.revoked_at is None:
        session.revoked_at = now
    db.commit()

    if device_id == "" and _shared_key_still_needed(user, session):
        log.info(
            "устройство %s отключено, общий ключ учётки %s оставлен: им пользуются другие входы",
            session.id,
            user.public_id,
        )
        return []

    problems: list[str] = []
    for key in device_keys(user, device_id):
        server = key.server
        if server.provisioning == Provisioning.SSH and key.public_key:
            try:
                from .. import provisioning

                provisioning.remove_peer_over_ssh(server, key.public_key)
            except Exception as exc:  # noqa: BLE001 — причина нужна администратору
                problems.append(f"{server.name}: {exc}")
                log.error("пир устройства %s не снят с узла %s: %s", session.id, server.name, exc)
                continue
        key.revoked_at = now
    db.commit()

    log.info(
        "отключено устройство %s пользователя %s%s%s",
        session.id,
        user.public_id,
        f" ({reason})" if reason else "",
        f", узлов не ответило: {len(problems)}" if problems else "",
    )
    return problems


def disconnect_by_id(db: OrmSession, user: User, session_id: int) -> list[str] | None:
    """
    То же самое, но по номеру строки. `None` — сессия не найдена или чужая.

    Проверку владельца держим здесь, а не в двух вызывающих: кабинет и
    админка спрашивают одно и то же, и разойтись эти проверки не должны.
    """
    target = db.get(Session, session_id)
    if target is None or target.user_id != user.id:
        return None
    return disconnect(db, target)
