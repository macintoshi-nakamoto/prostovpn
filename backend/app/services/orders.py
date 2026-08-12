"""
Заказы: от нажатия «Оплатить» на сайте до выданной учётки.

Главное правило всего файла: заказ переводит в `paid` только вебхук
провайдера. Возврат человека на страницу успеха ничего не подтверждает —
до этого адреса можно дойти, просто набрав его руками, и любой, кто это
сделает, получил бы подписку бесплатно. Страница успеха умеет ровно одно:
спрашивать статус заказа, пока он не станет `paid`.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, payments
from ..config import settings
from ..models import (
    AuditLog,
    Order,
    OrderStatus,
    Plan,
    Subscription,
    User,
    normalize_email,
    utcnow,
)
from ..security import hash_password
from . import credentials
from .billing import grant_subscription
from .errors import PanelError

log = logging.getLogger("panel.orders")


class OrderError(PanelError):
    """Заказ создать не удалось — текст показывается человеку на сайте."""


# --- создание -----------------------------------------------------------------


def public_plans(db: OrmSession) -> list[Plan]:
    """
    Тарифы, которые можно купить: включённые, публичные и с ценой.

    Цена больше нуля — не придирка. Кнопка «купить» у бесплатного тарифа
    упёрлась бы в отказ создать заказ: продать через платёжный сервис
    нечего. Бесплатный тариф получают регистрацией, а не оплатой.
    """
    return [plan for plan in site_plans(db) if plan.price_kopecks > 0]


def site_plans(db: OrmSession) -> list[Plan]:
    """
    Всё, что сайт показывает на витрине, — включая бесплатный пробный.

    Пробный период рекламируют наравне с платными тарифами, и его срок и
    объём трафика человек хочет видеть до регистрации. Значит, сайту нужно
    их откуда-то взять, а единственное место, где они заведены, — панель.
    Раньше запрос их не отдавал, и на странице стояли числа из вёрстки:
    администратор менял пробный период в панели, а сайт продолжал обещать
    прежний.

    Продаваемость при этом остаётся отдельным вопросом: у бесплатного
    тарифа в ответе `purchasable` равно false, и витрина ставит его
    отдельной полосой, а не карточкой с кнопкой оплаты.
    """
    return list(
        db.scalars(
            select(Plan)
            .where(Plan.is_active.is_(True), Plan.is_public.is_(True))
            .order_by(Plan.sort_order, Plan.id)
        )
    )


def create_order(
    db: OrmSession,
    plan_code: str,
    email: str,
    telegram_id: int | None = None,
    ip: str | None = None,
    provider_name: str | None = None,
) -> Order:
    """
    Заводит заказ и регистрирует платёж у провайдера.

    Сумма списывается с тарифа один раз, здесь, и дальше живёт в заказе.
    Пересчитывать её в вебхуке нельзя: между открытием формы и приходом
    денег администратор мог поменять цену, и человек заплатил бы одну сумму,
    а получил проверку на другую.
    """
    address = normalize_email(email)
    if not address or "@" not in address:
        raise OrderError("нужен настоящий адрес почты")

    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None or not plan.is_active:
        raise OrderError("такого тарифа нет")
    if plan.price_kopecks <= 0:
        raise OrderError("этот тариф не продаётся через сайт")

    name = provider_name or payments.active_name()
    order = Order(
        plan_code=plan.code,
        email=address,
        telegram_id=telegram_id,
        amount_kopecks=plan.price_kopecks,
        currency=plan.currency,
        status=OrderStatus.PENDING.value,
        provider=name,
        ip=ip,
        # Продление или первая покупка — видно уже сейчас, по почте. Значение
        # ещё раз уточняется при выдаче: за сутки, пока висит неоплаченный
        # заказ, человек мог купить по той же почте с другого устройства.
        is_renewal=db.scalar(select(User.id).where(User.email == address)) is not None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    try:
        provider = payments.get(name)
        session = provider.create_payment(order)
    except (payments.PaymentError, payments.UnknownProvider) as exc:
        order.status = OrderStatus.FAILED.value
        order.failure_reason = str(exc)
        db.commit()
        raise OrderError(str(exc)) from exc

    order.provider_payment_id = session.payment_id
    order.redirect_url = session.redirect_url
    db.commit()
    db.refresh(order)

    if name == payments.MockProvider.name:
        # Имитация: платёжная форма своя, и подтверждение приходит с неё же.
        log.info("заказ %s создан в режиме имитации оплаты", order.id)

    return order


def find(db: OrmSession, order_id: str) -> Order | None:
    return db.get(Order, order_id)


def expire_stale(db: OrmSession) -> int:
    """Неоплаченный заказ старше суток закрываем: он уже не оплатится."""
    deadline = utcnow() - dt.timedelta(hours=settings().order_ttl_hours)
    stale = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.PENDING.value, Order.created_at < deadline
            )
        )
    )
    for order in stale:
        order.status = OrderStatus.EXPIRED.value
    if stale:
        db.commit()
        log.info("просрочено заказов: %d", len(stale))
    return len(stale)


# --- выдача -------------------------------------------------------------------


class Fulfilment:
    """
    Чем закончилась выдача.

    `password` заполнен только для новой учётки и только в этот момент:
    дальше он живёт зашифрованным и открытым текстом больше нигде не
    появляется.
    """

    __slots__ = ("order", "user", "password", "is_renewal", "expires_at")

    def __init__(
        self,
        order: Order,
        user: User,
        password: str | None,
        is_renewal: bool,
        expires_at: dt.datetime,
    ) -> None:
        self.order = order
        self.user = user
        self.password = password
        self.is_renewal = is_renewal
        self.expires_at = expires_at


def fulfil(db: OrmSession, order: Order, manual_by: int | None = None) -> Fulfilment:
    """
    Создаёт или продлевает доступ по оплаченному заказу.

    Всё в одной транзакции: пользователь, подписка, платёж, отметка на
    заказе и задания на доставку. Задания — строками в таблице, а не
    отправкой письма прямо здесь: почтовый сервер отвечает секунды и падает,
    и держать открытой транзакцию с уже выданной подпиской, пока он думает,
    нельзя. Отправкой займётся отдельный обходчик очереди, уже после
    коммита.
    """
    done = _already_fulfilled(db, order)
    if done is not None:
        # Повторный вызов — например, администратор нажал «выдать вручную»
        # для заказа, который вебхук успел обработать секундой раньше.
        return done

    plan = db.scalar(select(Plan).where(Plan.code == order.plan_code))
    if plan is None:
        raise PanelError(f"тариф «{order.plan_code}» удалён, выдать нечего")

    existing = db.scalar(select(User).where(User.email == order.email))
    password: str | None = None

    if existing is not None:
        user = existing
        is_renewal = True
        # Пароль при продлении не меняем: человек уже вошёл в приложение на
        # всех своих устройствах, и смена пароля выкинула бы его отовсюду
        # ровно в тот момент, когда он заплатил.
        if user.is_blocked:
            user.is_blocked = False
            user.blocked_reason = None
            user.blocked_at = None
        user.is_active = True
    else:
        is_renewal = False
        password = credentials.gen_password()
        user = User(
            login=credentials.free_login(db),
            password_hash=hash_password(password),
            password_enc=crypto.encrypt_or_none(password),
            email=order.email,
            telegram_id=order.telegram_id,
            contact=order.email,
        )
        db.add(user)
        db.flush()

    if order.telegram_id and not user.telegram_id:
        user.telegram_id = order.telegram_id

    subscription = grant_subscription(
        db,
        user,
        days=plan.period_days,
        plan=plan,
        price=float(Decimal(order.amount_kopecks) / 100),
        commit=False,
    )

    order.status = OrderStatus.PAID.value
    order.paid_at = order.paid_at or utcnow()
    order.user_id = user.id
    order.subscription_id = subscription.id
    order.is_renewal = is_renewal
    order.failure_reason = None

    _register_payment(db, order, user, subscription.id)
    _enqueue_delivery(db, order, user, is_renewal)

    if manual_by is not None:
        db.add(
            AuditLog(
                admin_id=manual_by,
                action="order.fulfil_manual",
                target=order.id,
                detail=f"{order.email}, {order.amount_kopecks / 100:.2f} {order.currency}",
            )
        )
    db.add(
        AuditLog(
            admin_id=manual_by,
            action="user.create" if not is_renewal else "user.renew",
            target=user.public_id,
            detail=f"заказ {order.id[:8]}, тариф {plan.code}",
        )
    )

    try:
        db.commit()
    except IntegrityError:
        # Гонка: по этому же заказу выдача шла вторым потоком (кнопка в
        # панели и вебхук приходят одновременно) и успела закоммитить
        # раньше. Ловится уникальностью почты, а после добавления
        # уникальности на payments.order_id — и при продлении. Проигравший
        # не должен отвечать ошибкой: повторный вызов обязан быть
        # идемпотентным, и здесь он им и становится.
        db.rollback()
        fresh = db.get(Order, order.id, populate_existing=True)
        done = _already_fulfilled(db, fresh) if fresh is not None else None
        if done is None:
            raise
        log.warning("заказ %s выдан параллельной попыткой, эта отменена", order.id)
        return done

    db.refresh(user)

    # Новый оплаченный период — новый счёт трафика. После коммита: обнуление
    # счётчика не должно откатывать выданную подписку, если что-то пойдёт не
    # так, а без него человек упрётся в лимит прошлого месяца.
    user.traffic_used_bytes = 0
    user.traffic_reset_at = utcnow()
    db.commit()

    _ensure_keys_safely(db, user)

    return Fulfilment(order, user, password, is_renewal, subscription.expires_at)


def _already_fulfilled(db: OrmSession, order: Order) -> Fulfilment | None:
    """Заказ уже выдан — тем же ответом, что и в первый раз, или None."""
    if order.status != OrderStatus.PAID.value or not order.user_id:
        return None
    user = db.get(User, order.user_id)
    sub = user.active_subscription() if user else None
    return Fulfilment(order, user, None, True, sub.expires_at if sub else utcnow())


def _register_payment(db: OrmSession, order: Order, user: User, subscription_id: int) -> None:
    """Платёж в общую кассу — из неё считается календарь прибыли."""
    from ..models import Payment

    db.add(
        Payment(
            user_id=user.id,
            subscription_id=subscription_id,
            order_id=order.id,
            amount=Decimal(order.amount_kopecks) / 100,
            currency=order.currency,
            method=order.provider,
            external_id=order.provider_payment_id,
            comment=f"Заказ {order.id[:8]}, тариф {order.plan_code}",
            paid_at=order.paid_at or utcnow(),
        )
    )


def _enqueue_delivery(db: OrmSession, order: Order, user: User, is_renewal: bool) -> None:
    from ..models import DeliveryJob

    template = "renewed" if is_renewal else "credentials"
    db.add(
        DeliveryJob(
            channel="email",
            template=template,
            target=order.email,
            user_id=user.id,
            order_id=order.id,
        )
    )
    if order.telegram_id:
        db.add(
            DeliveryJob(
                channel="telegram",
                template=template,
                target=str(order.telegram_id),
                user_id=user.id,
                order_id=order.id,
            )
        )


def _ensure_keys_safely(db: OrmSession, user: User) -> None:
    """
    Пиры на серверах — после выдачи и вне транзакции.

    Ключи создаются по SSH, и недоступный узел не должен ни задерживать
    ответ провайдеру, ни тем более откатывать оплаченную подписку.
    Приложение всё равно досоздаёт недостающее при первом входе.
    """
    from .keys import ensure_keys

    try:
        warnings = ensure_keys(db, user)
    except Exception:  # pragma: no cover - зависит от доступности узлов
        log.exception("не удалось выдать ключи пользователю %s", user.public_id)
        return
    for warning in warnings:
        log.warning("выдача ключей %s: %s", user.public_id, warning)


# --- возврат ------------------------------------------------------------------


def refund(db: OrmSession, order: Order, reason: str = "возврат платежа") -> None:
    """
    Возврат или оспаривание: снимается ровно то, за что вернули деньги.

    Подписка помечается отменённой, а не удаляется: история платежей должна
    сходиться, а по удалённой строке потом не объяснить, куда делись деньги.
    По той же причине платёж не стирается, а сторнируется отдельной
    отрицательной строкой — иначе выручка в календаре и сводках навсегда
    осталась бы завышенной.

    Остальные оплаченные периоды не трогаются. Человек, купивший год и
    оспоривший последнее продление, не должен терять оплаченный год и
    получать бан за возврат тридцати рублей.
    """
    if order.status == OrderStatus.REFUNDED.value:
        # Повторный возврат: частичные возвраты приходят разными событиями,
        # а кнопка в панели нажимается сколько угодно раз. Сторнировать один
        # платёж дважды — занизить выручку ровно на ту же сумму.
        return

    order.status = OrderStatus.REFUNDED.value
    order.failure_reason = reason

    if order.subscription_id:
        subscription = db.get(Subscription, order.subscription_id)
        if subscription is not None:
            subscription.is_cancelled = True

    _register_refund(db, order, reason)

    user = db.get(User, order.user_id) if order.user_id else None
    db.commit()

    if user is not None:
        db.refresh(user)
        _close_access_after_refund(db, order, user, reason)

    db.add(AuditLog(action="order.refund", target=order.id, detail=reason))
    db.commit()


def _register_refund(db: OrmSession, order: Order, reason: str) -> None:
    """
    Сторно платежа: та же сумма со знаком минус.

    Компенсирующей строкой, а не отметкой на исходной: выручку считают
    шесть разных мест (день, месяц, год, календарь, сводка, произвольный
    период), и все они просто складывают `payments.amount`. Отрицательная
    строка чинит их разом и не забудется в следующем отчёте.

    Дата сторно — момент возврата, а не дата платежа: закрытые периоды не
    должны задним числом менять цифры.
    """
    from ..models import Payment

    original = db.scalar(
        select(Payment).where(Payment.order_id == order.id, Payment.amount > 0)
    )
    if original is None:
        return
    compensated = db.scalar(
        select(Payment.id).where(Payment.order_id == order.id, Payment.amount < 0)
    )
    if compensated is not None:
        return

    db.add(
        Payment(
            user_id=original.user_id,
            subscription_id=original.subscription_id,
            order_id=order.id,
            amount=-original.amount,
            currency=original.currency,
            method=original.method,
            external_id=original.external_id,
            comment=f"Возврат по заказу {order.id[:8]}: {reason}",
            paid_at=utcnow(),
        )
    )


def _close_access_after_refund(db: OrmSession, order: Order, user: User, reason: str) -> None:
    """
    Что снимать после возврата — по тому, что у человека осталось.

    Две разные величины, и путать их нельзя. `active_subscription` не
    смотрит на `starts_at`, поэтому ещё не начавшийся оплаченный период она
    считает действующим — для пиров это неверно, а для решения «банить ли
    учётку насовсем» как раз верно.
    """
    from .keys import revoke_key
    from .users import revoke_access

    now = utcnow()
    running = any(
        s.starts_at <= now < s.expires_at and not s.is_cancelled for s in user.subscriptions
    )
    remaining = any(not s.is_cancelled and s.expires_at > now for s in user.subscriptions)

    if running:
        # Оплаченный период идёт прямо сейчас — доступ остаётся как был.
        return

    if not remaining:
        problems = revoke_access(db, user, reason=reason)
        for problem in problems:
            log.error("возврат по заказу %s: пир не снят — %s", order.id, problem)
        return

    # Действующего периода нет, но есть оплаченный будущий: туннель гасим, а
    # учётку не блокируем. Бан здесь вывел бы её из-под expire_overdue и
    # встретил бы человека необъяснимым отказом в день начала периода.
    for key in list(user.keys):
        if key.revoked_at is not None:
            continue
        try:
            revoke_key(db, key)
        except Exception as exc:  # pragma: no cover - зависит от доступности узлов
            log.error("возврат по заказу %s: пир не снят — %s: %s", order.id, key.server.name, exc)
