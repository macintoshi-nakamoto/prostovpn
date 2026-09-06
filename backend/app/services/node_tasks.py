"""
Задания агенту узла (третий шаг агента, 06.09.2026).

Панель кладёт задание в очередь (таблица node_tasks), агент забирает его в
ответе на очередной снимок — ручка /api/v1/node/report держит ответ, пока
задание не появится или не выйдет HOLD_SECONDS, — исполняет и подтверждает
в следующем снимке (поле acks), который шлёт сразу, не дожидаясь интервала.
Вызывающий ждёт подтверждения WAIT_SECONDS и, не дождавшись, идёт по SSH,
как раньше. Все задания идемпотентны (поставить пир, снять пир, дослать
учётку, записать конфиг), поэтому повтор по SSH после запоздавшего агента
не вредит.

Что это даёт: вход в приложение больше не ждёт SSH (пир встаёт за доли
секунды), а root-ключ панели к узлам нужен только когда агент молчит.
Команд произвольной формы здесь нет: у каждого вида задания свой набор
полей, и агент проверяет их у себя (agent/tasks.go).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import threading

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from ..db import SessionLocal
from ..models import NodeTask, Server, utcnow

log = logging.getLogger("panel.node_tasks")

# Сколько ждём подтверждения от агента, прежде чем идти по SSH. Агент
# получает задание мгновенно (ответ на снимок держится), исполняет за
# десятки миллисекунд и тут же шлёт снимок с подтверждением — обычно
# хватает секунды; запас на занятый узел.
WAIT_SECONDS = 8.0
# Сколько держим ответ на снимок в ожидании задания. Меньше интервала
# снимков (15 с) и таймаута клиента в агенте (20 с) и nginx (30 с).
HOLD_SECONDS = 12.0
# Задание без подтверждения дольше этого — просрочено: по SSH давно сделано.
EXPIRE_AFTER = dt.timedelta(minutes=2)
# Подтверждённые задания храним сутки — для разбора, потом чистим.
KEEP_ACKED = dt.timedelta(days=1)
# С этой версии агент умеет задания; старому ответ не держим и заданий не даём.
MIN_AGENT = (0, 3, 0)

KINDS = frozenset({"awg_add", "awg_remove", "xray_write", "xray_adu", "xray_rmu", "hy2_kick", "restart"})

_loop: asyncio.AbstractEventLoop | None = None
_wakeups: dict[int, asyncio.Event] = {}
_acks: dict[int, threading.Event] = {}
_acks_guard = threading.Lock()


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Цикл событий панели: из потоков обработчиков будим ожидающие ответы."""
    global _loop
    _loop = loop


def _wakeup(server_id: int) -> asyncio.Event:
    event = _wakeups.get(server_id)
    if event is None:
        event = asyncio.Event()
        _wakeups[server_id] = event
    return event


def wake(server_id: int) -> None:
    loop = _loop
    if loop is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(lambda: _wakeup(server_id).set())


def version_tuple(text: str | None) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(text or "").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def supports_tasks(version: str | None) -> bool:
    return version_tuple(version) >= MIN_AGENT


def available(server: Server) -> bool:
    """Агент на узле свежий и умеет задания."""
    from .agent import STALE_AFTER

    try:
        seen = server.agent_seen_at
        version = server.agent_version
    except Exception:  # noqa: BLE001 — объект вне сессии: считаем, что агента нет
        return False
    if seen is None or utcnow() - seen > STALE_AFTER:
        return False
    return supports_tasks(version)


def submit(server_id: int, kind: str, payload: dict) -> int:
    """Кладёт задание в очередь и будит ответ агенту. Возвращает id."""
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид задания: {kind}")
    with SessionLocal() as db:
        task = NodeTask(server_id=server_id, kind=kind, payload=dict(payload or {}))
        db.add(task)
        db.commit()
        task_id = task.id
    wake(server_id)
    return task_id


def run(server: Server, kind: str, payload: dict, *, wait: float | None = None) -> NodeTask | None:
    """
    Задание агенту с ожиданием подтверждения. None — агента нет или он не
    подтвердил вовремя: вызывающий идёт по SSH. Вернулось задание — смотреть
    task.ok и task.out.
    """
    if not available(server):
        return None
    timeout = WAIT_SECONDS if wait is None else wait
    event = threading.Event()
    task_id = submit(server.id, kind, payload)
    with _acks_guard:
        _acks[task_id] = event
    try:
        # Подтверждение могло прийти, пока мы регистрировали ожидание.
        with SessionLocal() as db:
            early = db.get(NodeTask, task_id)
            if early is not None and early.acked_at is not None:
                db.expunge(early)
                return early
        if not event.wait(timeout):
            log.info(
                "узел «%s»: агент не подтвердил %s за %.1f с — идём по SSH", server.name, kind, timeout
            )
            return None
    finally:
        with _acks_guard:
            _acks.pop(task_id, None)
    with SessionLocal() as db:
        task = db.get(NodeTask, task_id)
        if task is not None:
            db.expunge(task)
        return task


def take(server_id: int) -> list[dict]:
    """Неотправленные и не просроченные задания узла: отдаём и помечаем отправленными."""
    now = utcnow()
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(NodeTask)
                .where(
                    NodeTask.server_id == server_id,
                    NodeTask.sent_at.is_(None),
                    NodeTask.acked_at.is_(None),
                    NodeTask.created_at >= now - EXPIRE_AFTER,
                )
                .order_by(NodeTask.id)
            )
        )
        out = []
        for row in rows:
            row.sent_at = now
            out.append({"id": row.id, "kind": row.kind, "payload": row.payload or {}})
        if rows:
            db.commit()
    return out


async def pending(server_id: int, hold: float) -> list[dict]:
    """
    Для ручки снимка: задания узла, с ожиданием до hold секунд, если их пока
    нет. Событие сбрасываем ДО первой выборки — задание, положенное между
    выборкой и ожиданием, разбудит нас, а не потеряется.
    """
    event = _wakeup(server_id)
    event.clear()
    tasks = await asyncio.to_thread(take, server_id)
    if tasks or hold <= 0:
        return tasks
    try:
        await asyncio.wait_for(event.wait(), hold)
    except asyncio.TimeoutError:
        pass
    return await asyncio.to_thread(take, server_id)


def ack(db: OrmSession, server: Server, acks: object) -> int:
    """Подтверждения из снимка: отмечаем задания и будим ожидающих."""
    if not isinstance(acks, list) or not acks:
        return 0
    now = utcnow()
    done: list[int] = []
    for item in acks[:200]:
        if not isinstance(item, dict):
            continue
        try:
            task_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        task = db.get(NodeTask, task_id)
        if task is None or task.server_id != server.id or task.acked_at is not None:
            continue
        task.acked_at = now
        task.ok = bool(item.get("ok"))
        task.out = str(item.get("out") or "")[:4000] or None
        task.error = str(item.get("error") or "")[:1000] or None
        if not task.ok:
            log.warning(
                "узел «%s»: задание %s #%d не выполнено: %s", server.name, task.kind, task.id, task.error
            )
        done.append(task_id)
    if done:
        db.commit()
        with _acks_guard:
            for task_id in done:
                event = _acks.get(task_id)
                if event is not None:
                    event.set()
    return len(done)


def expire_stale(db: OrmSession) -> int:
    """Просроченные без подтверждения — закрываем с ошибкой; старые — чистим."""
    now = utcnow()
    rows = list(
        db.scalars(
            select(NodeTask).where(
                NodeTask.acked_at.is_(None), NodeTask.created_at < now - EXPIRE_AFTER
            )
        )
    )
    for row in rows:
        row.acked_at = now
        row.ok = False
        row.error = "нет подтверждения от агента"
    db.execute(delete(NodeTask).where(NodeTask.acked_at < now - KEEP_ACKED))
    db.commit()
    return len(rows)
