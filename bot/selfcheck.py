"""Проверка бота без Telegram: python selfcheck.py

Читает панель только на чтение: тарифы и список приложений. Ничего не
создаёт и не меняет.
"""

import asyncio
import datetime as dt
import json
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.settings import SUPPORT_TOPICS, config, method_by_code
from database import db, models
from keyboards import menus
from keyboards.ui import DANGER, DEFAULT, PRIMARY, SUCCESS
from utils import assets, panel, texts
from utils.security import login_error, password_error


ALLOWED_STYLES = {PRIMARY, SUCCESS, DANGER, DEFAULT}

USER_ID = 999_000_111

NOW = dt.datetime.now().replace(microsecond=0)

FAKE_PLAN = panel.Plan(
    code="basic",
    title="Базовый",
    duration_days=30,
    price_kopecks=19900,
    currency="RUB",
    device_limit=2,
    traffic_limit_bytes=250 * 1024**3,
    purchasable=True,
)

FAKE_ACCOUNT = panel.Account(
    login="tester_01",
    active=True,
    plan="basic",
    plan_title="Базовый",
    expires_at=NOW + dt.timedelta(days=28),
    days_left=28,
    device_limit=2,
    devices=1,
    traffic_used_bytes=12 * 1024**3,
    traffic_limit_bytes=250 * 1024**3,
    payments=[panel.Payment(amount=199.0, currency="RUB", comment="Продление", paid_at=NOW)],
)

EMPTY_ACCOUNT = panel.Account(
    login="tester_01",
    active=False,
    plan=None,
    plan_title=None,
    expires_at=None,
    days_left=None,
    device_limit=0,
    devices=0,
    traffic_used_bytes=0,
    traffic_limit_bytes=None,
    payments=[],
)

FAKE_APPS = [
    panel.Download(platform="windows", version="1.0.27", url="https://prostovpn.cc/a.msi"),
    panel.Download(platform="android", version="1.1.2", url="https://prostovpn.cc/a.apk"),
]


# Цвет разрешён только этим кнопкам — остальные серые.
COLORED = (
    "Тарифы",
    "Продлить",
    "Оформить",
    "Оплатить",
    "Stars",
    "СБП",
    "карта",
    "Назад",
    "Отмена",
    "Меню",
    "Выйти",
)

FAKE_REC_ACTIVE = panel.Recurring(
    status="active",
    plan_code="basic",
    plan_title="Базовый",
    amount_kopecks=19900,
    currency="RUB",
    interval="month",
    next_charge_at=NOW + dt.timedelta(days=30),
)

FAKE_REC_PENDING = panel.Recurring(
    status="pending",
    plan_code="basic",
    plan_title="Базовый",
    amount_kopecks=19900,
    currency="RUB",
    interval="month",
    redirect_url="https://pay.example/sub",
)

FAKE_REC_PAST_DUE = panel.Recurring(
    status="past_due",
    plan_code="basic",
    plan_title="Базовый",
    amount_kopecks=19900,
    currency="RUB",
    interval="month",
    last_charge_error="списание не прошло",
)


def check_keyboards() -> None:
    boards = {
        "start": menus.start_menu(),
        "gate_new": menus.gate_menu(False),
        "gate_known": menus.gate_menu(True),
        "main": menus.main_menu(),
        "cabinet": menus.cabinet_menu(True),
        "cabinet_empty": menus.cabinet_menu(False),
        # Кабинет человека с iPhone: у него на кнопку больше — ключ для
        # AmneziaVPN, потому что приложения под iOS нет.
        "cabinet_ios": menus.cabinet_menu(True, ios=True),
        "methods": menus.payment_methods_menu(),
        "plans": menus.plans_menu([FAKE_PLAN], method_by_code("stars")),
        "plans_sbp": menus.plans_menu([FAKE_PLAN], method_by_code("sbp")),
        "pay_link": menus.pay_link_menu("https://pay.example/invoice"),
        "autorenew_offer": menus.autorenew_menu(None, [FAKE_PLAN]),
        "autorenew_pending": menus.autorenew_menu(FAKE_REC_PENDING, []),
        "autorenew_active": menus.autorenew_menu(FAKE_REC_ACTIVE, []),
        "autorenew_past_due": menus.autorenew_menu(FAKE_REC_PAST_DUE, []),
        "support": menus.support_menu(),
        "topic": menus.topic_menu(SUPPORT_TOPICS[0].code),
        "about": menus.about_menu(True, FAKE_APPS),
        "cancel": menus.cancel_menu(),
        "ticket_created": menus.ticket_created_menu(),
        "after_payment": menus.after_payment_menu(),
        "back": menus.back_menu(),
    }

    colored = 0

    for name, board in boards.items():
        for row in board.inline_keyboard:
            for button in row:
                payload = json.loads(button.model_dump_json(exclude_none=True))
                style = payload.get("style")

                assert style in ALLOWED_STYLES, f"{name}: стиль {style}"
                assert payload.get("icon_custom_emoji_id"), f"{name}: нет иконки"
                assert payload.get("callback_data") or payload.get("url"), name

                if style != DEFAULT:
                    colored += 1
                    assert any(word in button.text for word in COLORED), (
                        f"{name}: цветная кнопка «{button.text}» не входит в список важных"
                    )

    for board_name in ("main", "support", "cabinet"):
        rows = boards[board_name].inline_keyboard
        support_rows = [row for row in rows if any("Поддержка" in b.text for b in row)]

        for row in support_rows:
            assert len(row) == 1, f"{board_name}: поддержка должна быть на всю ширину"

    method_labels = [b.text for row in boards["methods"].inline_keyboard for b in row]

    for expected in ("Telegram Stars", "СБП", "Криптовалюта"):
        assert any(expected in label for label in method_labels), f"нет способа {expected}"

    plan_labels = [b.text for row in boards["plans"].inline_keyboard for b in row]

    assert any("★" in label for label in plan_labels), "в списке тарифов нет цены в звёздах"

    about_rows = [
        row for row in boards["main"].inline_keyboard if any("О сервисе" in b.text for b in row)
    ]

    assert about_rows and len(about_rows[0]) == 1, "«О сервисе» должно стоять отдельной строкой"

    # Инструкция по установке — сразу под каналом: сюда идут после того,
    # как скачали приложение или получили ключ.
    main_rows = boards["main"].inline_keyboard
    channel_at = next(i for i, row in enumerate(main_rows) if any("канал" in b.text for b in row))
    guide_row = main_rows[channel_at + 1]

    assert len(guide_row) == 1 and "Инструкция" in guide_row[0].text, (
        "под «Наш канал» должна стоять кнопка инструкции"
    )
    assert guide_row[0].url, "кнопка инструкции должна вести ссылкой на сайт"

    # Список российских сервисов — строка на всю ширину прямо над поддержкой: с вопросом
    # «почему не открывается банк» приходят именно в поддержку.
    cabinet_rows = boards["cabinet"].inline_keyboard
    support_at = next(
        i for i, row in enumerate(cabinet_rows) if any("Поддержка" in b.text for b in row)
    )
    bypass_row = cabinet_rows[support_at - 1]

    assert len(bypass_row) == 1 and "Российские сервисы" in bypass_row[0].text, (
        "над поддержкой в кабинете должна стоять кнопка списка российских сервисов"
    )

    ios_labels = [b.text for row in boards["cabinet_ios"].inline_keyboard for b in row]

    assert any("iPhone" in label for label in ios_labels), "в кабинете iOS нет кнопки ключа"

    # Автопродление: в кабинете есть вход, счёт даёт кнопку-ссылку, отключение
    # везде одно и серое — случайный клик не должен отменять подписку.
    cabinet_labels = [b.text for row in cabinet_rows for b in row]

    assert any("Автопродление" in label for label in cabinet_labels), (
        "в кабинете нет кнопки автопродления"
    )

    pay_buttons = [b for row in boards["pay_link"].inline_keyboard for b in row]

    assert any(b.url and "Оплатить" in b.text for b in pay_buttons), (
        "на экране счёта нет кнопки-ссылки «Оплатить»"
    )

    pending_buttons = [b for row in boards["autorenew_pending"].inline_keyboard for b in row]

    assert any(b.url and "Привязать" in b.text for b in pending_buttons), (
        "на экране оформления нет ссылки на привязку счёта"
    )

    for name in ("autorenew_pending", "autorenew_active", "autorenew_past_due"):
        off_buttons = [
            b
            for row in boards[name].inline_keyboard
            for b in row
            if b.callback_data == "rec:off"
        ]

        assert len(off_buttons) == 1, f"{name}: отключение должно быть одной кнопкой"

    print(f"клавиатуры: {len(boards)} экранов, цветных кнопок {colored}, остальные серые")


def check_texts() -> None:
    ticket = models.Ticket(
        id=1,
        user_id=USER_ID,
        panel_login="tester_01",
        topic="Оплата",
        message="деньги <ушли>",
        status="new",
        answer=None,
        created_at=NOW,
    )

    screens = [
        texts.start_text(),
        texts.gate_text(None),
        texts.gate_text("tester_01"),
        texts.main_text(FAKE_ACCOUNT),
        texts.main_text(EMPTY_ACCOUNT),
        texts.cabinet_text(FAKE_ACCOUNT),
        texts.cabinet_text(EMPTY_ACCOUNT),
        texts.methods_text(),
        texts.plans_text(method_by_code("stars"), [FAKE_PLAN]),
        texts.plans_text(method_by_code("sbp"), [FAKE_PLAN]),
        texts.invoice_text(FAKE_PLAN),
        texts.autorenew_text(None, [FAKE_PLAN]),
        texts.autorenew_text(FAKE_REC_PENDING, []),
        texts.autorenew_text(FAKE_REC_ACTIVE, []),
        texts.autorenew_text(FAKE_REC_PAST_DUE, []),
        texts.paid_text(FAKE_PLAN, FAKE_ACCOUNT),
        texts.paid_text(FAKE_PLAN, None),
        texts.about_text(),
        texts.support_text(),
        texts.topic_text(SUPPORT_TOPICS[0]),
        texts.ticket_prompt_text(SUPPORT_TOPICS[0]),
        texts.ticket_prompt_text(None),
        texts.ticket_created_text(1),
        texts.tickets_text([ticket]),
        texts.tickets_text([]),
        texts.history_text(FAKE_ACCOUNT.payments),
        texts.history_text([]),
    ]

    for screen in screens:
        assert screen.strip() and len(screen) < 1024, screen

    assert "Начните с личного кабинета" not in texts.start_text()
    assert login_error("ab") and not login_error("tester_01")
    assert password_error("1234567") and not password_error("secret123")

    print(f"тексты: {len(screens)} экранов, все короче подписи Telegram")


async def check_panel() -> None:
    plans = await panel.plans()

    assert plans, "панель не отдала тарифы"

    for plan in plans:
        assert plan.stars > 0
        print(
            f"  {plan.code:8} {plan.title:12} {plan.duration_days:3} дн"
            f"  {plan.rub:5} ₽  {plan.stars:4} ★  устройств {plan.device_limit}"
        )

    apps = await panel.downloads()

    print(f"панель {config.panel_url}: тарифов {len(plans)}, приложений {len(apps)}")


async def check_storage() -> None:
    await db.init()
    await drop_test_user()

    await models.upsert_user(USER_ID, "tester", "Тестер")

    assert await models.get_session(USER_ID) is None

    await models.save_session(USER_ID, "tester_01", "token", NOW + dt.timedelta(days=30))
    session = await models.get_session(USER_ID)

    assert session and session.panel_login == "tester_01"
    assert await models.last_login(USER_ID) == "tester_01"

    ticket_id = await models.add_ticket(USER_ID, "tester_01", "Оплата", "не прошла <b>оплата</b>")
    await models.answer_ticket(ticket_id, "вернули")
    tickets = await models.last_tickets(USER_ID)

    assert tickets and tickets[0].status == "answered"

    await models.save_session(USER_ID, "tester_01", "token", NOW - dt.timedelta(days=1))
    assert await models.get_session(USER_ID) is None, "протухшая сессия должна отпадать"

    await drop_test_user()

    print("база бота: сессии и обращения — ок")


async def drop_test_user() -> None:
    async with models._connect() as connection:
        for table in ("sessions", "tickets", "users"):
            await connection.execute(f"DELETE FROM {table} WHERE user_id = ?", (USER_ID,))

        await connection.commit()


def check_assets() -> None:
    files = [
        assets.WELCOME,
        assets.MENU,
        assets.GATE,
        assets.LOGIN_LOGIN,
        assets.LOGIN_PASSWORD,
        assets.PASSWORD,
        assets.PAYMENTS,
        assets.ABOUT,
        assets.CABINET_ACTIVE,
        assets.CABINET_INACTIVE,
        assets.PLANS,
        assets.SUPPORT,
    ]

    for path in files:
        assert path.exists(), f"нет анимации {path.name}"
        assert path.read_bytes()[4:8] == b"ftyp", f"{path.name} не похож на mp4"

    total = sum(path.stat().st_size for path in files) / 1024 / 1024
    print(f"анимации: {len(files)} файлов на месте, {total:.1f} МБ")


async def main() -> None:
    check_keyboards()
    check_assets()
    check_texts()
    await check_storage()
    await check_panel()
    await panel.close()
    print("selfcheck пройден")


if __name__ == "__main__":
    asyncio.run(main())
