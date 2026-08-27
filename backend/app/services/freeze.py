"""
Заморозка подписки: пауза, на которой дни не тратятся.

Уезжаешь на месяц — ставишь подписку на паузу, и оплаченные дни дожидаются
возвращения. Пауза честная в обе стороны: пока она стоит, VPN не работает,
иначе это была бы просто бесплатная прибавка к сроку.

Как устроено. Даты в подписках при заморозке НЕ трогаются — вместо этого
останавливаются часы: `User.subscription_clock` во время паузы возвращает
минуту заморозки, и всё, что считается от «сейчас» (активная подписка,
остаток дней, очередь будущих периодов), замирает вместе с ней. Разморозка
сдвигает даты один раз на всю длительность паузы. Так дешевле и надёжнее,
чем пересчитывать очередь периодов при каждой паузе: у человека их может
быть несколько — оплаченный, бонусный, подаренный другом.

Кому доступна. Только тому, у кого прямо сейчас идёт **оплаченный** период:
пробный и подаренные дни морозить нельзя — иначе бесплатные две недели можно
растянуть на год, раздавая ссылку дальше. Проверка смотрит на текущий период,
а не на историю платежей: подарок поверх оплаченного тарифа — это подарок.

Метка `is_free` паузу НЕ отнимает: она про кассу (продления такой учётки не
пишут платежей и не идут в прогноз выручки), а срок у неё идёт как у всех —
значит и останавливать его есть зачем.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import Subscription, User, utcnow
from . import keys as keys_service
from .errors import PanelError

log = logging.getLogger("panel.freeze")


# Дольше этого срока пауза не живёт: аккаунт всё это время занимает адреса и
# место в очереди, а человек, забывший про заморозку, теряет доступ молча.
# По истечении срока подписка размораживается сама — см. `auto_resume`.
MAX_DAYS = 180

# Чаще этого в один календарный месяц паузу не поставить. Иначе заморозку
# можно доить: вечером пользуешься, на ночь морозишь — и 30 оплаченных дней
# растягиваются на 60 календарных.
PER_MONTH = 2

# Пауза короче минуты — это промах по кнопке. Разморозка такой паузы ничего
# не сдвигает, но и повода записывать её в историю нет.
MIN_PAUSE = dt.timedelta(minutes=1)


class FreezeError(PanelError):
    """Заморозка невозможна — с человеческим объяснением почему."""


def _month(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m")


def month_used(user: User, now: dt.datetime | None = None) -> int:
    """Сколько пауз уже поставлено в текущем календарном месяце."""
    moment = now or utcnow()

    if user.freeze_month != _month(moment):
        return 0

    return user.freeze_month_used


def why_not(user: User, now: dt.datetime | None = None) -> str:
    """
    Почему заморозить нельзя. Пустая строка — можно.

    Причины возвращаются готовым текстом: их показывают и в кабинете, и в
    боте, и в панели, и расходиться формулировкам ни к чему.
    """
    moment = now or utcnow()

    if user.is_frozen:
        return "Подписка уже на паузе."

    if user.is_blocked:
        return "Аккаунт заблокирован."

    if not user.is_active:
        return "Аккаунт отключён."

    subscription = user.active_subscription(moment)

    if subscription is None:
        return "Активной подписки нет."

    if subscription.is_bonus or subscription.price <= 0:
        return "Пауза доступна только на оплаченном тарифе — пробные и подарочные дни заморозить нельзя."

    if (user.access_days_left(moment) or 0) <= 0:
        return "Дней на счету не осталось — паузу ставить не от чего."

    if month_used(user, moment) >= PER_MONTH:
        return (
            f"Пауза ставится не чаще {PER_MONTH} раз в месяц — лимит исчерпан, "
            "новая будет доступна с первого числа."
        )

    return ""


def can_freeze(user: User, now: dt.datetime | None = None) -> bool:
    return not why_not(user, now)


def state(user: User, now: dt.datetime | None = None) -> dict[str, object]:
    """Всё, что витрины показывают про паузу, — одним словарём."""
    moment = now or utcnow()
    reason = why_not(user, moment)

    return {
        "frozen": user.is_frozen,
        "frozen_at": user.frozen_at,
        "frozen_days": user.frozen_for(moment).days,
        "days_left": user.access_days_left(moment),
        "resumes_by": (user.frozen_at + dt.timedelta(days=MAX_DAYS)) if user.is_frozen else None,
        "can_freeze": not reason,
        "reason": reason,
        "max_days": MAX_DAYS,
        "used_days": user.frozen_days_used,
        "count": user.freeze_count,
        "per_month": PER_MONTH,
        "month_left": max(0, PER_MONTH - month_used(user, moment)),
    }


def freeze(db: OrmSession, user: User, *, by: str = "user") -> list[str]:
    """
    Ставит подписку на паузу и закрывает доступ. Возвращает жалобы узлов.

    Сессии приложения и кабинета НЕ трогаем — в отличие от «отключить
    аккаунт». Человеку нужно чем-то снять паузу, и выкидывать его из
    кабинета ровно в тот момент, когда он ставит её сам, было бы издевательством.
    """
    reason = why_not(user)

    if reason:
        raise FreezeError(reason, code="freeze_forbidden")

    now = utcnow()
    user.frozen_at = now
    user.freeze_count += 1

    month = _month(now)
    if user.freeze_month != month:
        user.freeze_month = month
        user.freeze_month_used = 0
    user.freeze_month_used += 1

    problems = _close_access(db, user)
    db.commit()

    log.info("подписка %s заморожена (%s)", user.public_id, by)

    return problems


def resume(db: OrmSession, user: User, *, by: str = "user") -> dt.timedelta:
    """
    Снимает паузу и возвращает подписке отнятое время.

    Сдвигаются все периоды, которые на момент заморозки ещё не кончились, —
    и текущий, и стоящие в очереди. Иначе бонусные дни, ждавшие своей
    очереди позади оплаченных, сгорали бы за время паузы.

    Ключи не выдаём: их выпишет первое же подключение (`ensure_keys` при
    входе и при запросе списка серверов). Выдавать здесь — значит держать
    ответ, пока узлы отвечают по SSH.
    """
    if not user.is_frozen:
        return dt.timedelta(0)

    now = utcnow()
    frozen_at = user.frozen_at
    elapsed = max(dt.timedelta(0), now - frozen_at)

    if elapsed >= MIN_PAUSE:
        for subscription in db.scalars(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.is_cancelled.is_(False),
                Subscription.expires_at > frozen_at,
            )
        ):
            if subscription.starts_at > frozen_at:
                subscription.starts_at += elapsed

            subscription.expires_at += elapsed

            # Письмо «подписка кончается» должно уйти к новому сроку, а не к
            # старому: старое напоминание отработало по дате, которой больше
            # нет.
            if subscription.reminder_sent_at is not None:
                subscription.reminder_sent_at = None

        user.frozen_days_used += elapsed.days

    user.frozen_at = None
    db.commit()

    log.info(
        "подписка %s разморожена (%s), сдвиг %s дн.",
        user.public_id,
        by,
        elapsed.days,
    )

    return elapsed


def auto_resume(db: OrmSession) -> list[str]:
    """
    Снимает паузы, которые стоят дольше положенного.

    Зовётся из фонового цикла. Человек, забывший про заморозку, иначе теряет
    доступ бессрочно, а его дни всё равно когда-нибудь кончатся — лучше
    вернуть их в ход и предупредить письмом, чем хранить вечно.
    """
    edge = utcnow() - dt.timedelta(days=MAX_DAYS)
    woken: list[str] = []

    for user in db.scalars(select(User).where(User.frozen_at.is_not(None), User.frozen_at <= edge)):
        resume(db, user, by="срок паузы вышел")
        woken.append(user.public_id)

    return woken


def _close_access(db: OrmSession, user: User) -> list[str]:
    """Снимает пиров со всех узлов. Сессии и ключи xray — тоже."""
    from ..models import Provisioning
    from .. import provisioning

    problems: list[str] = []
    now = utcnow()

    for key in user.keys:
        if key.revoked_at is not None:
            continue

        server = key.server

        if server.provisioning == Provisioning.SSH and key.public_key:
            try:
                provisioning.remove_peer_over_ssh(
                    server, key.public_key, interface=keys_service.interface_for(db, key)
                )
            except Exception as error:  # узел не ответил — скажем об этом честно
                problems.append(f"{server.name}: {error}")
                continue

        key.revoked_at = now

    keys_service.xray_revoke(db, user.id)

    return problems
