"""Тексты экранов. Коротко: одна мысль - одна строка."""

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


# Ящик поддержки. Тот же, что в футере сайта (web/src/lib/contacts.js) — платёжный
# провайдер требует видимый контакт техподдержки, и расходиться этим адресам нельзя.
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
    if account.freeze.frozen:
        left = timeutils.plural_days(account.freeze.days_left or account.days_left or 0)
        return f'{tg("freeze")} На паузе · в запасе {left}'

    if not account.active:
        return f'{tg("warn")} Подписка не активна'

    plan = escape(account.plan_title or "Подписка")
    left = timeutils.plural_days(account.days_left or 0)

    return f'{tg("check")} {plan} · {left}'


# --------------------------------------------------------------------------
# Экраны
# --------------------------------------------------------------------------


# Стартовый экран собирается блоками — см. utils/rich.py
#
# Формулировки согласованы с платёжным провайдером: банк на верификации
# отклоняет даже косвенные обещания «без ограничений скорости» и «работает
# там, где другие нет». Пишем только проверяемые факты — цифру скорости,
# шифрование, отсутствие логов.
START_LEAD = "Один аккаунт на все устройства - вход по логину и паролю."

START_POINTS = (
    "Собственный протокол и свои серверы",
    "Скорость до 1 Гбит/с: 4K и загрузки без пауз",
    "Шифрование трафика, логи не храним",
)


def start_text() -> str:
    return (
        "Привет! <b>Prosto</b> - ваш инструмент для цифровой свободы:\n\n"
        f'{tg("key")} VPN нового уровня: быстрый, надежный и безопасный '
        "доступ без ограничений."
    )


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

    if account.freeze.frozen:
        if account.freeze.frozen_days:
            lines.append(f"На паузе {timeutils.plural_days(account.freeze.frozen_days)}")

        lines.append("Дни не тратятся — снимите паузу, и доступ вернётся")
    elif account.active and account.expires_at:
        lines.append(f"До {timeutils.human_date(account.expires_at)}")

    traffic = traffic_line(account)

    if traffic and account.active:
        lines.append(traffic)

    if account.device_limit and account.active:
        lines.append(f"Устройства {account.devices} из {account.device_limit}")

    return "\n".join(lines)


def tunnel_text(file: TunnelFile | None) -> str:
    """
    Экран файла со списком российских сервисов.

    Первым делом - кому он вообще нужен. В приложениях ProstoVPN список уже
    внутри, и без этой строки файл скачивают все подряд, а потом спрашивают
    в поддержке, куда его девать.
    """
    if file is None:
        return (
            f'{tg("empty")} <b>Российские сервисы напрямую</b>\n\n'
            "Файл готовится - загляните позже."
        )

    version = f" · {escape(file.version)}" if file.version else ""

    return (
        f'{tg("rocket")} <b>Российские сервисы напрямую</b>{version}\n\n'
        # Восклицательный знак, а не «грустная» иконка предупреждения: это
        # важная строка, но ничего плохого не случилось.
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
    """Заголовок перед ключами. Сами ключи уходят отдельными сообщениями."""
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


def appstore_text() -> str:
    """Как сменить регион App Store: без него AmneziaVPN и Happ не поставить."""
    return (
        f'{tg("ios")} <b>Регион App Store</b>\n\n'
        "AmneziaVPN, Happ и другие VPN-приложения недоступны в российском "
        "App Store. Регион меняется за пару минут, Apple ID остаётся тот же.\n\n"
        "1. «Настройки» → ваше имя → «Медиаматериалы и покупки» → "
        "«Просмотреть учётную запись».\n"
        "2. «Страна/регион» → «Изменить страну или регион» → например, "
        "Казахстан, Турция или США.\n"
        "3. Примите условия. Способ оплаты — «Нет»; адрес и индекс — любые "
        "из этой страны, телефон — свой.\n"
        "4. Вернитесь в App Store и установите AmneziaVPN или Happ. Регион "
        "можно вернуть тем же путём — приложения останутся.\n\n"
        "Если на аккаунте есть остаток баланса, подписка или семейный доступ, "
        "Apple не даст сменить регион — тогда проще завести отдельный Apple ID "
        "на другую страну и войти им только в App Store."
    )


def devices_text(account: Account) -> str:
    """Список устройств с местом в лимите. Удаление — кнопками под текстом."""
    head = (
        f'{tg("profile")} <b>Устройства</b>\n\n'
        f"Занято {account.devices} из {account.device_limit}. "
        "Удалённое устройство отключается от VPN: ключ снимается с серверов, "
        "вход в приложение закрывается.\n"
    )
    if not account.device_rows:
        return head + "\nПока ни одного устройства."

    lines = []
    for index, device in enumerate(account.device_rows, start=1):
        state = "в сети" if device.is_connected else (
            "это устройство" if device.is_current else (
                f"было {fmt_ago(device.last_seen_at)}" if device.last_seen_at else "ещё не подключалось"
            )
        )
        lines.append(f"{index}. <b>{escape(device.title)}</b> — {state}")
    return head + "\n" + "\n".join(lines)


def device_confirm_text(device) -> str:
    return (
        f'{tg("warn")} <b>Удалить «{escape(device.title)}»?</b>\n\n'
        "Оно сразу отключится от VPN. Ключ или ссылку придётся выпускать заново."
    )


def fmt_ago(moment) -> str:
    """«3 мин назад», «2 ч назад», «вчера», «5 дн назад»."""
    import datetime as _dt

    if moment is None:
        return "давно"
    now = _dt.datetime.now(_dt.timezone.utc)
    stamp = moment if moment.tzinfo else moment.replace(tzinfo=_dt.timezone.utc)
    delta = max(0, int((now - stamp).total_seconds()))
    if delta < 60:
        return "только что"
    if delta < 3600:
        return f"{delta // 60} мин назад"
    if delta < 86400:
        return f"{delta // 3600} ч назад"
    days = delta // 86400
    return "вчера" if days == 1 else f"{days} дн назад"


def ios_key_text(key: IosKey) -> str:
    """Один ключ одним сообщением: нажатие на него копирует ссылку целиком."""
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
    """Условия тарифа одной строкой: срок, трафик, устройства, страны."""
    parts = [
        timeutils.plural_days(plan.duration_days),
        f"{plan.traffic_gb} ГБ трафика" if plan.traffic_gb else "безлимитный трафик",
        timeutils.plural_devices(plan.device_limit),
    ]

    if plan.server_limit:
        parts.append(timeutils.plural_countries(plan.server_limit))

    return " · ".join(parts)


def plan_price(plan: Plan, method: PayMethod) -> str:
    """Цена, которую спишут: вводная действует на все способы одинаково."""
    return f"{plan.stars_for()} ★" if method.code == "stars" else f"{plan.rub_for()} ₽"


def plans_text(method: PayMethod, plans: list[Plan]) -> str:
    lines = [f'{tg("wallet")} <b>Тарифы</b> · {escape(method.title)}', ""]

    for plan in plans:
        # Цена в заголовке строки, условия под ней: так же, как на экране
        # блоками — человек не должен видеть две разные витрины.
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
    # Цену называем в той валюте, в которой сейчас платят: обещать рубли
    # тому, кто выбрал звёзды, значит показать одну цену, а списать другую.
    price = f"{plan.stars_for()}★" if method == "stars" else f"{plan.rub_for()} ₽"

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
    """Счёт на оплату по ссылке: что, почём и что будет дальше."""
    terms = plan_terms(plan) if quantity == 1 else timeutils.plural_days(
        plan.duration_days * quantity
    )

    return (
        f'{tg("wallet")} <b>Счёт на оплату</b>\n\n'
        f"<b>{escape(plan.title)}</b> - {plan.rub_for(quantity)} ₽ · {escape(terms)}\n\n"
        + (
            # Цену продления называем до оплаты, а не через месяц.
            f"Дальше тариф стоит {plan.rub} ₽ в месяц.\n\n"
            if plan.intro_now(quantity)
            else ""
        )
        + 
        "Нажмите «Оплатить» и завершите платёж на открывшейся странице. "
        # Срок у способов разный: банковская ссылка живёт минуты, а перевод
        # в сети подтверждается своим ходом — обещать ему 15 минут нельзя.
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
    """Тот же экран простым текстом — если блоки не собрались."""
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


# --------------------------------------------------------------------------
# Ошибки панели человеческим языком
# --------------------------------------------------------------------------


def panel_error(error: PanelError) -> str:
    if isinstance(error, PanelUnavailable):
        return "Сервис недоступен, попробуйте через минуту."

    if error.status == 429:
        return "Слишком много попыток. Попробуйте позже."

    if error.code == "bad_credentials" or error.status == 401:
        return "Неверный логин или пароль."

    if error.code == "login_taken":
        return "Такой логин уже занят."

    # Текст ошибки приходит из панели и уходит в сообщение с parse_mode=HTML —
    # угловые скобки и амперсанды в нём Telegram не простит.
    return escape(str(error)) or "Что-то пошло не так."


def promo_text(days: int) -> str:
    """Экран после перехода по пригласительной ссылке."""
    return (
        f'{tg("gift")} <b>{timeutils.plural_days(days)} бесплатно</b>\n\n'
        "Вы перешли по пригласительной ссылке.\n"
        f"Откройте приложение, заведите аккаунт — и {timeutils.plural_days(days)} "
        "доступа начислим сразу, без карты и без оплаты.\n\n"
        f"{tg('star')} Друг по этой же ссылке получит столько же."
    )


def promo_granted_text(days: int) -> str:
    """
    Поздравление сразу после начисления.

    Отдельным сообщением и с кнопками «поделиться» и «скопировать»:
    человек прямо сейчас получил бесплатные дни, и это единственная
    секунда, когда он готов кому-то об этом сказать.
    """
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
    """Экран «iPhone» в разделе о сервисе: приложения нет, есть ключ."""
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
    """
    Экран подписки на канал.

    Два разных текста, потому что это две разные встречи. Пришедшему по
    рекламной ссылке говорим про его подарок: он уже знает, зачем пришёл, и
    подписка для него — последний шаг, а не новое требование. Остальным
    объясняем, что в канале вообще есть.
    """
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
    """Нажал «я подписался», а подписки нет."""
    return "Подписки пока не видно. Подпишитесь на канал и нажмите кнопку ещё раз."


# --------------------------------------------------------------------------
# Письма вдогонку
# --------------------------------------------------------------------------
#
# Все три — подпись под видео, а у подписи потолок 1024 символа. Отсюда и
# длина: три коротких абзаца, дальше кнопка. Первая строка говорит человеку,
# почему ему вообще пишут, — без неё сообщение читается как реклама.


def nudge_signup_text(days: int) -> str:
    """Зашёл в бота и не завёл аккаунт."""
    return (
        f'{tg("history")} <b>Вы зашли в бота, но не прошли регистрацию</b>\n\n'
        f"Дарим вам <b>{timeutils.plural_days(days)}</b> подписки — начислим "
        "сразу после регистрации.\n\n"
        "Нужны только логин и пароль, которые вы придумаете сами. "
        "Карту привязывать не нужно."
    )


def nudge_idle_text(days: int) -> str:
    """Аккаунт есть, а VPN так ни разу и не включили."""
    return (
        f'{tg("history")} <b>Вы зарегистрировались, но не начали пользоваться</b>\n\n'
        f"Дарим вам <b>{timeutils.plural_days(days)}</b> бесплатного доступа — "
        "они уже на вашем счету.\n\n"
        "Осталось поставить приложение и войти теми же логином и паролем. "
        "Если что-то не сойдётся — в «Инструкции» разбор по шагам."
    )


def nudge_renew_text(days_left: int, bonus: int) -> str:
    """Подписка на исходе. Неделя сверху — только тем, кто продлит сейчас."""
    return (
        f'{tg("renew")} <b>Подписка заканчивается через '
        f"{timeutils.plural_days(days_left)}</b>\n\n"
        f"Продлите её прямо сейчас — и мы добавим сверху "
        f"<b>{timeutils.plural_days(bonus)}</b> бесплатно.\n\n"
        "Неделя начисляется сама, как только пройдёт оплата. Предложение "
        "действует, пока идёт этот срок."
    )


def renew_bonus_text(bonus: int) -> str:
    """Продлил в срок — начислили обещанное."""
    return (
        f'{tg("gift")} <b>{timeutils.plural_days(bonus)} сверху — ваши</b>\n\n'
        "Спасибо, что продлили вовремя. Мы добавили их к подписке, "
        "ничего делать не нужно."
    )


def gift_granted_text(days: int) -> str:
    """
    Подарок начислен после регистрации — тот, что обещали письмом.

    Отдельно от `promo_granted_text`: там человек пришёл по чьей-то ссылке и
    ему есть чем поделиться, здесь делиться нечем — он просто вернулся и
    завёл аккаунт.
    """
    return (
        f'{tg("gift")} <b>{timeutils.plural_days(days)} начислены</b>\n\n'
        "Доступ уже работает — оплачивать ничего не нужно.\n\n"
        "Поставьте приложение и войдите теми же логином и паролем."
    )


# --------------------------------------------------------------------------
# Пауза подписки
# --------------------------------------------------------------------------


def freeze_ask_text(account: Account) -> str:
    """Экран подтверждения: что именно произойдёт после нажатия."""
    left = timeutils.plural_days(account.freeze.days_left or account.days_left or 0)

    return (
        f'{tg("freeze")} <b>Заморозить подписку</b>\n\n'
        f"В запасе <b>{left}</b> — на паузе они перестанут тратиться "
        "и дождутся вашего возвращения.\n\n"
        "Пока пауза стоит, VPN не работает: приложение отключится от серверов. "
        "Снять паузу можно в любой момент здесь же."
    )


def freeze_denied_text(account: Account) -> str:
    """Паузу поставить нельзя — панель объяснила почему."""
    reason = escape(account.freeze.reason or "Пауза сейчас недоступна.")

    return f'{tg("warn")} <b>Пауза недоступна</b>\n\n{reason}'


def freeze_done_text(account: Account) -> str:
    left = timeutils.plural_days(account.freeze.days_left or account.days_left or 0)

    return (
        f'{tg("freeze")} <b>Подписка на паузе</b>\n\n'
        f"Дни остановлены, в запасе {left}. Приложение сейчас отключится "
        "от серверов — это нормально.\n\n"
        "Вернётесь — нажмите «Снять паузу», доступ включится сразу."
    )


def resume_done_text(account: Account) -> str:
    left = timeutils.plural_days(account.freeze.days_left or account.days_left or 0)
    until = (
        f" Подписка действует до {timeutils.human_date(account.expires_at)}."
        if account.expires_at
        else ""
    )

    return (
        f'{tg("check")} <b>Пауза снята</b>\n\n'
        f"Доступ вернулся, в запасе {left}.{until}\n\n"
        "Подключайтесь в приложении — заново входить не нужно."
    )
