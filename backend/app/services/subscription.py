"""
Токены подписки: доступ к ссылке `sub.prostovpn.cc/s/<token>`.

Токен отделён от входа в приложение (`Session`): ссылку подписки человек
кладёт в сторонний клиент, и она не должна нести права кабинета. Здесь —
выдача, проверка, продление, ротация и отзыв; сама выдача конфига по токену
живёт в `subscription_api`.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Session, SubscriptionToken, utcnow
from ..security import new_token, token_hash

log = logging.getLogger("panel.subscription")


def _ttl() -> dt.timedelta:
    return dt.timedelta(days=settings().subscription_token_days)


def url_for(raw_token: str) -> str:
    """Полная ссылка подписки для сырого токена."""
    return f"{settings().subscription_base}/s/{raw_token}"


def _revoke_active(db: OrmSession, user_id: int, device_id: str, now: dt.datetime) -> None:
    """Гасит живые токены этой пары (user, device) — без коммита."""
    db.execute(
        update(SubscriptionToken)
        .where(
            SubscriptionToken.user_id == user_id,
            SubscriptionToken.device_id == device_id,
            SubscriptionToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def mint(db: OrmSession, user_id: int, device_id: str = "", label: str | None = None) -> str:
    """
    Заводит токен подписки для (user, device), погасив прежний активный.

    Возвращает СЫРОЙ токен — он существует только здесь и сейчас: в базе лежит
    лишь его хэш, восстановить сырой из базы нельзя. Поэтому ссылку показывают
    в момент выдачи (вход, ротация), а не отдают повторно на каждом запросе.
    """
    device_id = (device_id or "").strip()
    now = utcnow()
    _revoke_active(db, user_id, device_id, now)
    raw = new_token()
    db.add(
        SubscriptionToken(
            user_id=user_id,
            device_id=device_id,
            token_hash=token_hash(raw),
            label=(label or None),
            expires_at=now + _ttl(),
        )
    )
    db.commit()
    return raw


def mint_for_session(db: OrmSession, session: Session) -> str:
    """Токен для устройства этого входа — ярлык из имени устройства/платформы."""
    label = session.device_name or session.platform
    return mint(db, session.user_id, session.device_key, label=label)


def resolve(db: OrmSession, raw_token: str) -> SubscriptionToken | None:
    """Живой токен по сырому значению, иначе None (отозван/просрочен/нет)."""
    if not raw_token:
        return None
    tok = db.scalar(
        select(SubscriptionToken).where(SubscriptionToken.token_hash == token_hash(raw_token))
    )
    if tok is None or tok.revoked_at is not None:
        return None
    if tok.expires_at is not None and tok.expires_at <= utcnow():
        return None
    return tok


def touch(db: OrmSession, tok: SubscriptionToken) -> None:
    """Отмечает обращение и продлевает срок, когда прошла половина."""
    now = utcnow()
    tok.last_used_at = now
    if tok.expires_at is not None:
        full = _ttl()
        if tok.expires_at - now < full / 2:
            tok.expires_at = now + full
    db.commit()


def rotate(db: OrmSession, user_id: int, device_id: str = "", label: str | None = None) -> str:
    """
    Меняет токен: старый гаснет, выдаётся новый. Перевыпуск WG-пары — забота
    вызывающего (кнопка «скомпрометирован» в панели), здесь только сам токен.
    """
    return mint(db, user_id, device_id, label=label)


def revoke_for_device(db: OrmSession, user_id: int, device_id: str) -> int:
    """
    Гасит токены подписки устройства — при отвязке устройства.

    Иначе выкинутый по лимиту или отключённый вручную телефон сохранял бы
    рабочую ссылку подписки и продолжал получать конфиг. Возвращает число
    погашенных токенов.
    """
    now = utcnow()
    result = db.execute(
        update(SubscriptionToken)
        .where(
            SubscriptionToken.user_id == user_id,
            SubscriptionToken.device_id == (device_id or "").strip(),
            SubscriptionToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.commit()
    return result.rowcount or 0


def revoke_all(db: OrmSession, user_id: int) -> int:
    """Гасит все токены подписки пользователя — блокировка/сброс доступа."""
    now = utcnow()
    result = db.execute(
        update(SubscriptionToken)
        .where(
            SubscriptionToken.user_id == user_id,
            SubscriptionToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.commit()
    return result.rowcount or 0


def reissue_user(db: OrmSession, user) -> list[str]:
    """
    Инцидент компрометации: перевыпускает WG-пары всех устройств и гасит все
    ссылки подписки пользователя.

    Только это по-настоящему превращает утёкшую ссылку в отзываемый инцидент:
    ротация одного токена обрывает саму ссылку, но уже отданный по ней приватный
    ключ остаётся живым, пока пару не сменили. iOS-слоты не трогаем — у них своя
    кнопка перевыпуска в карточке. Возвращает список узлов, где не прошло.
    """
    from ..models import Provisioning, is_ios_slot
    from . import keys as keys_service

    problems: list[str] = []
    targets = [
        key
        for key in user.keys
        if key.revoked_at is None and not is_ios_slot(key.device_id)
    ]
    for key in targets:
        server = key.server
        if server.provisioning != Provisioning.SSH:
            continue
        try:
            keys_service.issue_key(db, user, server, rotate=True, device_id=key.device_id or "")
        except Exception as exc:  # noqa: BLE001 — причина нужна администратору
            problems.append(f"{server.name}: {exc}")
    revoke_all(db, user.id)
    return problems


def active_for_user(db: OrmSession, user_id: int) -> list[SubscriptionToken]:
    """Живые токены пользователя — для карточки в панели."""
    now = utcnow()
    rows = db.scalars(
        select(SubscriptionToken)
        .where(
            SubscriptionToken.user_id == user_id,
            SubscriptionToken.revoked_at.is_(None),
        )
        .order_by(SubscriptionToken.created_at)
    )
    return [t for t in rows if t.expires_at is None or t.expires_at > now]
