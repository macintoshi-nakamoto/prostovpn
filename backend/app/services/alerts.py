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
from ..models import Provisioning, Server, User, utcnow
from . import telegram

log = logging.getLogger("panel.alerts")

# Перевод строки для сообщений: в них его удобнее складывать, чем прятать
# в экранированные последовательности внутри длинных f-строк.
BR = chr(10)

# Сколько узел должен молчать, прежде чем будить админа. Одиночный отказ
# бывает от сетевой икоты по дороге, и будить из-за него — верный способ
# приучить не читать эти сообщения.
DOWN_AFTER = dt.timedelta(minutes=3)

# Один ключ на много устройств. Запас в один адрес — не щедрость: телефон
# на ходу переключается между Wi-Fi и сотовой сетью, и в один обход попадают
# оба адреса. Серия из трёх обходов подряд отсекает и это.
SHARE_GRACE = 1
SHARE_STRIKES = 3
# Второй раз про того же человека — не раньше чем через сутки: иначе
# сообщение о нём приходило бы каждую минуту, пока он не отключится.
SHARE_REPEAT = dt.timedelta(hours=24)


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


def check_sharing(db: OrmSession, ips_by_user: dict[int, set[str]]) -> list[str]:
    """
    Один ключ, воткнутый в десяток устройств.

    Считаем не соединения, а разные адреса, с которых сидит учётка: телефон
    держит соединения пачками, и по ним не понять, сколько за ключом людей.
    Адреса даёт сам Xray (`statsonlineiplist`), обход за трафиком забирает
    их тем же заходом по SSH.

    Здесь только счёт и сообщение админам. Резать доступ автоматически
    нельзя, пока не видно, как часто это ложная тревога: семья за двумя
    провайдерами и общий выход у оператора выглядят так же, а цена ошибки —
    отрезанный платящий человек.
    """
    now = utcnow()
    chats = admin_chats()
    sent: list[str] = []
    touched = False

    users = db.scalars(select(User).where(User.id.in_(ips_by_user.keys()))) if ips_by_user else []
    for user in users:
        count = len(ips_by_user.get(user.id) or ())
        allowed = user.device_limit(now) + SHARE_GRACE

        user.shared_ips = count
        user.shared_ips_at = now
        touched = True

        if count > allowed:
            user.shared_strikes += 1
        else:
            user.shared_strikes = 0
            continue

        if user.shared_strikes < SHARE_STRIKES:
            continue
        if user.shared_alert_at and now - user.shared_alert_at < SHARE_REPEAT:
            continue
        if not chats:
            log.warning(
                "ключ %s виден с %s адресов при лимите %s, но сказать некому",
                user.public_id,
                count,
                allowed,
            )
            continue

        text = (
            f"⚠️ <b>Ключ на нескольких устройствах</b>" + BR + BR
            + f"{user.login} ({user.public_id})" + BR
            + f"Адресов сейчас: <b>{count}</b>, по тарифу мест: "
            f"{user.device_limit(now)}." + BR
            + f"Держится {user.shared_strikes} обхода подряд."
        )
        if _notify(chats, text):
            user.shared_alert_at = now
            sent.append(f"share:{user.public_id}")

    if touched:
        db.commit()
    return sent
