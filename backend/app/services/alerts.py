"""
Оповещения администраторам: узел перестал отвечать и снова отвечает.

Получатели берутся ровно из `PANEL_ALERT_CHAT_IDS` и больше ниоткуда. Это
не оговорка в комментарии, а свойство кода: запросов к таблице
пользователей здесь нет вовсе, поэтому разослать такое письмо всем подряд
физически нечем. Список пуст — молчим и пишем в журнал.

Почему не отдельная проверка узлов: обход за трафиком и так ходит на
каждый сервер по SSH раз в интервал и уже отмечает в базе, ответил узел
или нет. Второй источник правды означал бы два разных ответа на вопрос
«узел жив?».
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..models import Provisioning, Server, utcnow
from . import telegram

log = logging.getLogger("panel.alerts")

# Сколько узел должен молчать, прежде чем будить админа. Одиночный отказ
# бывает от сетевой икоты по дороге, и будить из-за него — верный способ
# приучить не читать эти сообщения.
DOWN_AFTER = dt.timedelta(minutes=3)


def admin_chats() -> list[int]:
    """Кому слать. Только явный список из настроек, никаких выборок из базы."""
    raw = (settings().alert_chat_ids or "").replace(";", ",")
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            log.warning("PANEL_ALERT_CHAT_IDS: «%s» не похоже на chat_id", part)
    return out


def _notify(chats: list[int], text: str) -> bool:
    """Шлём каждому. Один недоступен — остальные всё равно должны узнать."""
    delivered = False
    for chat_id in chats:
        try:
            telegram.send(chat_id, text)
            delivered = True
        except Exception as exc:  # noqa: BLE001 — падать из-за оповещения нельзя
            log.warning("оповещение %s не ушло: %s", chat_id, exc)
    return delivered


def _human(delta: dt.timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    return f"{hours} ч {minutes % 60:02d} мин"


def _where(server: Server) -> str:
    place = server.country or server.name
    return f"{place} ({server.name})" if place != server.name else server.name


def check_nodes(db: OrmSession) -> list[str]:
    """
    Сверяет отметки живости и шлёт админам то, что изменилось.

    Возвращает описания отправленного — для журнала и тестов.
    """
    chats = admin_chats()
    now = utcnow()
    sent: list[str] = []

    servers = list(
        db.scalars(
            select(Server).where(
                Server.is_active.is_(True), Server.provisioning == Provisioning.SSH
            )
        )
    )

    for server in servers:
        down = server.down_since is not None and now - server.down_since >= DOWN_AFTER

        if down and server.alert_sent_at is None:
            if not chats:
                log.warning(
                    "узел «%s» не отвечает с %s, но PANEL_ALERT_CHAT_IDS пуст — "
                    "сказать некому",
                    server.name,
                    server.down_since,
                )
                continue
            text = (
                f"🔴 <b>Узел не отвечает</b>\n\n"
                f"{_where(server)}\n"
                f"Молчит {_human(now - server.down_since)}.\n\n"
                f"{server.traffic_error or 'SSH не отвечает'}"
            )
            if _notify(chats, text):
                server.alert_sent_at = now
                sent.append(f"down:{server.name}")

        elif server.down_since is None and server.alert_sent_at is not None:
            lay = ""
            if server.last_ok_at and server.alert_sent_at:
                lay = f" Лежал {_human(server.last_ok_at - server.alert_sent_at)}." \
                    if server.last_ok_at > server.alert_sent_at else ""
            text = f"🟢 <b>Узел снова отвечает</b>\n\n{_where(server)}.{lay}"
            _notify(chats, text)
            server.alert_sent_at = None
            sent.append(f"up:{server.name}")

    if sent:
        db.commit()
    return sent


def public_status(db: OrmSession) -> dict[str, object]:
    """
    Состояние узлов для сайта и мини-приложения.

    Наружу отдаём страну и название — адресов и портов здесь нет намеренно:
    страница статуса открыта всем, и она не должна быть заодно списком
    целей. Узлы с общим ключом пропускаем: за ними мы не ходим, и сказать
    о них нечего.
    """
    now = utcnow()
    servers = list(
        db.scalars(
            select(Server)
            .where(Server.is_active.is_(True), Server.provisioning == Provisioning.SSH)
            .order_by(Server.sort_order, Server.id)
        )
    )

    rows: list[dict[str, object]] = []
    checked: dt.datetime | None = None
    for server in servers:
        up = server.down_since is None or now - server.down_since < DOWN_AFTER
        if server.traffic_synced_at and (checked is None or server.traffic_synced_at > checked):
            checked = server.traffic_synced_at
        rows.append(
            {
                "name": server.name,
                "country": server.country,
                "country_code": server.country_code,
                "up": up,
                "down_since": server.down_since if not up else None,
            }
        )

    return {
        "ok": all(row["up"] for row in rows) if rows else True,
        "total": len(rows),
        "down": sum(0 if row["up"] else 1 for row in rows),
        "checked_at": checked,
        "servers": rows,
    }
