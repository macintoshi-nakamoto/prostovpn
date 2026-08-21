"""
Письмо с доступом.

Два решения, которые определяют, дойдёт ли оно вообще.

Первое: отправлять через транзакционного провайдера или SMTP своего домена,
а не напрямую с VPS. Письмо с логином и паролем, ушедшее с адреса без SPF,
DKIM и DMARC, попадает в спам почти гарантированно — а именно это письмо
человек и ждёт после оплаты. Настройка записей описана в deploy/README.md;
без неё канал считается ненастроенным.

Второе: в теме нет слова «VPN». Российские почтовые службы фильтруют такие
письма охотнее, а содержимого это не меняет — внутри логин, пароль и
ссылки на скачивание.

Чего в письме нет и не будет: ключей, конфигов, вложений, `vpn://`. Человек
за весь жизненный цикл видит ровно две строки.

Покупка с iPhone этого не меняет. Приложения под iOS нет, и подключаются
там ключом `vpn://` — но сам ключ живёт в личном кабинете, а письмо только
показывает дорогу к нему. Ключ — это рабочий доступ к VPN без пароля:
попав в чужие руки вместе с письмом, он не требует уже ничего.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from ..config import settings

log = logging.getLogger("panel.mail")


class MailError(RuntimeError):
    """Письмо не ушло — задание вернётся в очередь."""


# --- содержимое ---------------------------------------------------------------

_DOWNLOADS = (
    ("Windows", "/download.html#windows"),
    ("Android", "/download.html#android"),
    ("iPhone и iPad", "/download.html#ios"),
    ("macOS", "/download.html#macos"),
)


def _links() -> str:
    base = settings().site_url.rstrip("/")
    return "\n".join(f"  {title}: {base}{path}" for title, path in _DOWNLOADS)


def _ios_text(base: str) -> str:
    """
    Абзац для тех, кто купил с iPhone.

    Ключ сюда не кладём — только дорогу к нему: ссылка `vpn://` работает
    без пароля, и письмо с ней стало бы доступом к VPN для всякого, кто это
    письмо однажды прочитает.
    """
    return f"""
На iPhone приложения нет — подключение идёт через AmneziaVPN из App Store.
Ваш ключ уже готов и ждёт в личном кабинете: {base}/account
Инструкция по установке: {settings().guide_link}
"""


def _ios_html(base: str) -> str:
    return (
        '<p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">'
        "На iPhone приложения нет — подключение идёт через AmneziaVPN из App Store. "
        f'Ваш ключ уже готов в <a href="{base}/account" style="color:#ff6a1f;text-decoration:none">'
        "личном кабинете</a>, там же лежит "
        f'<a href="{settings().guide_link}" style="color:#ff6a1f;text-decoration:none">инструкция</a>.'
        "</p>"
    )


def _support_line() -> str:
    """Куда писать, если не получилось. Пусто — почты поддержки нет."""
    address = settings().support_email.strip()
    return f"Не получилось — напишите нам: {address}\n" if address else ""


def _support_html() -> str:
    address = settings().support_email.strip()
    if not address:
        return ""
    return (
        '<p style="font-size:13px;color:#8b8b93;margin:16px 0 0">Не получилось — напишите нам: '
        f'<a href="mailto:{address}" style="color:#8b8b93">{address}</a></p>'
    )


def credentials_body(login: str, password: str, expires_at: str, ios: bool = False) -> tuple[str, str]:
    """Первое письмо: логин и пароль. Возвращает (текст, html)."""
    base = settings().site_url.rstrip("/")
    text = f"""Здравствуйте!

Доступ готов. Вот он:

  Логин:  {login}
  Пароль: {password}

Действует до {expires_at}.

Скачайте приложение и введите эти две строки — больше ничего настраивать
не нужно.

{_links()}
{_ios_text(base) if ios else ""}
Пароль можно сменить в личном кабинете: {base}/account.html

{_support_line()}
Если письмо пришло вам по ошибке — просто удалите его.
"""
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:32px 16px;background:#0b0b0c;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e9e9ea">
<div style="max-width:520px;margin:0 auto">
  <p style="font-size:15px;line-height:1.6;margin:0 0 24px">Здравствуйте! Доступ готов.</p>
  <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:#141416;border:1px solid #26262a;border-radius:12px;padding:20px;margin:0 0 24px">
    <tr><td style="font-size:12px;color:#8b8b93;padding-bottom:4px">Логин</td></tr>
    <tr><td style="font-size:20px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#ff6a1f;padding-bottom:16px">{login}</td></tr>
    <tr><td style="font-size:12px;color:#8b8b93;padding-bottom:4px">Пароль</td></tr>
    <tr><td style="font-size:20px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#ff6a1f">{password}</td></tr>
  </table>
  <p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Действует до {expires_at}. Скачайте приложение и введите эти две строки — больше ничего настраивать не нужно.</p>
  <p style="font-size:14px;line-height:2;margin:0 0 24px">
    {"<br>".join(f'<a href="{base}{path}" style="color:#ff6a1f;text-decoration:none">{title}</a>' for title, path in _DOWNLOADS)}
  </p>
  {_ios_html(base) if ios else ""}
  <p style="font-size:13px;color:#8b8b93;margin:0">Пароль можно сменить в <a href="{base}/account.html" style="color:#8b8b93">личном кабинете</a>.</p>
  {_support_html()}
</div></body></html>"""
    return text, html


def renewed_body(login: str, expires_at: str, ios: bool = False) -> tuple[str, str]:
    """Продление: пароль не меняется, и повторять его в письме незачем."""
    base = settings().site_url.rstrip("/")
    ios_line = (
        "\nКлюч для AmneziaVPN на iPhone остался прежним — заново вставлять\n"
        "его не нужно.\n"
        if ios
        else ""
    )
    text = f"""Здравствуйте!

Подписка продлена до {expires_at}.

Логин прежний: {login}. Пароль тоже прежний — менять ничего не нужно,
приложение продолжит работать само.
{ios_line}
Личный кабинет: {base}/account.html

{_support_line()}"""
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:32px 16px;background:#0b0b0c;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e9e9ea">
<div style="max-width:520px;margin:0 auto">
  <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Подписка продлена до <b style="color:#ff6a1f">{expires_at}</b>.</p>
  <p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Логин прежний: <span style="font-family:ui-monospace,monospace">{login}</span>. Пароль тоже прежний — менять ничего не нужно, приложение продолжит работать само.{" Ключ для AmneziaVPN на iPhone тоже прежний." if ios else ""}</p>
  <p style="font-size:13px;color:#8b8b93;margin:0"><a href="{base}/account.html" style="color:#8b8b93">Личный кабинет</a></p>
  {_support_html()}
</div></body></html>"""
    return text, html


def recurring_on_body(
    plan_name: str, price_label: str, interval_label: str, next_charge: str
) -> tuple[str, str]:
    """Автопродление подключено: что, почём и когда спишется."""
    base = settings().site_url.rstrip("/")
    next_line = f"Следующее списание — {next_charge}.\n" if next_charge else ""
    text = f"""Здравствуйте!

Автопродление подключено: тариф «{plan_name}», {price_label} {interval_label}.
{next_line}
Доступ будет продлеваться сам, каждое продление мы подтверждаем письмом.
Отключить автопродление можно в любой момент в личном кабинете:
{base}/account

{_support_line()}"""
    next_html = f'<p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Следующее списание — {next_charge}.</p>' if next_charge else ""
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:32px 16px;background:#0b0b0c;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e9e9ea">
<div style="max-width:520px;margin:0 auto">
  <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Автопродление подключено: тариф «{plan_name}», <b style="color:#ff6a1f">{price_label} {interval_label}</b>.</p>
  {next_html}
  <p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Доступ будет продлеваться сам, каждое продление мы подтверждаем письмом. Отключить автопродление можно в любой момент в <a href="{base}/account" style="color:#ff6a1f;text-decoration:none">личном кабинете</a>.</p>
  {_support_html()}
</div></body></html>"""
    return text, html


def recurring_failed_body(plan_name: str, price_label: str, expires_at: str) -> tuple[str, str]:
    """Списание не прошло: что случилось и что делать."""
    base = settings().site_url.rstrip("/")
    text = f"""Здравствуйте!

Не получилось списать оплату за продление — тариф «{plan_name}», {price_label}.
Банк отклонил платёж или на счёте не хватило средств.

Доступ действует до {expires_at}. Чтобы он не прервался, продлите подписку
вручную в личном кабинете: {base}/account

{_support_line()}"""
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:32px 16px;background:#0b0b0c;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e9e9ea">
<div style="max-width:520px;margin:0 auto">
  <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Не получилось списать оплату за продление — тариф «{plan_name}», {price_label}. Банк отклонил платёж или на счёте не хватило средств.</p>
  <p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Доступ действует до <b style="color:#ff6a1f">{expires_at}</b>. Чтобы он не прервался, продлите подписку вручную в <a href="{base}/account" style="color:#ff6a1f;text-decoration:none">личном кабинете</a>.</p>
  {_support_html()}
</div></body></html>"""
    return text, html


def recurring_off_body(plan_name: str, expires_at: str) -> tuple[str, str]:
    """Автопродление отключено: оплаченные дни остаются."""
    base = settings().site_url.rstrip("/")
    text = f"""Здравствуйте!

Автопродление по тарифу «{plan_name}» отключено. Больше ничего списываться
не будет.

Оплаченный доступ действует до {expires_at}. Продлить можно в любой момент
в личном кабинете: {base}/account

{_support_line()}"""
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:32px 16px;background:#0b0b0c;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e9e9ea">
<div style="max-width:520px;margin:0 auto">
  <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Автопродление по тарифу «{plan_name}» отключено. Больше ничего списываться не будет.</p>
  <p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Оплаченный доступ действует до <b style="color:#ff6a1f">{expires_at}</b>. Продлить можно в любой момент в <a href="{base}/account" style="color:#ff6a1f;text-decoration:none">личном кабинете</a>.</p>
  {_support_html()}
</div></body></html>"""
    return text, html


# --- отправка -----------------------------------------------------------------


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Отправляет письмо выбранным способом. Кидает MailError при неудаче."""
    provider = settings().mail_provider.lower()
    if provider == "smtp":
        _send_smtp(to, subject, text, html)
    elif provider == "resend":
        _send_resend(to, subject, text, html)
    elif provider == "smtpbz":
        _send_smtpbz(to, subject, text, html)
    elif provider == "cloudflare":
        _send_cloudflare(to, subject, text, html)
    elif provider == "console":
        # Разработка: печатаем факт отправки, но не содержимое. Пароль в
        # логах не должен появляться даже в отладочном режиме.
        log.info("письмо (console): кому=%s тема=%r, %d символов", to, subject, len(text))
    else:
        raise MailError(f"неизвестный PANEL_MAIL_PROVIDER={provider!r}")


def _message(to: str, subject: str, text: str, html: str | None) -> EmailMessage:
    config = settings()
    message = EmailMessage()
    message["From"] = formataddr((config.mail_from_name, config.mail_from))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _send_smtp(to: str, subject: str, text: str, html: str | None) -> None:
    config = settings()
    if not config.smtp_host:
        raise MailError("PANEL_SMTP_HOST не задан")

    message = _message(to, subject, text, html)
    try:
        if config.smtp_ssl:
            server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
        with server:
            if config.smtp_starttls and not config.smtp_ssl:
                server.starttls()
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"SMTP: {exc}") from exc


def _send_smtpbz(to: str, subject: str, text: str, html: str | None) -> None:
    """
    Отправка через SMTP.bz.

    Российский отправитель выбран не из принципа: письмо с логином и паролем
    ждут в mail.ru, yandex.ru и rambler.ru, а они относятся к зарубежным
    рассыльщикам заметно строже — то же письмо через американскую
    инфраструктуру уезжает в спам чаще.

    По API, а не по SMTP: у них это один и тот же аккаунт, но HTTPS проходит
    там, где исходящий 587-й порт закрыт хостером, и ошибку возвращает
    текстом, а не обрывом соединения.

    Домен отправителя должен быть подтверждён в их панели — иначе приходит
    внятный отказ, и письмо честно возвращается в очередь.
    """
    config = settings()
    if not config.smtpbz_api_key:
        raise MailError("PANEL_SMTPBZ_API_KEY не задан")

    payload = {
        "name": config.mail_from_name,
        "from": config.mail_from,
        "to": to,
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html
    if config.support_email.strip():
        # Отвечают люди, а не отправитель рассылки: ответ на письмо должен
        # попадать в поддержку, а не в никуда.
        payload["reply"] = config.support_email.strip()

    try:
        response = httpx.post(
            "https://api.smtp.bz/v1/smtp/send",
            data=payload,
            headers={"Authorization": config.smtpbz_api_key},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise MailError(f"SMTP.bz недоступен: {exc}") from exc

    if response.status_code >= 400:
        raise MailError(f"SMTP.bz вернул {response.status_code}: {_smtpbz_error(response)}")

    # Двухсотка ещё не значит «принято»: отказ приезжает в теле.
    body = _json_or_none(response)
    if isinstance(body, dict) and body.get("result") is False:
        raise MailError(f"SMTP.bz отказал: {_smtpbz_error(response)}")


def _json_or_none(response: httpx.Response) -> object | None:
    try:
        return response.json()
    except ValueError:
        return None


def _smtpbz_error(response: httpx.Response) -> str:
    """Человеческий текст отказа: у них он лежит в errors.message."""
    body = _json_or_none(response)
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, dict) and errors.get("message"):
            return str(errors["message"])
        if isinstance(errors, str):
            return errors
    return response.text[:200]


def _send_cloudflare(to: str, subject: str, text: str, html: str | None) -> None:
    """
    Отправка через Cloudflare Email Service.

    Домен уже живёт в Cloudflare — там же его DNS, SPF и DKIM, — поэтому
    письмо уходит подписанным без отдельного почтового провайдера и без
    своего SMTP на VPS, с которого письма с паролем ушли бы в спам.

    Отправитель обязан быть на домене, заведённом в разделе Email Sending:
    на любой другой адрес API отвечает отказом, а не молча роняет письмо.
    """
    config = settings()
    if not config.cloudflare_account_id or not config.cloudflare_api_token:
        raise MailError("PANEL_CLOUDFLARE_ACCOUNT_ID или PANEL_CLOUDFLARE_API_TOKEN не заданы")

    payload: dict[str, object] = {
        "from": formataddr((config.mail_from_name, config.mail_from)),
        "to": to,
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{config.cloudflare_account_id}/email/sending/send"
    )
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {config.cloudflare_api_token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise MailError(f"Cloudflare недоступен: {exc}") from exc

    if response.status_code >= 400:
        raise MailError(f"Cloudflare вернул {response.status_code}: {response.text[:200]}")

    # Двухсотка ещё не значит «принято»: отказ приезжает в теле с success=false.
    body = response.json() if response.content else {}
    if not body.get("success", False):
        errors = body.get("errors") or []
        detail = "; ".join(str(item.get("message", item)) for item in errors) or response.text[:200]
        raise MailError(f"Cloudflare отказал: {detail}")


def _send_resend(to: str, subject: str, text: str, html: str | None) -> None:
    config = settings()
    if not config.resend_api_key:
        raise MailError("PANEL_RESEND_API_KEY не задан")

    payload = {
        "from": f"{config.mail_from_name} <{config.mail_from}>",
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {config.resend_api_key}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise MailError(f"Resend недоступен: {exc}") from exc
    if response.status_code >= 400:
        # Тело ответа сюда попасть может, а содержимое письма — нет.
        raise MailError(f"Resend вернул {response.status_code}: {response.text[:200]}")
