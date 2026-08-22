"""
Деньги: подписки, платежи, выручка и календарь прибыли.

Календарь показывает две разные величины и не смешивает их: уже полученное
за день (платежи) и ожидаемое (продления, которые приходятся на этот день).
Складывать их в одно число нельзя — по прошлым дням это факт, по будущим
прогноз, и решения по ним принимают разные.
"""

from __future__ import annotations

import calendar as pycalendar
import datetime as dt
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Payment, Plan, Server, Session, Subscription, User, utcnow
from .errors import PanelError


# --- подписки ----------------------------------------------------------------


def grant_subscription(
    db: OrmSession,
    user: User,
    days: int,
    plan: Plan | str | None = None,
    price: float | None = None,
    auto_renew: bool = True,
    commit: bool = True,
) -> Subscription:
    """
    Продлевает доступ. Оплаченные дни не съедаются никогда, а форма зависит от
    того, тот же это тариф или другой:

    * ТОТ ЖЕ тариф (обычное продление, самый частый случай) — продлеваем
      существующий период, а не заводим второй. Иначе «продлить» плодит
      строки, а `active_subscription` показывает всё ту же истекающую первую,
      и администратор жмёт кнопку без видимого эффекта — ровно этот баг и
      случился, когда каждое продление вставало в очередь.
    * ДРУГОЙ тариф (смена/апгрейд) — новый период встаёт в очередь за идущим:
      пока не дожиты дни старого тарифа, действует он, потом в полную силу
      вступает новый. Очередь держим строго в один период: прежний
      запланированный апгрейд заменяется новым, а не копится каскадом.

    Бесплатный период (пробный) к живому доступу не пристраиваем вовсе: так он
    уезжал в будущее и копил дни, которых никто не покупал.

    Инвариант на выходе — не больше одного идущего периода плюс не больше
    одного будущего. Его же чинит миграция для учёток, испорченных прежним
    каскадом (см. migrations._collapse_subscription_queue).

    `commit=False` оставляет запись в незавершённой транзакции: выдача по
    оплаченному заказу пишет пользователя, подписку, платёж и заказ одним
    коммитом, и промежуточная фиксация здесь означала бы, что при сбое на
    следующем шаге в базе останется подписка без заказа.
    """
    if days <= 0:
        raise PanelError("срок должен быть больше нуля")

    plan_ref: Plan | None = None
    if isinstance(plan, Plan):
        plan_ref = plan
    elif isinstance(plan, str):
        plan_ref = db.scalar(select(Plan).where(Plan.code == plan))

    code = plan_ref.code if plan_ref else (plan if isinstance(plan, str) else "basic")
    price_dec = (
        Decimal(str(price)) if price is not None else (plan_ref.price if plan_ref else Decimal(0))
    )

    now = utcnow()
    # Читаем из базы, а не из user.subscriptions: при expire_on_commit=False
    # коллекция на объекте в длинной сессии молча отстаёт от базы.
    live = list(
        db.scalars(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.is_cancelled.is_(False),
                Subscription.expires_at > now,
            )
            .order_by(Subscription.expires_at)
        )
    )
    running = max(
        (s for s in live if s.starts_at <= now), key=lambda s: s.expires_at, default=None
    )
    upcoming = sorted((s for s in live if s.starts_at > now), key=lambda s: s.starts_at)

    # Бесплатный период дарить поверх живого доступа нечего.
    if price_dec <= 0 and running is not None:
        return running

    def _finish(sub: Subscription) -> Subscription:
        if commit:
            db.commit()
            db.refresh(sub)
        else:
            # id подписки нужен вызывающему до коммита — заказ ссылается на неё.
            db.flush()
        return sub

    # Платный период во время пробного вступает СРАЗУ, а не после него: остаток
    # бесплатных дней ничего не стоит, и досиживать пробные лимиты после оплаты
    # человек не должен. Идущий пробный уступает — снимаем его.
    #
    # Подаренные дни — другое дело: они заработаны приглашениями и обязаны
    # пережить покупку. Поэтому остаток бонусного периода не сгорает, а
    # переезжает в оплаченный: человек получает купленный тариф сразу и с
    # теми же лишними днями, что у него были.
    carry = dt.timedelta(0)
    if price_dec > 0 and running is not None and (running.price or 0) <= 0:
        if running.is_bonus:
            carry = max(dt.timedelta(0), running.expires_at - now)
        running.is_cancelled = True
        running = None

    # Тариф, на котором человек окажется в конце: хвост очереди, иначе идущий.
    tail = upcoming[-1] if upcoming else running
    if tail is not None and tail.plan == code:
        tail.expires_at = tail.expires_at + dt.timedelta(days=days) + carry
        # Оплаченное продление — повод напомнить о следующем конце срока:
        # пометка о прежнем напоминании снимается, иначе письмо ушло бы один
        # раз за всю жизнь учётки.
        tail.reminder_sent_at = None
        # Продление своей ценой и не двигает `price`: он остаётся ценой периода.
        return _finish(tail)

    # Другой тариф — очередь ровно в один период: прежний запланированный
    # апгрейд заменяется, чтобы не копился каскад из наложенных строк.
    for stale in upcoming:
        stale.is_cancelled = True

    starts = running.expires_at if running is not None else now
    sub = Subscription(
        user_id=user.id,
        plan=code,
        plan_id=plan_ref.id if plan_ref else None,
        price=price_dec,
        currency=plan_ref.currency if plan_ref else settings().currency,
        period_days=days,
        auto_renew=auto_renew,
        starts_at=starts,
        expires_at=starts + dt.timedelta(days=days) + carry,
    )
    db.add(sub)
    return _finish(sub)


def collapse_corrupted_queues(db: OrmSession) -> list[dict[str, object]]:
    """
    Одноразовая чистка учёток, испорченных прежним каскадом очередей.

    Прежняя выдача пристраивала в очередь всё подряд — включая платёж, сделанный
    во время пробного, и повторное продление того же тарифа. У людей накопились
    наложенные периоды, а `active_subscription` показывала истекающий пробный
    вместо оплаченного тарифа.

    Чиним по одному правилу: оставляем период с самым дальним концом (то, за что
    человек реально заплатил дольше всего), делаем его идущим с этого момента и
    снимаем остальные живые. Дни доступа при этом не теряются — конец тот же, —
    а каскад исчезает.

    Не для старта панели: обычную очередь из смены тарифа (идущий + один
    будущий) чинить не надо, поэтому зовётся руками из скрипта выкладки, а не из
    миграций. Идемпотентно: после чистки живой период один, повтор — ничего.
    """
    now = utcnow()
    fixed: list[dict[str, object]] = []
    for user in db.scalars(select(User)):
        live = [s for s in user.subscriptions if not s.is_cancelled and s.expires_at > now]
        if len(live) <= 1:
            continue
        keep = max(live, key=lambda s: s.expires_at)
        before_plan = user.active_subscription(now)
        if keep.starts_at > now:
            # Оплаченный период стоял в будущем за пробным — активируем сейчас.
            keep.starts_at = now
        for s in live:
            if s.id != keep.id:
                s.is_cancelled = True
        fixed.append(
            {
                "login": user.login,
                "public_id": user.public_id,
                "live_before": len(live),
                "was_plan": before_plan.plan if before_plan else None,
                "now_plan": keep.plan,
                "access_until": keep.expires_at.isoformat(),
            }
        )
    if fixed:
        db.commit()
    return fixed


def add_bonus_days(
    db: OrmSession,
    user: User,
    days: int,
    reason: str,
    commit: bool = True,
) -> dt.datetime:
    """
    Дарит дни доступа, не трогая деньги.

    Отдельно от `grant_subscription` намеренно: та про оплаченный период —
    у неё цена, тариф и место в очереди. Подарок за приглашённого друга не
    оплачен никем, поэтому он не заводит платёж, не меняет цену подписки и
    не попадает в ожидаемую выручку — иначе бесплатные дни однажды
    посчитались бы доходом.

    Дни приклеиваются к самому дальнему живому периоду: человек с оплаченным
    годом получает год и два дня, а не второй период, спорящий с первым за
    право быть действующим. Доступа нет вовсе — заводим отдельный период по
    последнему известному тарифу, чтобы у него были понятные лимиты.

    Возвращает новую дату конца доступа.
    """
    if days <= 0:
        raise PanelError("подарить можно только положительное число дней")

    now = utcnow()
    live = list(
        db.scalars(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.is_cancelled.is_(False),
                Subscription.expires_at > now,
            )
            .order_by(Subscription.expires_at)
        )
    )
    tail = live[-1] if live else None

    if tail is not None:
        tail.expires_at += dt.timedelta(days=days)
        ends_at = tail.expires_at
    else:
        # Тариф берём последний известный: по нему считаются устройства и
        # трафик. Не нашли ни одного — пробный, он есть всегда.
        last = db.scalar(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        code = last.plan if last else settings().signup_plan_code
        plan_ref = db.scalar(select(Plan).where(Plan.code == code))
        bonus = Subscription(
            user_id=user.id,
            plan=plan_ref.code if plan_ref else code,
            plan_id=plan_ref.id if plan_ref else None,
            price=Decimal(0),
            currency=plan_ref.currency if plan_ref else settings().currency,
            period_days=days,
            # Продления от подарка не ждём: в календаре прибыли ему не место.
            auto_renew=False,
            is_bonus=True,
            starts_at=now,
            expires_at=now + dt.timedelta(days=days),
        )
        db.add(bonus)
        ends_at = bonus.expires_at

    from ..models import AuditLog

    db.add(
        AuditLog(
            action="user.bonus_days",
            target=user.public_id,
            detail=f"+{days} дн., {reason}",
        )
    )

    if commit:
        db.commit()
    else:
        db.flush()
    return ends_at


def take_bonus_days(db: OrmSession, user: User, days: int, reason: str, commit: bool = True) -> None:
    """
    Забирает подаренные дни обратно: возврат оплаты отменяет и бонус за неё.

    Иначе накрутка выглядит так: пригласил себя со второго телефона, купил
    самый дешёвый тариф, получил пять дней, сделал возврат — деньги вернули,
    дни остались. Снимаем с самого дальнего живого периода и не заходим за
    сегодняшний день: отбирать уже прожитое бессмысленно.
    """
    if days <= 0:
        return

    now = utcnow()
    live = list(
        db.scalars(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.is_cancelled.is_(False),
                Subscription.expires_at > now,
            )
            .order_by(Subscription.expires_at)
        )
    )
    if not live:
        return

    tail = live[-1]
    tail.expires_at = max(now, tail.expires_at - dt.timedelta(days=days))
    if tail.expires_at <= tail.starts_at:
        tail.is_cancelled = True

    from ..models import AuditLog

    db.add(
        AuditLog(action="user.bonus_revoked", target=user.public_id, detail=f"-{days} дн., {reason}")
    )
    if commit:
        db.commit()
    else:
        db.flush()


# --- платежи -----------------------------------------------------------------


def add_payment(
    db: OrmSession,
    amount: Decimal | float | str,
    user: User | None = None,
    method: str | None = None,
    comment: str | None = None,
    paid_at: dt.datetime | None = None,
    currency: str | None = None,
    external_id: str | None = None,
    subscription_id: int | None = None,
) -> Payment:
    value = Decimal(str(amount))
    if value <= 0:
        raise PanelError("сумма должна быть больше нуля")
    payment = Payment(
        user_id=user.id if user else None,
        subscription_id=subscription_id,
        amount=value,
        currency=currency or settings().currency,
        method=method,
        comment=comment,
        external_id=external_id,
        paid_at=paid_at or utcnow(),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# --- выручка -----------------------------------------------------------------


def revenue_series(db: OrmSession, days: int = 30) -> list[tuple[str, Decimal]]:
    """Выручка по дням за последние `days` дней, включая нулевые дни."""
    since = utcnow() - dt.timedelta(days=days - 1)
    rows = db.execute(select(Payment.paid_at, Payment.amount).where(Payment.paid_at >= since)).all()

    totals: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount in rows:
        totals[paid_at.date().isoformat()] += Decimal(str(amount))

    today = utcnow().date()
    return [
        (
            (today - dt.timedelta(days=offset)).isoformat(),
            totals[(today - dt.timedelta(days=offset)).isoformat()],
        )
        for offset in range(days - 1, -1, -1)
    ]


def revenue_by_month(db: OrmSession, months: int = 12) -> list[tuple[str, Decimal]]:
    rows = db.execute(select(Payment.paid_at, Payment.amount)).all()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount in rows:
        totals[f"{paid_at.year:04d}-{paid_at.month:02d}"] += Decimal(str(amount))

    today = utcnow().date()
    keys: list[str] = []
    year, month = today.year, today.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return [(key, totals[key]) for key in reversed(keys)]


def revenue_by_year(db: OrmSession) -> list[tuple[str, Decimal]]:
    rows = db.execute(select(Payment.paid_at, Payment.amount)).all()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount in rows:
        totals[str(paid_at.year)] += Decimal(str(amount))
    return sorted(totals.items())


def _sum_between(db: OrmSession, start: dt.datetime, end: dt.datetime) -> Decimal:
    value = db.scalar(
        select(func.sum(Payment.amount)).where(Payment.paid_at >= start, Payment.paid_at < end)
    )
    return Decimal(str(value)) if value is not None else Decimal(0)


def revenue_summary(db: OrmSession) -> dict[str, object]:
    """
    Сводка сбоку от календаря: день, неделя, месяц, год.

    Неделя считается от понедельника, а не «минус семь дней»: сводка должна
    сходиться с тем, что человек видит в календаре.
    """
    now = utcnow()
    today = now.date()
    day_start = dt.datetime.combine(today, dt.time.min)
    week_start = dt.datetime.combine(today - dt.timedelta(days=today.weekday()), dt.time.min)
    month_start = dt.datetime.combine(today.replace(day=1), dt.time.min)
    year_start = dt.datetime.combine(today.replace(month=1, day=1), dt.time.min)
    far = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.min)

    prev_day = _sum_between(db, day_start - dt.timedelta(days=1), day_start)
    prev_week = _sum_between(db, week_start - dt.timedelta(days=7), week_start)

    return {
        "day": _sum_between(db, day_start, far),
        "week": _sum_between(db, week_start, far),
        "month": _sum_between(db, month_start, far),
        "year": _sum_between(db, year_start, far),
        "prev_day": prev_day,
        "prev_week": prev_week,
        # Конец месяца считаем по календарю, а не «плюс 31 день»: иначе в
        # короткие месяцы в сводку попадают продления следующего.
        "expected_month": _expected_between(db, month_start, _next_month(month_start))[0],
        "currency": settings().currency,
    }


def _next_month(moment: dt.datetime) -> dt.datetime:
    year, month = moment.year, moment.month
    return dt.datetime(year + 1, 1, 1) if month == 12 else dt.datetime(year, month + 1, 1)


def _expected_between(
    db: OrmSession, start: dt.datetime, end: dt.datetime
) -> tuple[Decimal, dict[str, list[dict[str, object]]]]:
    """
    Ожидаемые поступления: продления, приходящиеся на промежуток.

    Считается только последняя подписка каждого человека и только та, что
    кончается сегодня или позже. Две оговорки, без которых цифра врёт:

    * подписки чередуются встык, и конец предыдущей совпадает с началом
      следующей — взяв любую из истории, мы объявили бы «ожидаемым» то
      продление, которое уже случилось и лежит в платежах этого же дня;
    * прошедший срок не ожидание, а свершившийся факт: человек либо
      заплатил (и это видно в полученном), либо ушёл.
    """
    # Порог — начало сегодняшнего дня: продление, которое ждём сегодня,
    # ещё не опоздало, даже если утро уже прошло.
    today_start = dt.datetime.combine(utcnow().date(), dt.time.min)
    lower = max(start, today_start)
    if lower >= end:
        return Decimal(0), {}

    rows = db.scalars(
        select(Subscription)
        .join(User, Subscription.user_id == User.id)
        .where(
            Subscription.is_cancelled.is_(False),
            Subscription.auto_renew.is_(True),
            User.is_blocked.is_(False),
            # Бесплатные учётки денег не приносят по определению — их
            # «продления» в ожидаемой выручке были бы самообманом.
            User.is_free.is_(False),
        )
        .order_by(Subscription.expires_at.desc())
    )

    total = Decimal(0)
    by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen: set[int] = set()
    for sub in rows:
        # Первая встреченная — самая поздняя: она и есть действующая.
        if sub.user_id in seen:
            continue
        seen.add(sub.user_id)

        if not (lower <= sub.expires_at < end):
            continue
        amount = Decimal(str(sub.price or 0))
        if amount <= 0:
            continue

        total += amount
        by_day[sub.expires_at.date().isoformat()].append(
            {
                "user_id": sub.user_id,
                "public_id": sub.user.public_id,
                "login": sub.user.login,
                "name": sub.user.name,
                "plan": sub.plan,
                "amount": amount,
                "period_days": sub.period_days,
            }
        )
    return total, by_day


def calendar_month(db: OrmSession, year: int, month: int) -> dict[str, object]:
    """
    Месяц для вкладки «Календарь»: по каждому дню — факт и ожидание.

    Дни отдаём все подряд, включая пустые: календарь рисует сетку, и дырки в
    данных превратились бы в дырки в сетке.
    """
    if not 1 <= month <= 12:
        raise PanelError("месяц вне диапазона")

    days_in_month = pycalendar.monthrange(year, month)[1]
    start = dt.datetime(year, month, 1)
    end = start + dt.timedelta(days=days_in_month)

    paid_rows = db.execute(
        select(Payment.paid_at, Payment.amount, Payment.user_id, Payment.method, User.public_id, User.login, User.name)
        .join(User, Payment.user_id == User.id, isouter=True)
        .where(Payment.paid_at >= start, Payment.paid_at < end)
        .order_by(Payment.paid_at)
    ).all()

    actual_by_day: dict[str, Decimal] = defaultdict(Decimal)
    payers_by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for paid_at, amount, user_id, method, public_id, login, name in paid_rows:
        key = paid_at.date().isoformat()
        value = Decimal(str(amount))
        actual_by_day[key] += value
        payers_by_day[key].append(
            {
                "user_id": user_id,
                "public_id": public_id,
                "login": login,
                "name": name,
                "amount": value,
                "method": method,
                "at": paid_at,
            }
        )

    expected_total, expected_by_day = _expected_between(db, start, end)
    today = utcnow().date()

    days = []
    for offset in range(days_in_month):
        date = (start + dt.timedelta(days=offset)).date()
        key = date.isoformat()
        expected = sum((Decimal(str(x["amount"])) for x in expected_by_day.get(key, [])), Decimal(0))
        days.append(
            {
                "date": key,
                "weekday": date.weekday(),
                "is_today": date == today,
                "is_past": date < today,
                "actual": actual_by_day.get(key, Decimal(0)),
                "expected": expected,
                "payments": payers_by_day.get(key, []),
                "renewals": expected_by_day.get(key, []),
            }
        )

    return {
        "year": year,
        "month": month,
        "days": days,
        "actual_total": sum(actual_by_day.values(), Decimal(0)),
        "expected_total": expected_total,
        "currency": settings().currency,
    }


def dashboard_totals(db: OrmSession) -> dict[str, object]:
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def total(since: dt.datetime) -> Decimal:
        value = db.scalar(select(func.sum(Payment.amount)).where(Payment.paid_at >= since))
        return Decimal(str(value)) if value is not None else Decimal(0)

    users = list(db.scalars(select(User)))
    online_since = now - dt.timedelta(minutes=10)

    # «Включён» и «работает» — разные вещи, и путать их дорого: клиент
    # платит, входит в приложение и упирается в пустой список. Считаем
    # отдельно, сколько узлов реально может выдать конфиг.
    from .diagnostics import can_serve

    servers = list(db.scalars(select(Server)))
    servers_usable = sum(1 for s in servers if can_serve(s))

    return {
        "users_total": len(users),
        "users_active": sum(1 for u in users if u.has_access(now)),
        # Людей с поднятым туннелем считаем отдельно от sessions_online:
        # последнее — это открытые приложения, а на «Пользователях» плитка с
        # той же подписью «Сейчас онлайн» считает рукопожатия. Две страницы
        # не должны отвечать разными числами на один вопрос.
        "users_online": sum(1 for u in users if u.is_vpn_connected(now)),
        "users_blocked": sum(1 for u in users if u.is_blocked),
        "traffic_used_bytes": sum(u.traffic_used_bytes for u in users),
        "servers_total": len(servers),
        "servers_active": sum(1 for s in servers if s.is_active),
        "servers_usable": servers_usable,
        "sessions_online": db.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.last_seen_at >= online_since, Session.revoked_at.is_(None))
        )
        or 0,
        "revenue_day": total(day_start),
        "revenue_month": total(month_start),
        "revenue_year": total(year_start),
        "currency": settings().currency,
    }
