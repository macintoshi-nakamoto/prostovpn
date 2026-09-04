"""Трафик: обычная проба — 15 ГБ, подарочные дни (промокод) — без предела."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.db import GB, SessionLocal, init_db
from app.models import Plan, Subscription, User, utcnow
from app.security import hash_password


def _user(db, login: str) -> User:
    user = User(login=login, password_hash=hash_password("x"))
    db.add(user)
    db.flush()
    return user


def _sub(db, user: User, plan: Plan, *, start_days: float, days: int, bonus: bool = False):
    starts = utcnow() + dt.timedelta(days=start_days)
    db.add(
        Subscription(
            user_id=user.id,
            plan=plan.code,
            plan_id=plan.id,
            price=0,
            currency="RUB",
            period_days=days,
            auto_renew=False,
            is_bonus=bonus,
            starts_at=starts,
            expires_at=starts + dt.timedelta(days=days),
        )
    )


def test_plain_trial_has_15_gb_and_promo_is_unlimited():
    init_db()
    with SessionLocal() as db:
        trial = db.scalar(select(Plan).where(Plan.code == "trial"))
        assert trial.traffic_limit_bytes == 15 * GB

        plain = _user(db, "bt-plain")
        _sub(db, plain, trial, start_days=-0.5, days=2)

        promo = _user(db, "bt-promo")
        _sub(db, promo, trial, start_days=-0.5, days=2)
        _sub(db, promo, trial, start_days=1.5, days=14, bonus=True)

        gifted = _user(db, "bt-gifted")
        _sub(db, gifted, trial, start_days=-1, days=14, bonus=True)
        db.commit()

        for user in (plain, promo, gifted):
            db.refresh(user)
        assert plain.effective_traffic_limit() == 15 * GB
        assert promo.effective_traffic_limit() is None, "проба с подарком в очереди — без предела"
        assert gifted.effective_traffic_limit() is None, "сам подарочный период — без предела"

        # Ручной лимит администратора сильнее подарка.
        promo.traffic_limit_bytes = 3 * GB
        db.commit()
        assert promo.effective_traffic_limit() == 3 * GB
