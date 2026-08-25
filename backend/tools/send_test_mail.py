from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services import mail


def main() -> int:
    if len(sys.argv) < 2:
        print("укажите адрес: send_test_mail.py кому@example.com", file=sys.stderr)
        return 2

    to = sys.argv[1]
    config = settings()
    print(f"провайдер: {config.mail_provider}")
    print(f"от кого:   {config.mail_from_name} <{config.mail_from}>")
    print(f"кому:      {to}")

    text = (
        "Это проверка почтового канала Prosto VPN.\n\n"
        "Письмо отправлено тем же кодом, что и письма с доступом: если оно "
        "дошло и не в спаме — канал настроен.\n"
    )
    html = (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        "<p>Это проверка почтового канала Prosto VPN.</p>"
        "<p>Письмо отправлено тем же кодом, что и письма с доступом: если оно дошло "
        "и не в спаме — канал настроен.</p></div>"
    )

    try:
        mail.send(to, "Prosto — проверка почты", text, html)
    except mail.MailError as exc:
        print(f"не отправилось: {exc}", file=sys.stderr)
        return 1

    print("отправлено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
