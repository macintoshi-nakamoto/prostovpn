"""
Телеметрия подключений из наших приложений: что реально работает у людей.

Приложение после каждой попытки подключиться присылает короткий отчёт —
протокол, узел, порт, вышло или нет, сколько заняло, на какой сети и у
какого оператора. Без адресов и без содержимого: только то, что нужно,
чтобы перестать гадать, режут ли AmneziaWG на МТС и спасает ли Reality.

Отчёты хранятся 90 дней; сводка для админки считается на лету — объёмы
малы (сотни в сутки).
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as OrmSession

from ..models import ConnectReport, Server, Session, utcnow

PROTOCOLS = ("awg", "vless", "hy2")
KINDS = ("wifi", "cellular", "ethernet", "other", "unknown", "none")
MAX_PER_REQUEST = 50
# Больше этого за сутки с одной сессии — это цикл, а не человек.
MAX_PER_SESSION_DAY = 300
KEEP_DAYS = 90
STAGES = ("handshake", "auth", "route", "engine", "other")


def _clip(value: object, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def store(db: OrmSession, session: Session, reports: list[dict]) -> int:
    """Записывает отчёты сессии, возвращает сколько принято."""
    if not reports:
        return 0
    now = utcnow()
    day_ago = now - dt.timedelta(days=1)
    already = db.scalar(
        select(func.count())
        .select_from(ConnectReport)
        .where(ConnectReport.session_id == session.id, ConnectReport.created_at >= day_ago)
    ) or 0
    room = max(0, MAX_PER_SESSION_DAY - already)
    if room <= 0:
        return 0

    hosts = {
        row.host: row.id
        for row in db.execute(select(Server.host, Server.id)).all()
    }
    accepted = 0
    for raw in reports[:MAX_PER_REQUEST]:
        if accepted >= room:
            break
        if not isinstance(raw, dict):
            continue
        protocol = str(raw.get("protocol") or "").strip().lower()
        if protocol not in PROTOCOLS:
            continue
        network = raw.get("network") if isinstance(raw.get("network"), dict) else {}
        kind = str(network.get("kind") or "unknown").strip().lower()
        if kind not in KINDS:
            kind = "other"
        stage = str(raw.get("stage") or "other").strip().lower()
        if stage not in STAGES:
            stage = "other"
        host = _clip(raw.get("host"), 128)
        try:
            duration = max(0, min(int(raw.get("duration_ms") or 0), 10**7))
            attempts = max(0, min(int(raw.get("attempts") or 1), 100))
            port = int(raw.get("port") or 0) or None
        except (TypeError, ValueError):
            continue
        db.add(
            ConnectReport(
                user_id=session.user_id,
                session_id=session.id,
                platform=_clip(session.platform, 32) or "unknown",
                app_version=_clip(session.app_version, 32),
                network_kind=kind,
                operator=_clip(network.get("operator"), 64),
                country=_clip(network.get("country"), 2),
                protocol=protocol,
                server_id=hosts.get(host) if host else None,
                host=host,
                port=port,
                ok=bool(raw.get("ok")),
                stage=stage,
                duration_ms=duration,
                attempts=attempts,
                error=_clip(raw.get("error"), 160),
                created_at=now,
            )
        )
        accepted += 1
    db.commit()
    return accepted


def prune(db: OrmSession) -> int:
    edge = utcnow() - dt.timedelta(days=KEEP_DAYS)
    result = db.execute(delete(ConnectReport).where(ConnectReport.created_at < edge))
    db.commit()
    return int(result.rowcount or 0)


def _bucket() -> dict:
    return {"attempts": 0, "ok": 0, "durations": []}


def _finish(name_fields: dict, bucket: dict) -> dict:
    attempts = bucket["attempts"]
    ok = bucket["ok"]
    ok_durations = bucket["durations"]
    return {
        **name_fields,
        "attempts": attempts,
        "ok": ok,
        "ok_pct": round(ok / attempts * 100, 1) if attempts else 0.0,
        "median_ms": int(statistics.median(ok_durations)) if ok_durations else None,
    }


def summary(db: OrmSession, days: int = 7) -> dict:
    now = utcnow()
    since = now - dt.timedelta(days=max(1, days))
    rows = list(
        db.scalars(
            select(ConnectReport)
            .where(ConnectReport.created_at >= since)
            .order_by(ConnectReport.created_at.desc())
        )
    )
    servers = {s.id: s for s in db.scalars(select(Server))}

    by_protocol: dict[str, dict] = defaultdict(_bucket)
    by_operator: dict[tuple[str, str], dict] = defaultdict(_bucket)
    by_kind: dict[tuple[str, str], dict] = defaultdict(_bucket)
    by_server: dict[tuple[int | None, str], dict] = defaultdict(_bucket)
    by_platform: dict[tuple[str, str], dict] = defaultdict(_bucket)
    errors: dict[str, int] = defaultdict(int)
    users_ok: set[int] = set()
    users_fail_only: dict[int, bool] = {}

    for r in rows:
        operator = (r.operator or "").strip() or ("Wi-Fi" if r.network_kind == "wifi" else "—")
        for bucket in (
            by_protocol[r.protocol],
            by_operator[(operator, r.protocol)],
            by_kind[(r.network_kind, r.protocol)],
            by_server[(r.server_id, r.protocol)],
            by_platform[(r.platform, r.app_version or "")],
        ):
            bucket["attempts"] += 1
            if r.ok:
                bucket["ok"] += 1
                bucket["durations"].append(r.duration_ms)
        if not r.ok and r.error:
            errors[r.error] += 1
        if r.user_id is not None:
            if r.ok:
                users_ok.add(r.user_id)
            users_fail_only.setdefault(r.user_id, True)
            if r.ok:
                users_fail_only[r.user_id] = False

    total = len(rows)
    ok_total = sum(1 for r in rows if r.ok)

    def label_server(server_id: int | None) -> str:
        server = servers.get(server_id) if server_id else None
        if server is None:
            return "неизвестный узел"
        return server.country or server.name

    operators = [
        _finish({"operator": op, "protocol": proto}, bucket)
        for (op, proto), bucket in by_operator.items()
    ]
    operators.sort(key=lambda x: (-x["attempts"], x["operator"], x["protocol"]))

    recent_failures = [
        {
            "at": r.created_at,
            "platform": r.platform,
            "app_version": r.app_version,
            "network_kind": r.network_kind,
            "operator": r.operator,
            "protocol": r.protocol,
            "server": label_server(r.server_id),
            "port": r.port,
            "stage": r.stage,
            "duration_ms": r.duration_ms,
            "attempts": r.attempts,
            "error": r.error,
        }
        for r in rows
        if not r.ok
    ][:40]

    return {
        "period_days": days,
        "reports": total,
        "ok": ok_total,
        "ok_pct": round(ok_total / total * 100, 1) if total else 0.0,
        "users_reporting": len({r.user_id for r in rows if r.user_id is not None}),
        "users_never_ok": sum(1 for v in users_fail_only.values() if v),
        "protocols": [
            _finish({"protocol": proto}, by_protocol[proto]) for proto in PROTOCOLS if proto in by_protocol
        ],
        "operators": operators,
        "kinds": sorted(
            (_finish({"kind": kind, "protocol": proto}, bucket) for (kind, proto), bucket in by_kind.items()),
            key=lambda x: (-x["attempts"], x["kind"]),
        ),
        "servers": sorted(
            (
                _finish({"server_id": sid, "server": label_server(sid), "protocol": proto}, bucket)
                for (sid, proto), bucket in by_server.items()
            ),
            key=lambda x: (x["server"], x["protocol"]),
        ),
        "platforms": sorted(
            (
                _finish({"platform": platform, "app_version": version}, bucket)
                for (platform, version), bucket in by_platform.items()
            ),
            key=lambda x: (x["platform"], x["app_version"]),
        ),
        "errors": [
            {"error": text, "count": count}
            for text, count in sorted(errors.items(), key=lambda kv: -kv[1])[:15]
        ],
        "recent_failures": recent_failures,
        "generated_at": now,
    }
