"""
Агент на узле (каталог agent/ в репозитории): приём снимков и живость по
протоколам.

Раньше панель узнавала о узле только по SSH: раз в минуту, три-четыре
сессии на узел, и «жив» значило «SSH ответил». Агент присылает снимок
сам, раз в несколько секунд, и в нём видно каждый протокол отдельно:
интерфейсы AmneziaWG, xray (Reality), Hysteria2 и службы systemd.

Первый шаг — агент только читает, а панель только смотрит. Счётчики
трафика по-прежнему зачисляет обход по SSH; здесь снимок кладётся рядом,
показывается в админке и сравнивается с тем, что снял SSH, — чтобы перед
переключением источника было видно, что цифры совпадают.

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

# Сверку с SSH пишем в журнал не на каждый снимок, а раз в столько снимков
# на узел: при интервале 15 с это примерно раз в десять минут.
COMPARE_EVERY = 40

_compare_tick: dict[int, int] = {}


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
        _compare(db, server, snapshot)
    except Exception:  # noqa: BLE001 — сверка для журнала, ронять приём нельзя
        log.exception("сверка снимка с базой не удалась")
    return problems


def _compare(db: OrmSession, server: Server, snapshot: dict) -> None:
    """
    Сверка с тем, что зачислил обход по SSH: те же пиры, те же байты?

    База отстаёт от снимка не больше чем на минуту, поэтому небольшая
    разница нормальна. Большая — повод не переключать источник, пока не
    понятно, откуда она.
    """
    tick = _compare_tick.get(server.id, 0) + 1
    _compare_tick[server.id] = tick
    if tick % COMPARE_EVERY != 1:
        return
    from .traffic import _parse_dump

    peers: dict[str, dict] = {}
    for iface in (snapshot.get("awg") or {}).values():
        dump = (iface or {}).get("dump") or ""
        if dump.strip():
            peers.update(_parse_dump(dump))

    keys = list(
        db.scalars(
            select(UserKey).where(UserKey.server_id == server.id, UserKey.revoked_at.is_(None))
        )
    )
    matched = 0
    node_bytes = 0
    base_bytes = 0
    for key in keys:
        peer = peers.get(key.public_key or "")
        if peer is None:
            continue
        matched += 1
        node_bytes += int(peer["rx"]) + int(peer["tx"])
        base_bytes += int(key.rx_bytes or 0) + int(key.tx_bytes or 0)
    diff = abs(node_bytes - base_bytes)
    share = (diff / node_bytes * 100) if node_bytes else 0.0
    log.info(
        "агент vs SSH, узел %s: пиров на узле %d, ключей в базе %d, совпало %d; "
        "байт по агенту %.2f ГБ, по базе %.2f ГБ, разница %.2f%%",
        server.name,
        len(peers),
        len(keys),
        matched,
        node_bytes / 1024**3,
        base_bytes / 1024**3,
        share,
    )


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
