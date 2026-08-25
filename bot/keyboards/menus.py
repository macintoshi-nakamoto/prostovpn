from urllib.parse import quote

from aiogram.types import InlineKeyboardMarkup

from config.settings import SUPPORT_TOPICS, PayMethod, config, payment_methods
from keyboards.ui import DANGER, DEFAULT, SUCCESS, make_btn
from utils.panel import Download, Plan


INVITE_PITCH = "Пользуюсь Prosto VPN — заходи, тут дают пробный период"

APPSTORE_URL = "https://apps.apple.com/app/amneziavpn/id1600529900"

PLATFORM_TITLES = {
    "windows": "Windows",
    "android": "Android",
    "macos": "macOS",
    "ios": "iPhone",
    "linux": "Linux",
}

PLATFORM_EMOJI = {
    "windows": "windows",
    "android": "android",
    "macos": "macos",
    "ios": "ios",
    "linux": "linux",
}

PLAN_EMOJI = ("coffee", "calendar", "season", "gift", "best")

TOPIC_EMOJI = {
    "connect": "unlock",
    "speed": "rocket",
    "pay": "wallet",
    "install": "guide",
    "account": "key",
}

METHOD_EMOJI = {"sbp": "wallet", "stars": "balance", "crypto": "crypto", "card": "calendar"}

LEGAL_DOCS = (
    ("Пользовательское соглашение", "/terms"),
    ("Политика конфиденциальности", "/privacy"),
    ("Правила использования", "/aup"),
    ("Возврат средств", "/refund"),
)


def start_menu() -> InlineKeyboardMarkup:
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
            [make_btn("Пригласить друга", callback_data="friends", emoji="friends")],
            [make_btn("Поддержка", callback_data="support", emoji="support")],
            [make_btn("Наш канал", url=config.channel_url, emoji="channel")],
            [make_btn("Инструкция по установке", url=config.guide_url, emoji="guide")],
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
        [make_btn("Передать дни другу", callback_data="transfer", emoji="transfer")],
    ]

    if ios:
        rows.append([make_btn("Ключ для iPhone", callback_data="ioskey", emoji="unlock")])

    rows.append([make_btn("Российские сервисы напрямую", callback_data="tunnel", emoji="rocket")])
    rows.append([make_btn("Поддержка", callback_data="support", emoji="support")])
    rows.append([make_btn("Меню", callback_data="home", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            make_btn(
                method.title if method.shows_catalog else f"{method.title} · скоро",
                callback_data=f"method:{method.code}",
                emoji=METHOD_EMOJI.get(method.code, "wallet"),
                style=SUCCESS if method.ready else DEFAULT,
            )
        ]
        for method in payment_methods()
    ]

    rows.append([make_btn("Документы", callback_data="docs", emoji="link")])
    rows.append([make_btn("Назад", callback_data="home", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_menu(plans: list[Plan], method: PayMethod) -> InlineKeyboardMarkup:
    rows = [
        [
            make_btn(
                f"{plan.title} · {price(plan, method)}",
                callback_data=f"buy:{method.code}:{plan.code}",
                emoji=PLAN_EMOJI[index % len(PLAN_EMOJI)],
            )
        ]
        for index, plan in enumerate(plans)
    ]

    rows.append([make_btn("Назад", callback_data="plans", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def price(plan: Plan, method: PayMethod) -> str:
    return f"{plan.stars} ★" if method.code == "stars" else f"{plan.rub} ₽"


def pay_link_menu(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Оплатить", url=url, emoji="wallet", style=SUCCESS)],
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
            [make_btn("Меню", callback_data="home", emoji="back", style=DANGER)],
        ]
    )


def friends_menu(invite_url: str) -> InlineKeyboardMarkup:
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
        [
            make_btn(
                topic.title,
                callback_data=f"faq:{topic.code}",
                emoji=TOPIC_EMOJI.get(topic.code, "support"),
            )
        ]
        for topic in SUPPORT_TOPICS
    ]

    rows.append([make_btn("Написать свою проблему", callback_data="ticket:other", emoji="ask")])

    rows.append(
        [
            make_btn("Обращения", callback_data="tickets", emoji="ticket"),
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
                emoji=PLATFORM_EMOJI.get(app.platform, "rocket"),
            )
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([make_btn("iPhone", callback_data="iphone", emoji="ios")])

    rows.append(
        [
            make_btn(
                "Нет приложения в App Store?",
                url=f"{config.site_url}/guide#appstore",
                emoji="warn",
            )
        ]
    )

    rows.append([make_btn("Документы", callback_data="docs", emoji="link")])
    rows.append([make_btn("Сайт", url=config.site_url, emoji="brand")])
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


def iphone_menu(authorized: bool) -> InlineKeyboardMarkup:
    rows = [[make_btn("AmneziaVPN в App Store", url=APPSTORE_URL, emoji="ios")]]

    if authorized:
        rows.append([make_btn("Ключ для iPhone", callback_data="ioskey", emoji="unlock")])
    else:
        rows.append([make_btn("Личный кабинет", callback_data="gate", emoji="profile")])

    rows.append(
        [
            make_btn(
                "Нет приложения в App Store?",
                url=f"{config.site_url}/guide#appstore",
                emoji="warn",
            )
        ]
    )
    rows.append([make_btn("Инструкция", url=config.guide_url, emoji="guide")])
    rows.append([make_btn("Назад", callback_data="about", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_menu(invite_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Создать аккаунт", callback_data="register", emoji="profile", style=SUCCESS)],
            [make_btn("Скопировать ссылку", copy_text=invite_url, emoji="link")],
            [
                make_btn("Войти", callback_data="login", emoji="key"),
                make_btn("О сервисе", callback_data="about", emoji="rocket"),
            ],
        ]
    )


def promo_granted_menu(share_url: str, invite_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Поделиться с другом", url=share_url, emoji="friends", style=SUCCESS)],
            [make_btn("Скопировать ссылку", copy_text=invite_url, emoji="link")],
            [
                make_btn("Личный кабинет", callback_data="cabinet", emoji="profile"),
                make_btn("Инструкция", url=config.guide_url, emoji="guide"),
            ],
        ]
    )


def subscribe_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Подписаться на канал", url=config.channel_url, emoji="channel", style=SUCCESS)],
            [make_btn("Я подписался", callback_data="subscribed", emoji="check")],
        ]
    )
