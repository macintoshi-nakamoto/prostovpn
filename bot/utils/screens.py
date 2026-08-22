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
        rich.title(config.brand, "brand"),
        rich.paragraph(rich.bold(texts.START_LEAD)),
        rich.bullets(*texts.START_POINTS),
    )


def gate(file_id: str | None, login: str | None) -> list[dict]:
    blocks = [
        rich.title("Личный кабинет", "profile"),
        rich.paragraph("Логин и пароль те же, что на сайте и в приложении."),
    ]

    if login:
        blocks.append(rich.facts(("Прошлый вход", rich.code(login))))

    return rich.screen(file_id, *blocks)


def main(file_id: str | None, account: Account) -> list[dict]:
    # Значок перед статусом читается раньше строки: зелёная галка — всё
    # хорошо, «ой» — подписки нет и нужно что-то сделать.
    mark = "check" if account.active else "warn"

    return rich.screen(
        file_id,
        rich.title(config.brand, "brand"),
        rich.paragraph([rich.emoji(mark), rich.bold(f"  {_status(account)}")]),
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

        return rich.screen(file_id, rich.title("Личный кабинет", "profile"), rich.facts(*rows))

    return rich.screen(
        file_id,
        rich.title("Личный кабинет", "profile"),
        rich.facts(*rows),
        rich.paragraph([rich.emoji("warn"), rich.bold("  Подписка не активна")]),
        rich.paragraph("Выберите тариф - доступ включится сразу после оплаты."),
    )


def methods(file_id: str | None) -> list[dict]:
    return rich.screen(
        file_id,
        rich.title("Тарифы и оплата", "wallet"),
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
        rich.title("Документы", "link"),
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
    blocks = [rich.title(f"Тарифы · {method.title}", "calendar")]

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


def invoice(file_id: str | None, plan: Plan) -> list[dict]:
    """Счёт на оплату по ссылке. Кнопка «Оплатить» - в клавиатуре под экраном."""
    return rich.screen(
        file_id,
        rich.title("Счёт на оплату", "wallet"),
        rich.facts(
            ("Тариф", plan.title),
            ("Сумма", f"{plan.rub} ₽"),
            ("Срок", timeutils.plural_days(plan.duration_days)),
        ),
        rich.paragraph(
            "Нажмите «Оплатить» и завершите платёж на открывшейся странице. "
            "Ссылка действует 15 минут."
        ),
        rich.paragraph(rich.italic("Доступ включится сам, подтверждение придёт сюда.")),
    )


def autorenew(file_id: str | None, rec, options: list[Plan]) -> list[dict]:
    """Автопродление: своё состояние - свой экран, кнопки в menus.autorenew_menu."""
    if rec is None or not rec.live:
        blocks = [
            rich.title("Автопродление", "calendar"),
            rich.paragraph(
                "Подключите автосписание - доступ будет продлеваться сам, "
                "без напоминаний. Отключается в один клик."
            ),
        ]

        for plan in options:
            word = "в год" if plan.duration_days >= 365 else "в месяц"
            blocks.append(rich.paragraph(rich.bold(f"{plan.title} - {plan.rub} ₽ {word}")))

        return rich.screen(file_id, *blocks)

    title = rec.plan_title or rec.plan_code or "Подписка"

    if rec.status == "pending":
        return rich.screen(
            file_id,
            rich.title("Автопродление", "calendar"),
            rich.facts(("Тариф", title), ("Сумма", f"{rec.rub} ₽ {rec.interval_label}")),
            rich.paragraph(
                "Осталось привязать счёт: нажмите «Привязать счёт» и подтвердите "
                "на странице оплаты."
            ),
            rich.paragraph(rich.italic("Денег на этом шаге не списывается.")),
        )

    if rec.status == "past_due":
        return rich.screen(
            file_id,
            rich.title("Автопродление", "calendar"),
            rich.paragraph(rich.bold("Последнее списание не прошло.")),
            rich.paragraph(
                "Продлите подписку вручную в «Тарифы и оплата» - или отключите "
                "автопродление."
            ),
        )

    rows: list[tuple[str, object]] = [
        ("Статус", "работает"),
        ("Тариф", title),
        ("Сумма", f"{rec.rub} ₽ {rec.interval_label}"),
    ]

    if rec.next_charge_at:
        rows.append(("Следующее списание", timeutils.human_date(rec.next_charge_at)))

    return rich.screen(
        file_id,
        rich.title("Автопродление", "calendar"),
        rich.facts(*rows),
        rich.paragraph(rich.italic("Каждое продление подтверждаем сообщением сюда.")),
    )


def paid(file_id: str | None, plan: Plan, account: Account | None) -> list[dict]:
    rows: list[tuple[str, object]] = [
        ("Тариф", plan.title),
        ("Добавлено", timeutils.plural_days(plan.duration_days)),
    ]

    if account and account.expires_at:
        rows.append(("Действует до", timeutils.human_date(account.expires_at)))

    return rich.screen(file_id, rich.title("Оплачено", "check"), rich.facts(*rows))


def about(file_id: str | None, apps: list[Download]) -> list[dict]:
    blocks = [
        rich.title(config.brand, "brand"),
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

    return rich.screen(file_id, *blocks)


def friends(file_id: str | None, stats, invite_url: str) -> list[dict]:
    """
    Экран приглашений: сколько дней уже подарено и за что дарят дальше.

    Числа сверху, правила снизу: пришедшему сюда во второй раз интересно
    «сколько мне капнуло», а не «как это работает».
    """
    rows: list[tuple[str, object]] = [
        ("Приглашено", str(stats.invited)),
        ("Из них оплатили", str(stats.purchased)),
        ("Подарено дней", str(stats.days)),
    ]

    blocks = [
        rich.title("Друзья", "friends"),
        rich.facts(*rows),
        rich.paragraph(
            [
                rich.emoji("gift"),
                rich.bold(f"  +{stats.join_days} дн."),
                f" за друга, который перешёл по вашей ссылке, и ещё +{stats.purchase_days} дн., "
                "когда он оплатит подписку.",
            ]
        ),
        rich.paragraph(rich.code(invite_url)),
    ]

    if stats.pending:
        # Человек ещё не входил в аккаунт — дни ждут его, а не потерялись.
        blocks.append(
            rich.paragraph(
                rich.italic("Дни начислим, как только вы войдёте в аккаунт в этом боте.")
            )
        )

    return rich.screen(file_id, *blocks)


def support(file_id: str | None) -> list[dict]:
    return rich.screen(
        file_id,
        rich.title("Поддержка", "support"),
        rich.paragraph("Выберите проблему или напишите свою."),
        rich.facts(("Почта поддержки", rich.code(texts.SUPPORT_EMAIL))),
    )


def topic(file_id: str | None, item: SupportTopic) -> list[dict]:
    lines = [line for line in item.answer.split("\n") if line.strip()]

    return rich.screen(
        file_id,
        rich.title(item.title, "support"),
        *[rich.paragraph(line) for line in lines],
    )


def history(file_id: str | None, payments: list[Payment]) -> list[dict]:
    if not payments:
        return rich.screen(
            file_id,
            rich.title("Платежи", "history"),
            rich.paragraph("Платежей пока нет."),
        )

    rows = [
        (
            timeutils.human_date(payment.paid_at),
            f"{payment.amount:.0f} {payment.currency}",
        )
        for payment in payments[:10]
    ]

    return rich.screen(file_id, rich.title("Платежи", "history"), rich.table(("Дата", "Сумма"), rows))


def tickets(file_id: str | None, items: list[Ticket]) -> list[dict]:
    if not items:
        return rich.screen(
            file_id,
            rich.title("Обращения", "support"),
            rich.paragraph("Обращений пока нет."),
        )

    blocks = [rich.title("Обращения", "support")]

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
