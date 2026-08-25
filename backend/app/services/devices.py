from __future__ import annotations

import logging

from sqlalchemy.orm import Session as OrmSession

from ..models import Provisioning, Session, User, UserKey, utcnow

log = logging.getLogger("panel.devices")


def device_keys(user: User, device_id: str) -> list[UserKey]:
    wanted = (device_id or "").strip()
    return [
        key for key in user.keys if key.revoked_at is None and (key.device_id or "") == wanted
    ]


def _shared_key_still_needed(user: User, exclude: Session) -> bool:
    return any(
        session.id != exclude.id and session.is_device and not session.device_key
        for session in user.live_sessions()
    )


def disconnect(db: OrmSession, session: Session, reason: str = "") -> list[str]:
    user = session.user
    now = utcnow()
    device_id = session.device_key

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

                from .keys import interface_for

                provisioning.remove_peer_over_ssh(
                    server, key.public_key, interface=interface_for(db, key)
                )
            except Exception as exc:
                problems.append(f"{server.name}: {exc}")
                log.error("пир устройства %s не снят с узла %s: %s", session.id, server.name, exc)
        key.revoked_at = now
    db.commit()

    from . import subscription, xray

    subscription.revoke_for_device(db, user.id, device_id)
    xray.revoke_for_user(db, user.id, device_id=device_id)

    log.info(
        "отключено устройство %s пользователя %s%s%s",
        session.id,
        user.public_id,
        f" ({reason})" if reason else "",
        f", узлов не ответило: {len(problems)}" if problems else "",
    )
    return problems


def disconnect_by_id(db: OrmSession, user: User, session_id: int) -> list[str] | None:
    target = db.get(Session, session_id)
    if target is None or target.user_id != user.id:
        return None
    return disconnect(db, target)
