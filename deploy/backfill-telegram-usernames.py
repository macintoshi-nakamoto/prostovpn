#!/usr/bin/env python3
"""
Разово переносит @юзернеймы из базы бота в панель.

Панель узнаёт юзернейм только когда человек заходит в мини-приложение или
касается бота, поэтому у давно зарегистрированных поле пустое. Бот же хранит
юзернейм с первого /start — этим и заполняем.

Заполняем ТОЛЬКО пустые: то, что панель получила из свежей подписи Telegram,
новее записи бота, и перетирать его нельзя.

    python3 backfill-telegram-usernames.py --dry-run
    python3 backfill-telegram-usernames.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

PANEL_DB = "/opt/prosto-vpn/backend/panel.db"
BOT_DB = "/opt/prosto-bot/database/database.db"
USERNAME_MAX = 32


def clean(value: str | None) -> str | None:
    """Тот же разбор, что и в панели: без «@», только буквы, цифры и «_»."""
    name = (value or "").strip().lstrip("@")
    if not name or len(name) > USERNAME_MAX:
        return None
    return name if all(c.isascii() and (c.isalnum() or c == "_") for c in name) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-db", default=PANEL_DB)
    parser.add_argument("--bot-db", default=BOT_DB)
    parser.add_argument("--dry-run", action="store_true", help="только показать, ничего не писать")
    args = parser.parse_args()

    panel = sqlite3.connect(args.panel_db)
    bot = sqlite3.connect(args.bot_db)

    columns = {row[1] for row in panel.execute("PRAGMA table_info(users)")}
    if "telegram_username" not in columns:
        print("в панели нет колонки telegram_username — сначала выкатите панель", file=sys.stderr)
        return 1

    known = {}
    for user_id, username in bot.execute("select user_id, username from users"):
        name = clean(username)
        if name:
            known[user_id] = name

    targets = panel.execute(
        "select id, login, telegram_id from users "
        "where telegram_id is not null "
        "  and (telegram_username is null or telegram_username = '')"
    ).fetchall()

    updates = [(known[tg], uid, login) for uid, login, tg in targets if tg in known]
    for username, _, login in updates:
        print(f"  {login} -> @{username}")

    print(f"бот знает юзернеймов: {len(known)}")
    print(f"в панели ждут заполнения: {len(targets)}")
    print(f"будет заполнено: {len(updates)}")

    if args.dry_run or not updates:
        return 0

    panel.executemany(
        "update users set telegram_username = ? where id = ?",
        [(username, uid) for username, uid, _ in updates],
    )
    panel.commit()
    print("готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
