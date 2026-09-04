"""
Воронка: где теряются люди между регистрацией и оплатой.

Этапы считаются по фактам, которые уже лежат в базе, без отдельного
трекинга:

  зарегистрировался — users.created_at;
  получил доступ     — сам сделал шаг: вошёл в приложение, взял ключ для
                       iPhone или выпустил ссылку-подписку (общий ключ
                       учётки, который выдаётся всем при регистрации, не в
                       счёт): min(created_at) по sessions/user_keys/
                       subscription_tokens;
  подключился        — первая выборка трафика (traffic_samples), а если её
                       нет — первое рукопожатие/активность учётки;
  оплатил            — первый платёж с суммой больше нуля;
  платит снова       — второй и дальше.

Источник — откуда пришёл человек: по приглашению (referrals), из Telegram
(первая сессия telegram или есть telegram_id), с сайта (первая сессия
web), из приложения (первый вход сразу из приложения) или заведён
администратором.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from ..models import (
    EXTERNAL_SLOT_PREFIX,
    NON_DEVICE_PLATFORMS,
    Payment,
    Referral,
    Session,
    SubscriptionToken,
    TrafficSample,
    User,
    UserEndpointCred,
    UserKey,
    utcnow,
)

STAGES = [
    ("registered", "Зарегистрировались"),
    ("setup", "Получили доступ"),
    ("connected", "Подключились"),
    ("paid", "Оплатили"),
    ("repeat", "Платят снова"),
]

SOURCES = {
    "referral": "По приглашению",
    "telegram": "Telegram",
    "site": "Сайт",
    "app": "Приложение",
    "admin": "Заведены вручную",
}

STUCK_AFTER = dt.timedelta(hours=24)
STUCK_LIMIT = 30
COHORT_WEEKS = 10


def _min_by_user(db: OrmSession, column, user_col, where=None) -> dict[int, dt.datetime]:
    stmt = select(user_col, func.min(column)).group_by(user_col)
    if where is not None:
        stmt = stmt.where(where)
    return {uid: stamp for uid, stamp in db.execute(stmt).all() if uid is not None and stamp}


def _earliest(*stamps: dt.datetime | None) -> dt.datetime | None:
    present = [s for s in stamps if s is not None]
    return min(present) if present else None


def _week_start(moment: dt.datetime) -> dt.date:
    day = moment.date()
    return day - dt.timedelta(days=day.weekday())


def build(db: OrmSession, days: int | None = None) -> dict:
    now = utcnow()
    since = now - dt.timedelta(days=days) if days else None

    stmt = select(User).order_by(User.created_at)
    if since is not None:
        stmt = stmt.where(User.created_at >= since)
    users = list(db.scalars(stmt))
    ids = [u.id for u in users]
    if not ids:
        return _empty(days, now)

    # --- факты по людям, по одному запросу на таблицу ---------------------
    first_app = _min_by_user(
        db,
        Session.created_at,
        Session.user_id,
        (Session.user_id.in_(ids))
        & or_(Session.platform.is_(None), func.lower(Session.platform).notin_(list(NON_DEVICE_PLATFORMS))),
    )
    # Общий ключ учётки (device_id пустой) выдаётся всем при регистрации —
    # это не шаг человека. Считаем только ключи на устройство: слоты iPhone и
    # ключи входов приложения.
    first_key = _min_by_user(
        db,
        UserKey.created_at,
        UserKey.user_id,
        (UserKey.user_id.in_(ids)) & (UserKey.device_id != ""),
    )
    first_link = _min_by_user(
        db,
        SubscriptionToken.created_at,
        SubscriptionToken.user_id,
        (SubscriptionToken.user_id.in_(ids))
        & SubscriptionToken.device_id.like(f"{EXTERNAL_SLOT_PREFIX}%"),
    )
    first_sample = _min_by_user(
        db, TrafficSample.sampled_at, TrafficSample.user_id, TrafficSample.user_id.in_(ids)
    )
    first_handshake = _min_by_user(
        db, UserKey.last_handshake_at, UserKey.user_id, UserKey.user_id.in_(ids)
    )
    first_seen = _min_by_user(
        db, UserEndpointCred.last_seen_at, UserEndpointCred.user_id, UserEndpointCred.user_id.in_(ids)
    )
    first_paid = _min_by_user(
        db, Payment.paid_at, Payment.user_id, (Payment.user_id.in_(ids)) & (Payment.amount > 0)
    )
    payments_count = {
        uid: n
        for uid, n in db.execute(
            select(Payment.user_id, func.count())
            .where(Payment.user_id.in_(ids), Payment.amount > 0)
            .group_by(Payment.user_id)
        ).all()
    }
    invited = {
        uid
        for (uid,) in db.execute(
            select(Referral.invited_user_id).where(
                Referral.invited_user_id.in_(ids), Referral.voided_at.is_(None)
            )
        ).all()
    }
    # Первая сессия каждого — по порядку создания; setdefault оставляет
    # самую раннюю.
    first_platform: dict[int, str] = {}
    for uid, platform in db.execute(
        select(Session.user_id, Session.platform)
        .where(Session.user_id.in_(ids))
        .order_by(Session.user_id, Session.created_at, Session.id)
    ).all():
        first_platform.setdefault(uid, (platform or "").strip().lower())

    # --- разметка каждого человека -----------------------------------------
    rows = []
    for user in users:
        uid = user.id
        setup_at = _earliest(first_app.get(uid), first_key.get(uid), first_link.get(uid))
        connected_at = first_sample.get(uid) or _earliest(first_handshake.get(uid), first_seen.get(uid))
        paid_at = first_paid.get(uid)
        paid_n = payments_count.get(uid, 0)

        if uid in invited:
            source = "referral"
        else:
            platform = first_platform.get(uid)
            if platform == "telegram":
                source = "telegram"
            elif platform == "web":
                source = "site"
            elif platform:
                source = "app"
            elif user.telegram_id:
                source = "telegram"
            else:
                source = "admin"

        rows.append(
            {
                "user": user,
                "source": source,
                "registered_at": user.created_at,
                "setup_at": setup_at,
                "connected_at": connected_at,
                "paid_at": paid_at,
                "repeat": paid_n >= 2,
            }
        )

    # --- этапы ---------------------------------------------------------------
    def count(pred) -> int:
        return sum(1 for r in rows if pred(r))

    stage_counts = {
        "registered": len(rows),
        "setup": count(lambda r: r["setup_at"] is not None),
        "connected": count(lambda r: r["connected_at"] is not None),
        "paid": count(lambda r: r["paid_at"] is not None),
        "repeat": count(lambda r: r["repeat"]),
    }
    total = stage_counts["registered"]
    stages = []
    prev = total
    for key, label in STAGES:
        value = stage_counts[key]
        stages.append(
            {
                "key": key,
                "label": label,
                "count": value,
                "pct_total": round(value / total * 100, 1) if total else 0.0,
                "pct_prev": round(value / prev * 100, 1) if prev else 0.0,
            }
        )
        prev = value

    # --- по источникам --------------------------------------------------------
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        bucket = by_source[r["source"]]
        bucket["registered"] += 1
        bucket["setup"] += r["setup_at"] is not None
        bucket["connected"] += r["connected_at"] is not None
        bucket["paid"] += r["paid_at"] is not None
    sources = [
        {"source": code, "label": label, **{k: by_source[code][k] for k in ("registered", "setup", "connected", "paid")}}
        for code, label in SOURCES.items()
        if by_source.get(code)
    ]
    sources.sort(key=lambda s: -s["registered"])

    # --- когорты по неделям регистрации ---------------------------------------
    cohorts_map: dict[dt.date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        week = _week_start(r["registered_at"])
        bucket = cohorts_map[week]
        bucket["registered"] += 1
        bucket["setup"] += r["setup_at"] is not None
        bucket["connected"] += r["connected_at"] is not None
        bucket["paid"] += r["paid_at"] is not None
    cohorts = [
        {
            "week": start.isoformat(),
            "label": f"{start:%d.%m}–{start + dt.timedelta(days=6):%d.%m}",
            **{k: cohorts_map[start][k] for k in ("registered", "setup", "connected", "paid")},
        }
        for start in sorted(cohorts_map)[-COHORT_WEEKS:]
    ]

    # --- сколько ждут -----------------------------------------------------------
    to_connect = [
        (r["connected_at"] - r["registered_at"]).total_seconds() / 3600
        for r in rows
        if r["connected_at"] is not None and r["connected_at"] >= r["registered_at"]
    ]
    to_pay = [
        (r["paid_at"] - r["registered_at"]).total_seconds() / 86400
        for r in rows
        if r["paid_at"] is not None and r["paid_at"] >= r["registered_at"]
    ]

    # --- застряли ---------------------------------------------------------------
    stuck_rows = [
        r
        for r in rows
        if r["connected_at"] is None and r["registered_at"] <= now - STUCK_AFTER
    ]
    stuck_rows.sort(key=lambda r: r["registered_at"], reverse=True)
    stuck = [
        {
            "id": r["user"].id,
            "public_id": r["user"].public_id,
            "login": r["user"].login,
            "name": r["user"].name,
            "telegram_username": r["user"].telegram_username,
            "created_at": r["registered_at"],
            "source": r["source"],
            "has_setup": r["setup_at"] is not None,
            "access_active": r["user"].has_access(now),
        }
        for r in stuck_rows[:STUCK_LIMIT]
    ]
    cooled = count(
        lambda r: r["connected_at"] is not None
        and r["paid_at"] is None
        and not r["user"].has_access(now)
    )

    return {
        "period_days": days,
        "users": total,
        "stages": stages,
        "sources": sources,
        "cohorts": cohorts,
        "stuck_count": len(stuck_rows),
        "stuck": stuck,
        "cooled_count": cooled,
        "median_hours_to_connect": round(statistics.median(to_connect), 1) if to_connect else None,
        "median_days_to_pay": round(statistics.median(to_pay), 1) if to_pay else None,
        "generated_at": now,
    }


def _empty(days: int | None, now: dt.datetime) -> dict:
    return {
        "period_days": days,
        "users": 0,
        "stages": [
            {"key": key, "label": label, "count": 0, "pct_total": 0.0, "pct_prev": 0.0}
            for key, label in STAGES
        ],
        "sources": [],
        "cohorts": [],
        "stuck_count": 0,
        "stuck": [],
        "cooled_count": 0,
        "median_hours_to_connect": None,
        "median_days_to_pay": None,
        "generated_at": now,
    }
