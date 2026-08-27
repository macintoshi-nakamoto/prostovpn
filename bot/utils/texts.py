from html import escape

from config.settings import PayMethod, SupportTopic, config
from database.models import Ticket
from keyboards.ui import tg
from utils import timeutils
from utils.panel import (
    Account,
    IosKey,
    PanelError,
    PanelUnavailable,
    Payment,
    Plan,
    TunnelFile,
)


SUPPORT_EMAIL = "support@prostovpn.cc"


def _gb(value: float) -> str:
    if value >= 100:
        return f"{value:.0f} ГБ"

    return f"{value:.1f}".rstrip("0").rstrip(".") + " ГБ"


def traffic_line(account: Account) -> str | None:
    if account.traffic_limit_bytes is None:
        return None

    used = account.traffic_used_bytes / 1024**3
    limit = account.traffic_limit_bytes / 1024**3

    return f"Трафик {_gb(used)} из {_gb(limit)}"


def status_line(account: Account) -> str:
    if not account.active:
        return f'{tg("warn")} Подписка не активна'

    plan = escape(account.plan_title or "Подписка")
    left = timeutils.plural_days(account.days_left or 0)

    return f'{tg("check")} {plan} · {left}'


START_LEAD = "Один аккаунт на все устройства - вход по логину и паролю."

START_POINTS = (
    "Собственный протокол и свои серверы",
    "Скорость до 1 Гбит/с: 4K и загрузки без пауз",
    "Шифрование трафика, логи не храним",
)


def start_text() -> str:
    return f'{tg("brand")} <b>{config.brand}</b>\nПросто быстрый VPN'


def gate_text(login: str | None) -> str:
    known = f"\nАккаунт: <code>{escape(login)}</code>" if login else ""

    return (
        f'{tg("profile")} <b>Личный кабинет</b>{known}\n\n'
        "Логин и пароль те же, что на сайте и в приложении."
    )


def main_text(account: Account) -> str:
    return (
        f'{tg("brand")} <b>{config.brand}</b>\n\n'
        f"{status_line(account)}"
    )


def cabinet_text(account: Account) -> str:
    lines = [
        f'{tg("profile")} <code>{escape(account.login)}</code>',
        "",
        status_line(account),
    ]

    if account.active and account.expires_at:
        lines.append(f"До {timeutils.human_date(account.expires_at)}")

    traffic = traffic_line(account)

    if traffic and account.active:
        lines.append(traffic)

    if account.device_limit and account.active:
        lines.append(f"Устройства {account.devices} из {account.device_limit}")

    return "\n".join(lines)


def tunnel_text(file: TunnelFile | None) -> str:
    if file is None:
        return (
            f'{tg("empty")} <b>Российские сервисы напрямую</b>\n\n'
            "Файл готовится - загляните позже."
        )

    version = f" · {escape(file.version)}" if file.version else ""

    return (
        f'{tg("rocket")} <b>Российские сервисы напрямую</b>{version}\n\n'
        f'{tg("channel")} Файл нужен <b>только на iPhone</b>.\n'
        "В приложении ProstoVPN для Windows, Android и macOS это уже встроено - "
        "там ничего скачивать и вставлять не надо, всё работает само.\n\n"
        "С файлом банки, госуслуги и другие российские сайты открываются как без "
        "VPN, остальное идёт через нас.\n\n"
        "Сохраните файл и откройте его в приложении - оно само предложит добавить "
        "сайты.\n"
        f"Инструкция: {config.guide_url}"
    )


def ios_keys_text(account: Account) -> str:
    if not account.ios_keys:
        return (
            f'{tg("empty")} <b>Ключ для iPhone</b>\n\n'
            "Ключи ещё не готовы либо подписка неактивна.\n"
            "Загляните в кабинет через минуту."
        )

    return (
        f'{tg("key")} <b>Ключ для iPhone</b>\n\n'
        "Своего приложения ProstoVPN для iPhone пока нет - ключ работает в "
        "AmneziaVPN из App Store, в списке он появится под именем prostovpn.cc.\n\n"
        f"Ключей {len(account.ios_keys)}: по одному на устройство, "
        "на два телефона один и тот же ключ не поставить.\n\n"
        f"Инструкция: {account.guide_url or config.guide_url}"
    )


def ios_key_text(key: IosKey) -> str:
    where = f" · {escape(key.server)}" if key.server else ""

    return (
        f"<b>Устройство {key.slot}</b>{where}\n"
        f"<code>{escape(key.vpn_url)}</code>"
    )


def methods_text() -> str:
    return (
        f'{tg("wallet")} <b>Тарифы и оплата</b>\n\n'
        "Выберите способ оплаты - дальше покажу тарифы.\n\n"
        "Оплачивая, вы принимаете условия пользовательского соглашения. "
        "Оно и остальные документы - в разделе «Документы»."
    )


def docs_text() -> str:
    return (
        f'{tg("link")} <b>Документы</b>\n\n'
        "Пользовательское соглашение, политика конфиденциальности, правила "
        "использования и условия возврата. Открываются на сайте.\n\n"
        f"Поддержка: <code>{SUPPORT_EMAIL}</code>"
    )


def plan_terms(plan: Plan) -> str:
    parts = [
        timeutils.plural_days(plan.duration_days),
        f"{plan.traffic_gb} ГБ трафика" if plan.traffic_gb else "безлимитный трафик",
        timeutils.plural_devices(plan.device_limit),
    ]

    if plan.server_limit:
        parts.append(timeutils.plural_countries(plan.server_limit))

    return " · ".join(parts)


def plan_price(plan: Plan, method: PayMethod) -> str:
    return f"{plan.stars} ★" if method.code == "stars" else f"{plan.rub} ₽"


def plans_text(method: PayMethod, plans: list[Plan]) -> str:
    lines = [f'{tg("wallet")} <b>Тарифы</b> · {escape(method.title)}', ""]

    for plan in plans:
        lines.append(f"<b>{escape(plan.title)}</b> - {plan_price(plan, method)}")
        lines.append(escape(plan_terms(plan)))
        lines.append("")

    lines.append("Дни складываются с текущей подпиской.")

    if method.catalog_only:
        lines += [
            "",
            f"Оплата через {escape(method.title)} подключается. "
            "Сейчас доступна оплата звёздами Telegram.",
        ]

    return "\n".join(lines)


def daily_prompt(plan: Plan, method: str | None = None) -> str:
    price = f"{plan.stars}★" if method == "stars" else f"{plan.rub} ₽"

    return (
        f'{tg("coffee")} <b>{escape(plan.title)}</b>\n\n'
        f"{price} за день. Сколько дней берёте?\n"
        "Пришлите число от 1 до 90 — например, 7."
    )


def daily_error() -> str:
    return (
        f'{tg("warn")} <b>Нужно число</b>\n\n'
        "Сколько дней покупаем? Пришлите число от 1 до 90."
    )


def invoice_text(plan: Plan, quantity: int = 1, method: str | None = None) -> str:
    terms = plan_terms(plan) if quantity == 1 else timeutils.plural_days(
        plan.duration_days * quantity
    )

    return (
        f'{tg("wallet")} <b>Счёт на оплату</b>\n\n'
        f"<b>{escape(plan.title)}</b> - {plan.rub * quantity} ₽ · {escape(terms)}\n\n"
        "Нажмите «Оплатить» и завершите платёж на открывшейся странице. "
        + (
            "Переведите точную сумму на указанный адрес.\n\n"
            if method == "crypto"
            else "Ссылка действует 15 минут.\n\n"
        )
        + "Доступ включится сам, подтверждение придёт сюда."
    )


def transfer_text(account: Account, history: list) -> str:
    lines = [
        f'{tg("transfer")} <b>Передать дни</b>',
        "",
        f"У вас есть {timeutils.plural_days(account.days_left or 0)}.",
        "",
        "Напишите логин или ID друга — дальше спрошу, сколько дней передать.",
        "Дни уйдут сразу, вернуть их сможет только он.",
    ]

    if history:
        lines.append("")
        for row in history[:5]:
            mark = "Отдано" if row.direction == "sent" else "Получено"
            lines.append(f"{mark}: {row.days} дн. · {escape(row.counterpart)}")

    return "\n".join(lines)


def transfer_who_error() -> str:
    return (
        f'{tg("warn")} <b>Не понял, кому</b>\n\n'
        "Пришлите логин друга или его ID вида <code>PV-XXXX-XXXX</code>."
    )


def transfer_days_prompt(recipient: str) -> str:
    return (
        f'{tg("transfer")} <b>Сколько дней передать</b>\n\n'
        f"Получатель: <code>{escape(recipient)}</code>\n\n"
        "Пришлите число — например, 7."
    )


def transfer_days_error() -> str:
    return (
        f'{tg("warn")} <b>Нужно число</b>\n\n'
        "Сколько дней передать? Пришлите число, например 3."
    )


def transfer_failed(error: PanelError) -> str:
    return f'{tg("warn")} <b>Не передали</b>\n\n{escape(str(error))}'


def transfer_done(record) -> str:
    return (
        f'{tg("check")} <b>Готово</b>\n\n'
        f"{timeutils.plural_days(record.days)} ушли аккаунту "
        f"<code>{escape(record.counterpart)}</code>."
    )


def paid_text(plan: Plan, account: Account | None) -> str:
    until = (
        f"\nДо {timeutils.human_date(account.expires_at)}"
        if account and account.expires_at
        else ""
    )

    return (
        f'{tg("check")} <b>Оплачено</b>\n\n'
        f"{escape(plan.title)} · +{timeutils.plural_days(plan.duration_days)}{until}"
    )


def about_text() -> str:
    return (
        f'{tg("brand")} <b>{config.brand}</b>\n\n'
        "Один аккаунт на все устройства.\n"
        "Логин и пароль работают на сайте, в приложении и здесь."
    )


def friends_text(stats, invite_url: str) -> str:
    waiting = (
        "\nДни начислим, как только вы войдёте в аккаунт в этом боте."
        if stats.pending
        else ""
    )

    return (
        f'{tg("friends")} <b>Друзья</b>\n\n'
        f"Приглашено: <b>{stats.invited}</b>\n"
        f"Из них оплатили: <b>{stats.purchased}</b>\n"
        f"Подарено дней: <b>{stats.days}</b>\n\n"
        f'{tg("gift")} +{stats.join_days} дн. за друга по вашей ссылке '
        f"и ещё +{stats.purchase_days} дн., когда он оплатит подписку.\n\n"
        f"<code>{escape(invite_url)}</code>{waiting}"
    )


def support_text() -> str:
    return (
        f'{tg("support")} <b>Поддержка</b>\n\n'
        "Выберите проблему или напишите свою.\n\n"
        f"Почта поддержки: <code>{SUPPORT_EMAIL}</code>"
    )


def topic_text(topic: SupportTopic) -> str:
    return (
        f'{tg("support")} <b>{escape(topic.title)}</b>\n\n'
        f"{escape(topic.answer)}"
    )


def ticket_prompt_text(topic: SupportTopic | None) -> str:
    subject = escape(topic.title) if topic else "Свой вопрос"

    return (
        f'{tg("channel")} <b>{subject}</b>\n\n'
        "Опишите проблему одним сообщением."
    )


def ticket_created_text(ticket_id: int) -> str:
    return (
        f'{tg("check")} <b>Обращение №{ticket_id}</b>\n\n'
        "Ответим здесь же."
    )


def tickets_text(tickets: list[Ticket]) -> str:
    if not tickets:
        return f'{tg("empty")} <b>Обращений нет</b>'

    lines = [f'{tg("history")} <b>Обращения</b>', ""]

    for ticket in tickets:
        status = "Отвечено" if ticket.status == "answered" else "В работе"
        lines.append(
            f"<b>№{ticket.id}</b> · {timeutils.human_date(ticket.created_at)} · {status}"
        )
        lines.append(f"<i>{escape(_short(ticket.message))}</i>")

        if ticket.answer:
            lines.append(f'{tg("check")} {escape(_short(ticket.answer))}')

        lines.append("")

    return "\n".join(lines).strip()


def history_text(payments: list[Payment]) -> str:
    if not payments:
        return f'{tg("empty")} <b>Платежей нет</b>'

    lines = [f'{tg("history")} <b>Платежи</b>', ""]

    for payment in payments[:10]:
        lines.append(
            f"{timeutils.human_date(payment.paid_at)} - "
            f"<b>{payment.amount:.0f} {escape(payment.currency)}</b>"
        )

    return "\n".join(lines)


def _short(value: str, limit: int = 80) -> str:
    value = value.strip().replace("\n", " ")

    return value if len(value) <= limit else value[: limit - 3] + "..."


def panel_error(error: PanelError) -> str:
    if isinstance(error, PanelUnavailable):
        return "Сервис недоступен, попробуйте через минуту."

    if error.status == 429:
        return "Слишком много попыток. Попробуйте позже."

    if error.code == "bad_credentials" or error.status == 401:
        return "Неверный логин или пароль."

    if error.code == "login_taken":
        return "Такой логин уже занят."

    return str(error) or "Что-то пошло не так."


def promo_text(days: int) -> str:
    return (
        f'{tg("gift")} <b>{timeutils.plural_days(days)} бесплатно</b>\n\n'
        "Вы перешли по пригласительной ссылке.\n"
        f"Заведите аккаунт — и {timeutils.plural_days(days)} доступа "
        "начислим сразу, без карты и без оплаты.\n\n"
        f"{tg('star')} Друг по этой же ссылке получит столько же."
    )


def promo_granted_text(days: int) -> str:
    return (
        f'{tg("gift")} <b>Поздравляем!</b>\n\n'
        f"Вам начислено <b>{timeutils.plural_days(days)}</b> бесплатного доступа.\n"
        "Ничего оплачивать не нужно — доступ уже работает.\n\n"
        f"{tg('friends')} <b>Скорее делитесь с другом</b> — по вашей ссылке "
        "он получит столько же, а вам это ничего не стоит."
    )


def promo_used_text() -> str:
    return (
        f'{tg("check")} <b>Подарок уже получен</b>\n\n'
        "Эта ссылка даёт бесплатные дни один раз и только новому аккаунту."
    )


def promo_expired_text() -> str:
    return (
        f'{tg("empty")} <b>Ссылка больше не действует</b>\n\n'
        "Срок этого приглашения истёк. Пробный период у нас есть и без него — "
        "заведите аккаунт и посмотрите."
    )


def iphone_text() -> str:
    return (
        f'{tg("ios")} <b>iPhone</b>\n\n'
        "Своего приложения для iPhone у нас пока нет — и это не мешает.\n\n"
        "1. Поставьте <b>AmneziaVPN</b> из App Store.\n"
        "2. Возьмите ключ в кабинете: «Ключ для iPhone».\n"
        "3. Откройте ключ — профиль добавится сам, в списке он будет "
        "называться prostovpn.cc.\n\n"
        "Ключ выдаётся свой на каждое устройство: на два телефона один и "
        "тот же не поставить.\n\n"
        "Если AmneziaVPN не находится в App Store — так и должно быть с "
        "российским Apple ID. Это обходится за пару минут, инструкция по "
        "кнопке ниже."
    )


def subscribe_text(days: int | None = None) -> str:
    if days:
        return (
            f'{tg("gift")} <b>Ваши {timeutils.plural_days(days)} ждут</b>\n\n'
            "Остался один шаг: подпишитесь на наш канал и нажмите "
            "«Я подписался» — подарок сразу станет вашим.\n\n"
            "В канале мы пишем, что делать, когда провайдер начинает резать: "
            "запасные порты, обходные файлы, новые страны."
        )

    return (
        f'{tg("channel")} <b>Подпишитесь на канал</b>\n\n'
        "Там мы пишем, что делать, когда провайдер начинает резать: запасные "
        "порты, обходные файлы, новые страны. Это единственное место, где "
        "об этом узнают вовремя.\n\n"
        "Подпишитесь и нажмите «Я подписался» — и вернёмся к делу."
    )


def subscribe_missing_text() -> str:
    return "Подписки пока не видно. Подпишитесь на канал и нажмите кнопку ещё раз."
