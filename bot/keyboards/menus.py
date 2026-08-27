from urllib.parse import quote

from aiogram.types import InlineKeyboardMarkup

from config.settings import SUPPORT_TOPICS, PayMethod, config, payment_methods
from keyboards.ui import DANGER, DEFAULT, SUCCESS, make_btn
from utils.panel import Download, Plan


# Подпись к пересылке ссылки: её увидит тот, кого зовут.
INVITE_PITCH = "Пользуюсь Prosto VPN — заходи, тут дают пробный период"

# Приложения ProstoVPN под iPhone нет: там ставят официальный AmneziaVPN и
# кладут в него наш ключ. Адрес тот же, что на сайте.
APPSTORE_URL = "https://apps.apple.com/app/amneziavpn/id1600529900"

PLATFORM_TITLES = {
    "windows": "Windows",
    "android": "Android",
    "macos": "macOS",
    "ios": "iPhone",
    "linux": "Linux",
}

# Значок платформы. Два одинаковых значка в одном сообщении читаются как
# ошибка вёрстки, поэтому у каждой кнопки списка — свой.
PLATFORM_EMOJI = {
    "windows": "windows",
    "android": "android",
    "macos": "macos",
    "ios": "ios",
    "linux": "linux",
}

# Значки тарифов по кругу: от «на пробу» к «самому выгодному». Список
# длиннее любой витрины, поэтому соседние кнопки не совпадают.
PLAN_EMOJI = ("coffee", "calendar", "season", "gift", "best")

# Темы поддержки — по смыслу вопроса, а не одинаковым значком на все.
TOPIC_EMOJI = {
    "connect": "unlock",
    "speed": "rocket",
    "pay": "wallet",
    "install": "guide",
    "account": "key",
}

# Значок способа оплаты: одинаковых в одном списке быть не должно.
METHOD_EMOJI = {"sbp": "wallet", "stars": "balance", "crypto": "crypto", "card": "calendar"}

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
            # Полный кабинет — тот же, что на сайте, но открывается внутри
            # Telegram и входит сам, без пароля.
            [
                make_btn(
                    "Кабинет на сайте — без пароля",
                    web_app=f"{config.site_url}/account",
                    emoji="link",
                )
            ],
            [make_btn("Тарифы и оплата", callback_data="plans", emoji="wallet", style=SUCCESS)],
            # Приглашения сразу под оплатой: это второй способ получить дни,
            # и человеку он интересен ровно в тот момент, когда он смотрит на цену.
            [make_btn("Пригласить друга", callback_data="friends", emoji="friends")],
            [make_btn("Поддержка", callback_data="support", emoji="support")],
            [make_btn("Наш канал", url=config.channel_url, emoji="channel")],
            # Инструкция сразу под каналом: до неё чаще всего и идут — из
            # канала за новостями, отсюда за установкой.
            [make_btn("Инструкция по установке", url=config.guide_url, emoji="guide")],
            [make_btn("О сервисе", callback_data="about", emoji="rocket")],
            [make_btn("Документы", callback_data="docs", emoji="link")],
            [make_btn("Выйти из аккаунта", callback_data="logout", emoji="cross", style=DANGER)],
        ]
    )


def cabinet_menu(active: bool, ios: bool = False, freeze=None) -> InlineKeyboardMarkup:
    # У человека на паузе подписка есть, просто спит: предлагать ему
    # «оформить» — значит делать вид, что дни сгорели.
    paid = active or bool(freeze is not None and freeze.frozen)

    rows = [
        [
            make_btn(
                "Продлить подписку" if paid else "Оформить подписку",
                callback_data="plans",
                emoji="wallet",
                style=SUCCESS,
            )
        ],
        [
            make_btn("Платежи", callback_data="history", emoji="history"),
            make_btn("Пароль", callback_data="password", emoji="key"),
        ],
        # Перевод дней — тоже про «свои дни», поэтому рядом с платежами.
        # Автопродления здесь нет намеренно: оно живёт в кабинете на сайте,
        # где рядом и способ оплаты, и понятная страница отмены.
        [make_btn("Передать дни другу", callback_data="transfer", emoji="transfer")],
    ]

    # Пауза подписки. Кнопка стоит у всех, а не только у тех, кому пауза
    # доступна: спрятанная возможность — это возможность, о которой не знают.
    # Кому нельзя — тот увидит экран с причиной, а не молчание.
    if freeze is not None:
        rows.append(
            [
                make_btn(
                    "Снять паузу" if freeze.frozen else "Заморозить подписку",
                    callback_data="resume" if freeze.frozen else "freeze",
                    emoji="freeze",
                )
            ]
        )

    if ios:
        # Приложения под iPhone нет: человек подключается ключом из
        # AmneziaVPN, и это для него главная кнопка кабинета.
        rows.append([make_btn("Ключ для iPhone", callback_data="ioskey", emoji="unlock")])

    # Файл нужен тем, кто сидит с iPhone: в наших приложениях список
    # уже внутри. Строка на всю ширину и прямо над поддержкой — сюда и
    # приходят с вопросом «почему не открывается сбербанк».
    rows.append(
        [make_btn("Полный кабинет", web_app=f"{config.site_url}/account", emoji="link")]
    )
    rows.append([make_btn("Российские сервисы напрямую", callback_data="tunnel", emoji="rocket")])
    rows.append([make_btn("Поддержка", callback_data="support", emoji="support")])
    rows.append([make_btn("Меню", callback_data="home", emoji="back", style=DANGER)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def freeze_confirm_menu() -> InlineKeyboardMarkup:
    """Подтверждение паузы. «Назад», а не «Отмена»: у отмены тот же значок."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Да, заморозить", callback_data="freeze:yes", emoji="freeze")],
            [make_btn("Назад", callback_data="cabinet", emoji="back", style=DANGER)],
        ]
    )


def payment_methods_menu() -> InlineKeyboardMarkup:
    """Сначала способ оплаты, тарифы — следующим экраном."""
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
    """Счёт на оплату: одна зелёная кнопка со ссылкой, остальное тихое."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Оплатить", url=url, emoji="wallet", style=SUCCESS)],
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
            [make_btn("Меню", callback_data="home", emoji="back", style=DANGER)],
        ]
    )


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

    # iPhone стоит вне общего ряда: у остальных платформ кнопка ведёт прямо
    # на установщик, а здесь скачивать нечего — нужен экран с тремя шагами.
    rows.append([make_btn("iPhone", callback_data="iphone", emoji="ios")])

    # И сразу под ним — про пустой App Store. На экране iPhone эта кнопка тоже
    # есть, но туда ещё надо зайти, а спотыкается человек раньше: он видит
    # список платформ, идёт ставить приложение и не находит его.
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
    """App Store и путь к ключу. Ключ живёт в кабинете, туда и ведём."""
    rows = [[make_btn("AmneziaVPN в App Store", url=APPSTORE_URL, emoji="ios")]]

    if authorized:
        rows.append([make_btn("Ключ для iPhone", callback_data="ioskey", emoji="unlock")])
    else:
        rows.append([make_btn("Личный кабинет", callback_data="gate", emoji="profile")])

    # Отдельной кнопкой, а не строкой в тексте: у владельцев айфонов с
    # российским Apple ID приложение просто не находится в поиске, и это
    # первое, обо что они спотыкаются. Якорь #appstore открывает нужный
    # раздел инструкции уже развёрнутым.
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
    """
    Экран пригласительной ссылки.

    Регистрация — единственная зелёная кнопка: дни даются только за новый
    аккаунт, и предлагать вход первым значит уводить человека мимо подарка.
    Вход всё равно оставляем: по ссылке приходят и те, кто уже с нами.

    Копирование ссылки здесь же — человек, которому подарок не достался
    (аккаунт у него давно), всё равно может передать её дальше, и это
    единственный экран, где ссылка у него перед глазами.
    """
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
    """
    Экран после начисления подарка.

    «Поделиться» первой и зелёной: человек прямо сейчас получил бесплатные
    дни, и это единственная секунда, когда он готов кому-то об этом сказать.
    Через час он уже подключается и про кнопку не вспомнит.

    Копирование рядом — тем же порядком, что и на экране приглашений: кнопка
    «поделиться» открывает пересылку внутри Telegram, а ссылку кидают и в
    другие места, откуда диалог Telegram недоступен.
    """
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
    """
    Экран подписки: сначала подписаться, потом подтвердить.

    Порядок кнопок и есть инструкция — человек читает сверху вниз и делает
    ровно то, что нужно. «Я подписался» проверяется по-настоящему, поэтому
    нажать её раньше времени безвредно: бот честно ответит, что не видит.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Подписаться на канал", url=config.channel_url, emoji="channel", style=SUCCESS)],
            [make_btn("Я подписался", callback_data="subscribed", emoji="check")],
        ]
    )


# --------------------------------------------------------------------------
# Письма вдогонку
# --------------------------------------------------------------------------
#
# У каждого письма ровно одно нужное действие, и оно стоит первым и цветным.
# Вторая кнопка — не альтернатива, а выход для того, кто пришёл не за этим:
# посмотреть сервис, открыть инструкцию, заглянуть в кабинет.


def nudge_signup_menu() -> InlineKeyboardMarkup:
    """Письмо «вы зашли и не зарегистрировались»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Зарегистрироваться", callback_data="register", emoji="profile", style=SUCCESS)],
            [make_btn("О сервисе", callback_data="about", emoji="rocket")],
        ]
    )


def nudge_idle_menu() -> InlineKeyboardMarkup:
    """Письмо «аккаунт есть, а VPN не включали»: главное здесь — инструкция."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Инструкция", url=config.guide_url, emoji="guide", style=SUCCESS)],
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
        ]
    )


def nudge_renew_menu() -> InlineKeyboardMarkup:
    """Письмо «подписка кончается»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Продлить подписку", callback_data="plans", emoji="wallet", style=SUCCESS)],
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
        ]
    )


def gift_menu() -> InlineKeyboardMarkup:
    """Подарок начислен — дальше только пользоваться."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_btn("Личный кабинет", callback_data="cabinet", emoji="profile")],
            [make_btn("Инструкция", url=config.guide_url, emoji="guide")],
        ]
    )
