"""
Демонстрационные данные для пустой базы.

Включается через PANEL_SEED_DEMO=1 и работает только если пользователей ещё
нет: повторный запуск ничего не портит и не удваивает.

Ключи здесь создаются записями в базе, минуя SSH: демо не должно требовать
живых серверов, а вкладка «Ключи» без них выглядела бы пустой.
"""

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import crypto, provisioning
from .services.translit import slugify
from .models import (
    GB,
    Payment,
    Plan,
    Provisioning,
    Server,
    Session,
    Subscription,
    User,
    UserKey,
    new_public_id,
    utcnow,
)
from .security import hash_password, new_token, token_hash

AWG_TEMPLATE = """[Interface]
Address = {address}
PrivateKey = {private_key}
DNS = 1.1.1.1, 1.0.0.1
MTU = 1280
Jc = 4
Jmin = 230
Jmax = 649
S1 = 56
S2 = 61
H1 = 1735837
H2 = 1256981
H3 = 1476102
H4 = 1231234

[Peer]
PublicKey = SERVER_PUBLIC_KEY_PLACEHOLDER
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint}:51820
PersistentKeepalive = 25
"""

# Адреса из RFC 5737 (документационные): они гарантированно никому не
# принадлежат. Демо-данные не должны приводить к попыткам зайти по SSH на
# чужую живую машину.
SERVERS = [
    # имя, страна, страна (en), город, код, хост
    ("nl-ams-01", "Нидерланды", "Netherlands", "Амстердам", "NL", "192.0.2.11"),
    ("de-fra-01", "Германия", "Germany", "Франкфурт", "DE", "192.0.2.12"),
    ("fi-hel-01", "Финляндия", "Finland", "Хельсинки", "FI", "198.51.100.13"),
    ("tr-ist-01", "Турция", "Turkey", "Стамбул", "TR", "198.51.100.14"),
    ("us-nyc-01", "США", "United States", "Нью-Йорк", "US", "203.0.113.15"),
]

NAMES = [
    "Алексей Ковалёв", "Марина Тихонова", "Дмитрий Соколов", "Ольга Белова",
    "Иван Морозов", "Екатерина Лапина", "Сергей Ершов", "Анна Гусева",
    "Павел Зайцев", "Ксения Орлова", "Никита Фомин", "Юлия Панова",
    "Артём Волков", "Дарья Крылова", "Роман Судаков", "Вера Шилова",
    "Максим Гордеев", "Полина Рыбина", "Егор Летов", "Мария Носова",
    "Тимур Асланов", "Светлана Рогова", "Кирилл Ткачук", "Наталья Дёмина",
]

METHODS = ["Карта", "СБП", "USDT", "Telegram Stars"]
PLATFORMS = [("windows", "2.1.4"), ("android", "2.1.2"), ("ios", "2.0.9"), ("macos", "2.1.4")]


def seed_demo(db: OrmSession) -> None:
    if db.scalar(select(User).limit(1)) is not None:
        return

    rnd = random.Random(20260810)
    now = utcnow()

    plans = {p.code: p for p in db.scalars(select(Plan))}
    if not plans:
        return

    servers = _make_servers(db)
    _make_users(db, rnd, now, plans, servers)


def _make_servers(db: OrmSession) -> list[Server]:
    servers: list[Server] = []
    for order, (name, country, country_en, city, code, host) in enumerate(SERVERS):
        server = Server(
            name=name,
            country=country,
            country_en=country_en,
            city=city,
            country_code=code,
            host=host,
            port=51820,
            # Последний сервер выключен — пусть в панели будет видно и такое.
            is_active=code != "US",
            sort_order=order,
            provisioning=Provisioning.SSH,
            ssh_host=host,
            ssh_user="root",
            awg_template=AWG_TEMPLATE.replace("{endpoint}", host),
        )
        db.add(server)
        servers.append(server)
    db.commit()
    for server in servers:
        db.refresh(server)
    return servers


def _make_users(
    db: OrmSession,
    rnd: random.Random,
    now: dt.datetime,
    plans: dict[str, Plan],
    servers: list[Server],
) -> None:
    active_servers = [s for s in servers if s.is_active]
    address_counter = {s.id: 1 for s in servers}

    # Тарифы берём те, что реально есть в базе, а не по именам из кода:
    # коды меняются, а падение демо-данных на старте выглядит как поломка
    # панели, хотя ломается только генератор выдуманных людей.
    codes = sorted(plans)
    weighted = [code for code in codes for _ in range(2 if code == "basic" else 1)] or codes

    for index, full_name in enumerate(NAMES):
        plan = plans[rnd.choice(weighted)]

        # Раскидываем регистрации по последним пяти месяцам, чтобы графики и
        # календарь были не одной точкой.
        created = now - dt.timedelta(days=rnd.randint(1, 150), hours=rnd.randint(0, 23))
        password = f"demo{rnd.randint(1000, 9999)}"

        user = User(
            public_id=new_public_id(),
            login=f"{slugify(full_name)}-{rnd.randint(100, 999)}",
            password_hash=hash_password(password),
            # Как и у настоящих учёток: только шифротекст, никакого
            # открытого текста в базе даже у выдуманных людей.
            password_enc=crypto.encrypt_or_none(password),
            name=full_name,
            contact=f"@{slugify(full_name).split('-')[0]}{rnd.randint(10, 99)}",
            created_at=created,
        )
        # Как у настоящих: шифротекст и слепой индекс, не открытое поле.
        user.set_email(f"{slugify(full_name)}{index}@example.com")

        # Пятеро с личным лимитом, остальные — по тарифу.
        if index % 5 == 0:
            user.traffic_limit_bytes = rnd.choice([50, 200, 500]) * GB

        db.add(user)
        db.commit()
        db.refresh(user)

        state = _pick_state(index)
        _make_subscription_and_payments(db, rnd, now, user, plan, created, state)
        _make_traffic(rnd, user, state)
        _make_keys(db, rnd, user, active_servers, address_counter, state)
        _make_sessions(db, rnd, now, user, state)

        if state == "blocked":
            user.is_blocked = True
            user.blocked_reason = rnd.choice(
                ["Возврат платежа", "Раздача доступа третьим лицам", "Жалоба хостера"]
            )
            user.blocked_at = now - dt.timedelta(days=rnd.randint(1, 20))
        elif state == "paused":
            user.is_active = False
        db.commit()


def _pick_state(index: int) -> str:
    """Раскладка состояний: большинство платит, меньшинство — нет."""
    if index % 11 == 3:
        return "blocked"
    if index % 9 == 5:
        return "paused"
    if index % 7 == 2:
        return "expired"
    return "active"


def _make_subscription_and_payments(
    db: OrmSession,
    rnd: random.Random,
    now: dt.datetime,
    user: User,
    plan: Plan,
    created: dt.datetime,
    state: str,
) -> None:
    price = Decimal(str(plan.price))
    period = dt.timedelta(days=plan.period_days)

    # Периоды строим назад от конца текущего, а не вперёд от регистрации:
    # только так последний период гарантированно накрывает сегодняшний день
    # (или кончается в прошлом у просроченных), а не уезжает в будущее.
    if state == "expired":
        end = now - dt.timedelta(days=rnd.randint(2, 25))
    else:
        # Действующие — с концом в ближайшие недели, чтобы в календаре были
        # и ожидаемые продления. Не дальше длины самого периода: иначе
        # «осталось дней» окажется больше, чем срок тарифа.
        end = now + dt.timedelta(days=rnd.randint(1, max(1, min(plan.period_days, 30))))

    # За срок жизни клиента набегает несколько оплат, и календарь прошлых
    # месяцев не должен быть пустым.
    periods = min(6, max(1, (now - created).days // max(plan.period_days, 1) + 1))

    subs: list[Subscription] = []
    for _ in range(periods):
        starts = end - period
        sub = Subscription(
            user_id=user.id,
            plan=plan.code,
            plan_id=plan.id,
            price=price,
            currency=plan.currency,
            period_days=plan.period_days,
            auto_renew=state != "blocked",
            starts_at=starts,
            expires_at=end,
            created_at=starts,
        )
        db.add(sub)
        subs.append(sub)

        if price > 0:
            db.add(
                Payment(
                    user_id=user.id,
                    subscription_id=None,
                    amount=price,
                    currency=plan.currency,
                    method=rnd.choice(METHODS),
                    comment=f"Оплата тарифа «{plan.name}»",
                    paid_at=starts,
                )
            )
        end = starts

    if subs and state == "blocked":
        subs[0].is_cancelled = True
    db.commit()


def _make_traffic(rnd: random.Random, user: User, state: str) -> None:
    limit = user.effective_traffic_limit()
    if limit is None:
        user.traffic_used_bytes = rnd.randint(3, 900) * GB // 10
        return
    # Один из шести — упёрся в лимит: такое состояние в панели надо видеть.
    share = rnd.choice([0.05, 0.2, 0.35, 0.6, 0.85, 1.05])
    user.traffic_used_bytes = int(limit * share)


def _make_keys(
    db: OrmSession,
    rnd: random.Random,
    user: User,
    servers: list[Server],
    address_counter: dict[int, int],
    state: str,
) -> None:
    if state == "blocked":
        return
    for server in servers:
        address_counter[server.id] += 1
        octet = address_counter[server.id]
        address = f"10.8.1.{octet}/32"
        private_key, public_key = provisioning.generate_keypair()
        config = provisioning.render_from_template(server.awg_template or "", private_key, address)

        rx = rnd.randint(0, 40) * GB // 10
        tx = rnd.randint(0, 25) * GB // 10
        db.add(
            UserKey(
                user_id=user.id,
                server_id=server.id,
                config=config,
                public_key=public_key,
                address=address,
                rx_bytes=rx,
                tx_bytes=tx,
                last_handshake_at=utcnow() - dt.timedelta(minutes=rnd.randint(1, 4000)),
                traffic_synced_at=utcnow(),
            )
        )
    db.commit()


def _make_sessions(
    db: OrmSession, rnd: random.Random, now: dt.datetime, user: User, state: str
) -> None:
    if state == "blocked":
        return
    for _ in range(rnd.randint(1, 3)):
        platform, version = rnd.choice(PLATFORMS)
        # Часть сессий — свежие: панель показывает их как «онлайн».
        last_seen = now - dt.timedelta(minutes=rnd.choice([1, 3, 7, 40, 600, 4000]))
        db.add(
            Session(
                user_id=user.id,
                token_hash=token_hash(new_token()),
                platform=platform,
                app_version=version,
                ip=f"{rnd.randint(31, 213)}.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}",
                created_at=last_seen - dt.timedelta(days=rnd.randint(0, 30)),
                last_seen_at=last_seen,
                expires_at=now + dt.timedelta(days=rnd.randint(1, 30)),
            )
        )
    db.commit()


