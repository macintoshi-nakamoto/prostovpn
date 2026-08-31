from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from .. import crypto
from ..config import settings
from ..models import Session, SubscriptionToken, utcnow
from ..security import new_token, token_hash

log = logging.getLogger("panel.subscription")


def _ttl() -> dt.timedelta:
    return dt.timedelta(days=settings().subscription_token_days)


def url_for(raw_token: str) -> str:
    return f"{settings().subscription_base}/s/{raw_token}"


def _revoke_active(db: OrmSession, user_id: int, device_id: str, now: dt.datetime) -> None:
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
    device_id = (device_id or "").strip()
    now = utcnow()
    _revoke_active(db, user_id, device_id, now)
    raw = new_token()
    db.add(
        SubscriptionToken(
            user_id=user_id,
            device_id=device_id,
            token_hash=token_hash(raw),
            token_enc=crypto.encrypt_or_none(raw),
            label=(label or None),
            expires_at=now + _ttl(),
        )
    )
    db.commit()
    return raw


def reveal(tok: SubscriptionToken) -> str | None:
    """Сам токен, если он был зашифрован при выпуске.

    Пусто у всех ссылок, выпущенных до появления token_enc, и когда ключ
    шифрования недоступен. Звать только там, где пустой ответ не ломает
    экран: показать нечего — предложим выпустить заново.
    """
    if not tok.token_enc:
        return None
    try:
        return crypto.decrypt(tok.token_enc)
    except Exception:
        log.warning("ссылка подписки %s не расшифровалась", tok.id)
        return None


def mint_for_session(db: OrmSession, session: Session) -> str:
    label = session.device_name or session.platform
    return mint(db, session.user_id, session.device_key, label=label)


def resolve(db: OrmSession, raw_token: str) -> SubscriptionToken | None:
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
    now = utcnow()
    tok.last_used_at = now
    if tok.expires_at is not None:
        full = _ttl()
        if tok.expires_at - now < full / 2:
            tok.expires_at = now + full
    db.commit()


def rotate(db: OrmSession, user_id: int, device_id: str = "", label: str | None = None) -> str:
    return mint(db, user_id, device_id, label=label)


def revoke_for_device(db: OrmSession, user_id: int, device_id: str) -> int:
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
        except Exception as exc:
            problems.append(f"{server.name}: {exc}")
    revoke_all(db, user.id)
    return problems


def active_for_user(db: OrmSession, user_id: int) -> list[SubscriptionToken]:
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
