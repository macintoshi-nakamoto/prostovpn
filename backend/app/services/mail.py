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


def credentials_body(login: str, password: str, expires_at: str) -> tuple[str, str]:
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
  <p style="font-size:13px;color:#8b8b93;margin:0">Пароль можно сменить в <a href="{base}/account.html" style="color:#8b8b93">личном кабинете</a>.</p>
  {_support_html()}
</div></body></html>"""
    return text, html


def renewed_body(login: str, expires_at: str) -> tuple[str, str]:
    """Продление: пароль не меняется, и повторять его в письме незачем."""
    base = settings().site_url.rstrip("/")
    text = f"""Здравствуйте!

Подписка продлена до {expires_at}.

Логин прежний: {login}. Пароль тоже прежний — менять ничего не нужно,
приложение продолжит работать само.

Личный кабинет: {base}/account.html

{_support_line()}"""
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:32px 16px;background:#0b0b0c;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e9e9ea">
<div style="max-width:520px;margin:0 auto">
  <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Подписка продлена до <b style="color:#ff6a1f">{expires_at}</b>.</p>
  <p style="font-size:14px;line-height:1.6;color:#a8a8b0;margin:0 0 24px">Логин прежний: <span style="font-family:ui-monospace,monospace">{login}</span>. Пароль тоже прежний — менять ничего не нужно, приложение продолжит работать само.</p>
  <p style="font-size:13px;color:#8b8b93;margin:0"><a href="{base}/account.html" style="color:#8b8b93">Личный кабинет</a></p>
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
