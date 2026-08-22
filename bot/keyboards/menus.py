from urllib.parse import quote

from aiogram.types import InlineKeyboardMarkup

from config.settings import SUPPORT_TOPICS, PayMethod, config, payment_methods
from keyboards.ui import DANGER, DEFAULT, SUCCESS, make_btn
from utils.panel import Download, Plan


# Подпись к пересылке ссылки: её увидит тот, кого зовут.
INVITE_PITCH = "Пользуюсь Prosto VPN — заходи, тут дают пробный период"

PLATFORM_TITLES = {
    "windows": "Windows",
    "android": "Android",
    "macos": "macOS",
    "ios": "iPhone",
    "linux": "Linux",
}

# Правовые документы. Платёжный провайдер требует, чтобы оферта, политика и
# правила возврата были доступны там же, где идёт оплата. Ведут на сайт: это
# провайдером допускается, а дублировать текст в боте — заводить вторую
# редакцию, которая разойдётся с первой. Только кнопками: Rich Message ссылок
# внутри текста не поддерживает.
LEGAL_DOCS = (
    ("Пользовательское соглашение", "/terms"),
    ("Политика конфиденциальности", "/privacy"),
    ("Правила использования", "/aup"),
    ("Возврат средств", "/refund"),
)


def start_menu() -> InlineKeyboardMarkup:
    """Первый экран: личный кабинет выше всего остального."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Личный кабинет", callback_data="gate", emoji="profile")],
            [make_btn("О сервисе", callback_data="about", emoji="rocket")],
            [make_btn("Документы", callback_data="docs", emoji="link")],
        ]
    )


def gate_menu(known: bool) -> InlineKeyboardMarkup:
    row = [make_btn("Войти", callback_data="login", emoji="key")]

    if not known:
        row.insert(0, make_btn("Регистрация", callback_data="register", emoji="profile"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [make_btn("Назад", callback_data="start", emoji="back", style=DANGER)],
        ]
    )


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
            [make_btn("Тарифы и оплата", callback_data="plans", emoji="wallet", style=SUCCESS)],
            # Приглашения сразу под оплатой: это второй способ получить дни,
            # и человеку он интересен ровно в тот момент, когда он смотрит на цену.
            [make_btn("Пригласить друга", callback_data="friends", emoji="friends")],
            [make_btn("Поддержка", callback_data="support", emoji="support")],
            [make_btn("Наш канал", url=config.channel_url, emoji="channel")],
            # Инструкция сразу под каналом: до неё чаще всего и идут — из
            # канала за новостями, отсюда за установкой.
            [make_btn("Инструкция по установке", url=config.guide_url, emoji="rocket")],
            [make_btn("О сервисе", callback_data="about", emoji="rocket")],
            [make_btn("Документы", callback_data="docs", emoji="link")],
            [make_btn("Выйти из аккаунта", callback_data="logout", emoji="cross", style=DANGER)],
        ]
    )


def cabinet_menu(active: bool, ios: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            make_btn(
                "Продлить подписку" if active else "Оформить подписку",
                callback_data="plans",
                emoji="wallet",
                style=SUCCESS,
            )
        ],
        [
            make_btn("Платежи", callback_data="history", emoji="history"),
            make_btn("Пароль", callback_data="password", emoji="key"),
        ],
        # Рядом с платежами: автопродление - тоже про деньги.
        [make_btn("Автопродление", callback_data="autorenew", emoji="calendar")],
    ]

    if ios:
        # Приложения под iPhone нет: человек подключается ключом из
        # AmneziaVPN, и это для него главная кнопка кабинета.
        rows.append([make_btn("Ключ для iPhone", callback_data="ioskey", emoji="key")])

    # Файл нужен тем, кто сидит с iPhone: в наших приложениях список
    # уже внутри. Строка на всю ширину и прямо над поддержкой — сюда и
    # приходят с вопросом «почему не открывается сбербанк».
    rows.append([make_btn("Российские сервисы напрямую", callback_data="tunnel", emoji="rocket")])
    rows.append([make_btn("Поддержка", callback_data="support", emoji="support")])
    rows.append([make_btn("Меню", callback_data="home", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_menu() -> InlineKeyboardMarkup:
    """Сначала способ оплаты, тарифы — следующим экраном."""
    rows = [
        [
            make_btn(
                method.title if method.shows_catalog else f"{method.title} · скоро",
                callback_data=f"method:{method.code}",
                emoji="balance" if method.code == "stars" else "wallet",
                style=SUCCESS if method.ready else DEFAULT,
            )
        ]
        for method in payment_methods()
    ]

    # Документы прямо на экране оплаты: требование платёжного провайдера —
    # человек должен дойти до оферты, не покидая оплату.
    rows.append([make_btn("Документы", callback_data="docs", emoji="link")])
    rows.append([make_btn("Назад", callback_data="home", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_menu(plans: list[Plan], method: PayMethod) -> InlineKeyboardMarkup:
    rows = [
        [
            make_btn(
                f"{plan.title} · {price(plan, method)}",
                callback_data=f"buy:{method.code}:{plan.code}",
                emoji="calendar",
            )
        ]
        for plan in plans
    ]

    rows.append([make_btn("Назад", callback_data="plans", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def price(plan: Plan, method: PayMethod) -> str:
    return f"{plan.stars} ★" if method.code == "stars" else f"{plan.rub} ₽"


def pay_link_menu(url: str) -> InlineKeyboardMarkup:
    """Счёт на оплату: одна зелёная кнопка со ссылкой, остальное тихое."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Оплатить", url=url, emoji="wallet", style=SUCCESS)],
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
            [make_btn("Меню", callback_data="home", emoji="back", style=DANGER)],
        ]
    )


def autorenew_menu(rec, options: list[Plan]) -> InlineKeyboardMarkup:
    """
    Автопродление. Кнопки зависят от состояния: не подключено - выбор
    тарифа, ждёт привязки - ссылка и отмена, работает - только отключение.
    Отключение намеренно серое и одно: случайно не нажмёшь.
    """
    rows: list[list] = []

    if rec is None or not rec.live:
        rows = [
            [
                make_btn(
                    f"{plan.title} · {plan.rub} ₽ {'в год' if plan.duration_days >= 365 else 'в месяц'}",
                    callback_data=f"rec:on:{plan.code}",
                    emoji="calendar",
                )
            ]
            for plan in options
        ]
    elif rec.status == "pending":
        if rec.redirect_url:
            rows.append([make_btn("Привязать счёт", url=rec.redirect_url, emoji="wallet")])

        rows.append([make_btn("Отменить оформление", callback_data="rec:off", emoji="cross")])
    else:
        rows.append([make_btn("Отключить автопродление", callback_data="rec:off", emoji="cross")])

    rows.append([make_btn("Назад", callback_data="cabinet", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def friends_menu(invite_url: str) -> InlineKeyboardMarkup:
    """
    Экран приглашений: поделиться, скопировать, вернуться.

    Кнопка «Поделиться» — не ссылка на бота, а готовый диалог пересылки:
    Telegram сам предложит выбрать, кому отправить. Копирование рядом —
    для тех, кто кидает ссылку не в Telegram.
    """
    share = f"https://t.me/share/url?url={quote(invite_url, safe='')}&text={quote(INVITE_PITCH, safe='')}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Поделиться ссылкой", url=share, emoji="friends", style=SUCCESS)],
            [make_btn("Скопировать ссылку", copy_text=invite_url, emoji="link")],
            [make_btn("Меню", callback_data="home", emoji="back", style=DANGER)],
        ]
    )


def support_menu() -> InlineKeyboardMarkup:
    rows = [
        [make_btn(topic.title, callback_data=f"faq:{topic.code}", emoji="support")]
        for topic in SUPPORT_TOPICS
    ]

    rows.append(
        [make_btn("Написать свою проблему", callback_data="ticket:other", emoji="channel")]
    )

    rows.append(
        [
            make_btn("Обращения", callback_data="tickets", emoji="history"),
            make_btn("Меню", callback_data="home", emoji="back", style=DANGER),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def topic_menu(topic_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Не помогло", callback_data=f"ticket:{topic_code}", emoji="channel")],
            [make_btn("Назад", callback_data="support", emoji="back", style=DANGER)],
        ]
    )


def about_menu(authorized: bool, apps: list[Download]) -> InlineKeyboardMarkup:
    rows = []
    row = []

    for app in apps:
        row.append(
            make_btn(
                PLATFORM_TITLES.get(app.platform, app.platform.title()),
                url=app.url,
                emoji="rocket",
            )
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([make_btn("Документы", callback_data="docs", emoji="link")])
    rows.append([make_btn("Сайт", url=config.site_url, emoji="link")])
    rows.append(
        [
            make_btn(
                "Назад",
                callback_data="home" if authorized else "start",
                emoji="back",
                style=DANGER,
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def docs_menu(authorized: bool) -> InlineKeyboardMarkup:
    rows = [
        [make_btn(title, url=f"{config.site_url}{path}", emoji="link")]
        for title, path in LEGAL_DOCS
    ]

    rows.append(
        [
            make_btn(
                "Назад",
                callback_data="home" if authorized else "start",
                emoji="back",
                style=DANGER,
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu(target: str = "home", title: str = "Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[make_btn(title, callback_data=target, emoji="back", style=DANGER)]]
    )


def cancel_menu(target: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[make_btn("Отмена", callback_data=target, emoji="cross", style=DANGER)]]
    )


def ticket_created_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Обращения", callback_data="tickets", emoji="history")],
            [make_btn("Меню", callback_data="home", emoji="back", style=DANGER)],
        ]
    )


def after_payment_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
            [make_btn("Меню", callback_data="home", emoji="back", style=DANGER)],
        ]
    )
