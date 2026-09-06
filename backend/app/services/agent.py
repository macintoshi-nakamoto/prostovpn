"""
Агент на узле (каталог agent/ в репозитории): приём снимков и живость по
протоколам.

Раньше панель узнавала о узле только по SSH: раз в минуту, три-четыре
сессии на узел, и «жив» значило «SSH ответил». Агент присылает снимок
сам, раз в несколько секунд, и в нём видно каждый протокол отдельно:
интерфейсы AmneziaWG, xray (Reality), Hysteria2 и службы systemd.

Второй шаг (06.09.2026, после суток сверки с разницей 0,00–0,02 %):
снимок — источник счётчиков и живости. Выдачи из снимка зачисляются тем
же кодом, что и снятые по SSH (traffic.apply_dumps, xray.apply_stats,
hy2.apply_traffic), а обход по SSH пропускает узел, пока снимок свежий,
и возвращается сам, когда агент замолчал. Писать на узел агент пока не
умеет: ключи и конфиги по-прежнему уезжают по SSH.

Оповещения — тем же адресатам и тем же способом, что и про падение узла
(services/alerts.py): только `PANEL_ALERT_CHAT_IDS`, выборок из таблицы
пользователей здесь нет.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import EndpointKind, EndpointState, NodeEndpoint, Provisioning, Server, UserKey, utcnow
from ..security import new_token, token_hash
from .alerts import BR, _human, _notify, _where, admin_chats, esc

log = logging.getLogger("panel.agent")

# Панель не настраивает логи: без своего обработчика в журнал попадают
# только WARNING и выше. Сверка «агент vs SSH» — INFO, и ради неё у этого
# журнала свой вывод; остальных логгеров это не касается.
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("panel.agent: %(message)s"))
    log.addHandler(_handler)
    log.propagate = False
log.setLevel(logging.INFO)

# Снимок с сотнями пиров — десятки килобайт; мегабайты сюда не приходят.
MAX_REPORT_BYTES = 2 * 1024 * 1024

# Сколько служба должна лежать по снимкам, прежде чем будить админа.
# Один снимок с ошибкой бывает от перезапуска xray при выкладке конфига.
TROUBLE_AFTER = dt.timedelta(minutes=3)

# Агент шлёт раз в 15 секунд; молчит две минуты — снимок устарел.
STALE_AFTER = dt.timedelta(minutes=2)

# Адреса, с которых сидят учётки VLESS, по последнему снимку каждого узла:
# server_id → (когда, {user_id: [ip, …]}). Их читает обход в main._sync_once
# для проверки «один ключ на много устройств».
_latest_ips: dict[int, tuple[dt.datetime, dict[int, list[str]]]] = {}


def issue_token(db: OrmSession, server: Server) -> str:
    """Новый токен узлу. Хранится только хеш — как у сессий."""
    token = new_token()
    server.agent_token_hash = token_hash(token)
    db.commit()
    return token


def server_by_token(db: OrmSession, token: str | None) -> Server | None:
    token = (token or "").strip()
    if not token:
        return None
    return db.scalar(select(Server).where(Server.agent_token_hash == token_hash(token)))


def _expectations(db: OrmSession, server: Server) -> tuple[bool, bool]:
    """Ждём ли на узле xray и Hysteria2 — по точкам входа в панели."""
    endpoints = list(
        db.scalars(
            select(NodeEndpoint).where(
                NodeEndpoint.server_id == server.id,
                NodeEndpoint.kind == EndpointKind.VLESS,
                NodeEndpoint.state != EndpointState.RETIRED,
            )
        )
    )
    expect_xray = bool(endpoints)
    expect_hy2 = any((e.params or {}).get("hy2", {}).get("port") for e in endpoints)
    return expect_xray, expect_hy2


def troubles(snapshot: dict, *, expect_xray: bool = True, expect_hy2: bool = True) -> list[str]:
    """Что на узле не так, по снимку. Пустой список — всё в порядке."""
    out: list[str] = []
    awg = snapshot.get("awg") or {}
    if not isinstance(awg, dict) or not awg:
        out.append("AmneziaWG: нет ни одного интерфейса")
    else:
        for name, iface in sorted(awg.items()):
            if not (iface or {}).get("ok"):
                out.append(f"AmneziaWG {name}: {(iface or {}).get('error') or 'не слушает'}")

    xray = snapshot.get("xray") or {}
    if expect_xray and not xray.get("ok"):
        out.append(f"Reality: {xray.get('error') or 'не отвечает'}")

    hy2 = snapshot.get("hy2") or {}
    if expect_hy2 and not hy2.get("ok"):
        out.append(f"Hysteria2: {hy2.get('error') or 'не отвечает'}")

    for unit, state in sorted((snapshot.get("services") or {}).items()):
        watched = unit in ("prosto-xray", "prosto-hy2") or unit.startswith("awg-quick@")
        if unit == "prosto-xray" and not expect_xray:
            watched = False
        if unit == "prosto-hy2" and not expect_hy2:
            watched = False
        if watched and state != "active":
            out.append(f"служба {unit}: {state}")
    return out


def store_report(db: OrmSession, server: Server, snapshot: dict) -> list[str]:
    """Кладёт снимок к узлу и отмечает, с какого момента что-то не так."""
    now = utcnow()
    expect_xray, expect_hy2 = _expectations(db, server)
    problems = troubles(snapshot, expect_xray=expect_xray, expect_hy2=expect_hy2)

    server.agent_seen_at = now
    server.agent_version = str(snapshot.get("agent") or "")[:32] or None
    server.agent_snapshot = json.dumps(snapshot, ensure_ascii=False)
    if problems:
        if server.agent_trouble_since is None:
            server.agent_trouble_since = now
    else:
        server.agent_trouble_since = None
    db.commit()

    try:
        _account(db, server, snapshot, now)
    except Exception:  # noqa: BLE001 — приём снимка важнее зачисления: обход по SSH подстрахует
        log.exception("зачисление снимка узла «%s» не удалось", server.name)
    return problems


def _account(db: OrmSession, server: Server, snapshot: dict, now: dt.datetime) -> None:
    """
    Зачисляет снимок: пиры AmneziaWG, учётки xray, дельты Hysteria2 —
    теми же функциями, что и обход по SSH. Общий ключ (provisioning=shared)
    счётчиков по людям не имеет — там нечего зачислять.
    """
    if server.provisioning != Provisioning.SSH:
        return
    from . import hy2, traffic, xray

    awg = snapshot.get("awg") or {}
    dumps = {
        name: str((iface or {}).get("dump") or "")
        for name, iface in awg.items()
        if isinstance(iface, dict) and iface.get("ok")
    }
    if dumps:
        traffic.apply_dumps(db, server, dumps)

    xray_state = snapshot.get("xray") or {}
    if isinstance(xray_state, dict) and xray_state.get("api_ok"):
        result = xray.apply_stats(
            db,
            server,
            str(xray_state.get("stats") or ""),
            str(xray_state.get("online") or ""),
            str(xray_state.get("ips") or ""),
        )
        ips = result.get("ips") if isinstance(result, dict) else None
        _latest_ips[server.id] = (now, {int(k): list(v) for k, v in (ips or {}).items()})

    hy2_state = snapshot.get("hy2") or {}
    if isinstance(hy2_state, dict) and hy2_state.get("ok"):
        online = hy2_state.get("online") if isinstance(hy2_state.get("online"), dict) else {}
        data = hy2_state.get("traffic") if isinstance(hy2_state.get("traffic"), dict) else {}
        # Байты зачисляем только с пометкой cleared: агент 0.2+ сам обнуляет
        # счётчики и шлёт дельты. Без пометки цифры абсолютные (старый агент
        # или панель ещё не разрешила) — их по-прежнему снимает обход по SSH.
        hy2.apply_traffic(db, server, data if hy2_state.get("cleared") else {}, online)


def _fresh_snapshot(server: Server) -> dict | None:
    if not server.agent_snapshot or server.agent_seen_at is None:
        return None
    if utcnow() - server.agent_seen_at > STALE_AFTER:
        return None
    try:
        snap = json.loads(server.agent_snapshot)
    except ValueError:
        return None
    return snap if isinstance(snap, dict) else None


def covered(server: Server) -> set[str]:
    """
    Что из обхода уже зачислено по свежему снимку агента — эти части обход
    по SSH пропускает: "awg", "xray", "hy2". Пустое множество — агент
    молчит, обход работает как раньше.
    """
    snap = _fresh_snapshot(server)
    if snap is None:
        return set()
    parts: set[str] = set()
    awg = snap.get("awg") or {}
    if isinstance(awg, dict) and any(
        isinstance(i, dict) and i.get("ok") and i.get("dump") for i in awg.values()
    ):
        parts.add("awg")
    xray = snap.get("xray") or {}
    if isinstance(xray, dict) and xray.get("api_ok"):
        parts.add("xray")
    hy2 = snap.get("hy2") or {}
    if isinstance(hy2, dict) and hy2.get("ok") and hy2.get("cleared"):
        parts.add("hy2")
    return parts


def awg_dumps(server: Server) -> dict[str, str] | None:
    """Выдачи `awg show dump` из свежего снимка — для сверки пиров без SSH."""
    snap = _fresh_snapshot(server)
    if snap is None or "awg" not in covered(server):
        return None
    return {
        name: str((iface or {}).get("dump") or "")
        for name, iface in (snap.get("awg") or {}).items()
        if isinstance(iface, dict) and iface.get("ok")
    }


def recent_ips() -> dict[int, set[str]]:
    """Адреса учёток VLESS по свежим снимкам всех узлов: user_id → адреса."""
    now = utcnow()
    out: dict[int, set[str]] = {}
    for server_id, (at, ips) in list(_latest_ips.items()):
        if now - at > STALE_AFTER:
            _latest_ips.pop(server_id, None)
            continue
        for user_id, addresses in ips.items():
            out.setdefault(user_id, set()).update(addresses)
    return out


def health(server: Server) -> dict | None:
    """Сводка по последнему снимку для админки. Нет снимка — нет сводки."""
    if not server.agent_snapshot:
        return None
    try:
        snap = json.loads(server.agent_snapshot)
    except ValueError:
        return None
    if not isinstance(snap, dict):
        return None

    seen = server.agent_seen_at
    stale = seen is None or utcnow() - seen > STALE_AFTER
    awg = snap.get("awg") or {}
    xray = snap.get("xray") or {}
    hy2 = snap.get("hy2") or {}
    online_hy2 = 0
    if isinstance(hy2.get("online"), dict):
        online_hy2 = sum(1 for count in hy2["online"].values() if int(count or 0) > 0)
    load = snap.get("load") or [0]

    problems = troubles(snap)
    return {
        "version": server.agent_version,
        "seen_at": seen,
        "stale": stale,
        "awg_ok": bool(awg) and all((i or {}).get("ok") for i in awg.values()),
        "xray_ok": bool(xray.get("ok")),
        "hy2_ok": bool(hy2.get("ok")),
        "peers": sum(int((i or {}).get("peers") or 0) for i in awg.values()),
        "online_vless": int(xray.get("online_count") or 0),
        "online_hy2": online_hy2,
        "load1": float(load[0] or 0) if load else 0.0,
        "mem_avail_mb": int(snap.get("mem_avail_kb") or 0) // 1024,
        "uptime_s": int(snap.get("uptime_s") or 0),
        "took_ms": int(snap.get("took_ms") or 0),
        "trouble": "; ".join(problems) or None,
        "trouble_since": server.agent_trouble_since,
    }


def check_agents(db: OrmSession) -> list[str]:
    """
    Будит админов, когда служба на узле лежит дольше TROUBLE_AFTER, и
    отчитывается, когда всё вернулось. Узел без агента здесь не участвует —
    за него по-прежнему отвечает обход по SSH и alerts.check_nodes.
    """
    chats = admin_chats()
    now = utcnow()
    sent: list[str] = []

    servers = db.scalars(
        select(Server).where(
            Server.is_active.is_(True),
            Server.provisioning == Provisioning.SSH,
            Server.agent_snapshot.is_not(None),
        )
    )
    for server in servers:
        since = server.agent_trouble_since
        troubled = since is not None and now - since >= TROUBLE_AFTER

        if troubled and server.agent_alert_sent_at is None:
            summary = health(server) or {}
            if not chats:
                log.warning(
                    "узел «%s»: %s — но PANEL_ALERT_CHAT_IDS пуст", server.name, summary.get("trouble")
                )
                continue
            text = (
                "🟠 <b>На узле не работает часть служб</b>" + BR + BR
                + _where(server) + BR
                + esc(summary.get("trouble") or "неизвестно что") + BR + BR
                + f"Держится {_human(now - since)}. Узел при этом по SSH отвечает."
            )
            if _notify(chats, text):
                server.agent_alert_sent_at = now
                sent.append(f"trouble:{server.name}")

        elif since is None and server.agent_alert_sent_at is not None:
            _notify(chats, "🟢 <b>Службы узла снова в порядке</b>" + BR + BR + _where(server))
            server.agent_alert_sent_at = None
            sent.append(f"fine:{server.name}")

    if sent:
        db.commit()
    return sent
