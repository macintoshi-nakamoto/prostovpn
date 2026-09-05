"""
Выдать токен агенту узла.

    cd /opt/prosto-vpn/backend
    sudo -u prostovpn .venv/bin/python tools/agent_token.py <имя или id узла>

Печатает токен один раз — в базе остаётся только хеш. Повторный запуск
выдаёт новый токен, прежний перестаёт работать: так и отзывают доступ
узлу, который больше не наш.
"""

from __future__ import annotations

import os
import sys

# Скрипт лежит в tools/, а пакет app — уровнем выше: запуск «python tools/…»
# сам по себе backend/ в sys.path не кладёт.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Server  # noqa: E402
from app.services import agent  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    who = sys.argv[1].strip()
    with SessionLocal() as db:
        server = db.get(Server, int(who)) if who.isdigit() else db.scalar(
            select(Server).where(Server.name == who)
        )
        if server is None:
            print(f"узел «{who}» не найден", file=sys.stderr)
            return 1
        token = agent.issue_token(db, server)
        print(f"узел: {server.name} ({server.host})")
        print(f"токен: {token}")
        print()
        print("на узле:")
        print(f"  sudo bash install.sh https://prostovpn.cc {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
