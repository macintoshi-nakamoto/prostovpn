"""Экраны бота, собранные блоками.

Каждая функция возвращает готовый список блоков: заставка раздела сверху,
содержимое, отступ перед кнопками. Тексты живут рядом, в utils/texts.py.
"""

from config.settings import PayMethod, SupportTopic, config
from database.models import Ticket
from utils import rich, texts, timeutils
from utils.panel import Account, Download, Payment, Plan


PLATFORM_TITLES = {
    "windows": "Windows",
    "android": "Android",
    "macos": "macOS",
    "ios": "iPhone",
    "linux": "Linux",
}


def start(file_id: str | None) -> list[dict]:
    """Первый экран: заставка, главная мысль и три пункта."""
    return rich.screen(
        file_id,
        rich.paragraph(rich.bold(texts.START_LEAD)),
        rich.bullets(*texts.START_POINTS),
    )


def gate(file_id: str | None, login: str | None) -> list[dict]:
    blocks = [
        rich.title("Личный кабинет"),
        rich.paragraph("Логин и пароль те же, что на сайте и в приложении."),
    ]

    if login:
        blocks.append(rich.facts(("Прошлый вход", rich.code(login))))

    return rich.screen(file_id, *blocks)


def main(file_id: str | None, account: Account) -> list[dict]:
    return rich.screen(
        file_id,
        rich.title(config.brand),
        rich.paragraph(rich.bold(_status(account))),
    )


def cabinet(file_id: str | None, account: Account) -> list[dict]:
    rows: list[tuple[str, object]] = [("Логин", rich.code(account.login))]

    if account.active:
        rows.append(("Тариф", account.plan_title or "Подписка"))

        if account.expires_at:
            rows.append(("Действует до", timeutils.human_date(account.expires_at)))

        rows.append(("Осталось", timeutils.plural_days(account.days_left or 0)))

        if account.traffic_limit_bytes:
            used = account.traffic_used_bytes / 1024**3
            limit = account.traffic_limit_bytes / 1024**3
            rows.append(("Трафик", f"{used:.0f} из {limit:.0f} ГБ"))
        else:
            rows.append(("Трафик", "безлимит"))

        if account.device_limit:
            rows.append(("Устройства", f"{account.devices} из {account.device_limit}"))

        return rich.screen(file_id, rich.title("Личный кабинет"), rich.facts(*rows))

    return rich.screen(
        file_id,
        rich.title("Личный кабинет"),
        rich.facts(*rows),
        rich.paragraph(rich.bold("Подписка не активна")),
        rich.paragraph("Выберите тариф - доступ включится сразу после оплаты."),
    )


def methods(file_id: str | None) -> list[dict]:
    return rich.screen(
        file_id,
        rich.title("Тарифы и оплата"),
        rich.paragraph("Выберите способ оплаты - дальше покажу тарифы."),
        rich.paragraph(
            rich.italic(
                "Оплачивая, вы принимаете условия пользовательского соглашения — "
                "оно и остальные документы в разделе «Документы»."
            )
        ),
    )


def docs(file_id: str | None) -> list[dict]:
    """Правовые документы. Сами тексты — на сайте, здесь только кнопки."""
    return rich.screen(
        file_id,
        rich.title("Документы"),
        rich.bullets(
            "Пользовательское соглашение",
            "Политика конфиденциальности",
            "Правила использования",
            "Возврат средств",
        ),
        rich.paragraph(rich.italic("Открываются на сайте.")),
        rich.facts(("Поддержка", rich.code(texts.SUPPORT_EMAIL))),
    )


def plans(file_id: str | None, method: PayMethod, available: list[Plan]) -> list[dict]:
    # Не таблицей: колонок под все условия нужно пять, и на телефоне они
    # схлопываются в нечитаемое. Пара строк на тариф — название с ценой
    # жирным, условия под ним — читается и в узком окне.
    blocks = [rich.title(f"Тарифы · {method.title}")]

    for plan in available:
        blocks.append(
            rich.paragraph(rich.bold(f"{plan.title} — {texts.plan_price(plan, method)}"))
        )
        blocks.append(rich.paragraph(texts.plan_terms(plan)))

    blocks.append(rich.paragraph(rich.italic("Дни складываются с текущей подпиской.")))

    # Цены настоящие, оплата этим способом ещё подключается — говорим об этом
    # на самом экране, а не только в ответе на нажатие.
    if method.catalog_only:
        blocks.append(
            rich.paragraph(
                rich.italic(
                    f"Оплата через {method.title} подключается. "
                    "Сейчас доступна оплата звёздами Telegram."
                )
            )
        )

    return rich.screen(file_id, *blocks)


def paid(file_id: str | None, plan: Plan, account: Account | None) -> list[dict]:
    rows: list[tuple[str, object]] = [
        ("Тариф", plan.title),
        ("Добавлено", timeutils.plural_days(plan.duration_days)),
    ]

    if account and account.expires_at:
        rows.append(("Действует до", timeutils.human_date(account.expires_at)))

    return rich.screen(file_id, rich.title("Оплачено"), rich.facts(*rows))


def about(file_id: str | None, apps: list[Download]) -> list[dict]:
    blocks = [
        rich.title(config.brand),
        rich.bullets(
            "Один аккаунт на все устройства",
            "Логин и пароль работают на сайте, в приложении и здесь",
        ),
    ]

    if apps:
        blocks.append(
            rich.table(
                ("Приложение", "Версия"),
                [(PLATFORM_TITLES.get(app.platform, app.platform.title()), app.version) for app in apps],
            )
        )

    # ВРЕМЕННО: кодовое слово для согласования с платёжным провайдером.
    # Убрать после подтверждения.
    blocks.append(rich.facts(("Код проверки", rich.code("verplatega"))))

    return rich.screen(file_id, *blocks)


def support(file_id: str | None) -> list[dict]:
    return rich.screen(
        file_id,
        rich.title("Поддержка"),
        rich.paragraph("Выберите проблему или напишите свою."),
        rich.facts(("Почта поддержки", rich.code(texts.SUPPORT_EMAIL))),
    )


def topic(file_id: str | None, item: SupportTopic) -> list[dict]:
    lines = [line for line in item.answer.split("\n") if line.strip()]

    return rich.screen(
        file_id,
        rich.title(item.title),
        *[rich.paragraph(line) for line in lines],
    )


def history(file_id: str | None, payments: list[Payment]) -> list[dict]:
    if not payments:
        return rich.screen(
            file_id,
            rich.title("Платежи"),
            rich.paragraph("Платежей пока нет."),
        )

    rows = [
        (
            timeutils.human_date(payment.paid_at),
            f"{payment.amount:.0f} {payment.currency}",
        )
        for payment in payments[:10]
    ]

    return rich.screen(file_id, rich.title("Платежи"), rich.table(("Дата", "Сумма"), rows))


def tickets(file_id: str | None, items: list[Ticket]) -> list[dict]:
    if not items:
        return rich.screen(
            file_id,
            rich.title("Обращения"),
            rich.paragraph("Обращений пока нет."),
        )

    blocks = [rich.title("Обращения")]

    for ticket in items:
        status = "отвечено" if ticket.status == "answered" else "в работе"

        blocks.append(
            rich.facts(
                (f"№{ticket.id}", timeutils.human_date(ticket.created_at)),
                ("Статус", status),
            )
        )
        blocks.append(rich.quote(ticket.message.strip()))

        if ticket.answer:
            blocks.append(rich.quote(rich.bold(ticket.answer.strip())))

    return rich.screen(file_id, *blocks)


def _status(account: Account) -> str:
    if not account.active:
        return "Подписка не активна"

    plan = account.plan_title or "Подписка"

    return f"{plan} · {timeutils.plural_days(account.days_left or 0)}"
