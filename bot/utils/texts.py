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
        "AmneziaVPN из App Store, в списке он появится под именем ProstoVPN.\n\n"
        f"Ключей {len(account.ios_keys)}: по одному на устройство, "
        "на два телефона один и тот же ключ не поставить.\n\n"
        f"Инструкция: {account.guide_url or config.guide_url}"
    )


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
    return f"{plan.stars} ★" if method.code == "stars" else f"{plan.rub} ₽"


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


def invoice_text(plan: Plan) -> str:
    """Счёт на оплату по ссылке: что, почём и что будет дальше."""
    return (
        f'{tg("wallet")} <b>Счёт на оплату</b>\n\n'
        f"<b>{escape(plan.title)}</b> - {plan.rub} ₽ · {escape(plan_terms(plan))}\n\n"
        "Нажмите «Оплатить» и завершите платёж на открывшейся странице. "
        "Ссылка действует 15 минут.\n\n"
        "Доступ включится сам, подтверждение придёт сюда."
    )


def autorenew_text(rec, options: list[Plan]) -> str:
    """Автопродление. Что происходит - зависит от статуса подписки."""
    head = f'{tg("calendar")} <b>Автопродление</b>\n\n'

    if rec is None or not rec.live:
        lines = [
            "Подключите автосписание - доступ будет продлеваться сам, "
            "без напоминаний. Отключается в один клик.",
            "",
        ]

        for plan in options:
            word = "в год" if plan.duration_days >= 365 else "в месяц"
            lines.append(f"<b>{escape(plan.title)}</b> - {plan.rub} ₽ {word}")

        return head + "\n".join(lines)

    title = escape(rec.plan_title or rec.plan_code or "Подписка")

    if rec.status == "pending":
        return (
            head
            + f"{title} - {rec.rub} ₽ {rec.interval_label}.\n\n"
            "Осталось привязать счёт: нажмите «Привязать счёт» и подтвердите "
            "на странице оплаты. Денег на этом шаге не списывается."
        )

    if rec.status == "past_due":
        return (
            head
            + f'{tg("warn")} Последнее списание не прошло.\n\n'
            "Продлите подписку вручную в «Тарифы и оплата» - или отключите "
            "автопродление."
        )

    when = (
        f"\nСледующее списание - {timeutils.human_date(rec.next_charge_at)}."
        if rec.next_charge_at
        else ""
    )

    return (
        head
        + f'{tg("check")} Работает.\n\n'
        f"{title} - {rec.rub} ₽ {rec.interval_label}.{when}\n\n"
        "Каждое продление подтверждаем сообщением сюда."
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
    # ВРЕМЕННО: кодовое слово для согласования с платёжным провайдером.
    # Убрать после подтверждения.
    return (
        f'{tg("brand")} <b>{config.brand}</b>\n\n'
        "Один аккаунт на все устройства.\n"
        "Логин и пароль работают на сайте, в приложении и здесь.\n\n"
        "<code>verplatega</code>"
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
        status = "отвечено" if ticket.status == "answered" else "в работе"
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

    return str(error) or "Что-то пошло не так."
