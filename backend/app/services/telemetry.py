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

from ..config import settings
from ..models import ConnectReport, Server, Session, utcnow
from . import asn
from .alerts import BR, _notify, admin_chats

PROTOCOLS = ("awg", "vless", "hy2")
KINDS = ("wifi", "cellular", "ethernet", "other", "unknown", "none")
MAX_PER_REQUEST = 50
# Больше этого за сутки с одной сессии — это цикл, а не человек.
MAX_PER_SESSION_DAY = 300
KEEP_DAYS = 90
STAGES = ("handshake", "auth", "route", "engine", "other")

# Одного оператора называют по-разному: телефон говорит «MTS RUS», база
# ASN — «Mobile TeleSystems PJSC». Сводим к одному имени, иначе в таблице
# он же трижды.
OPERATOR_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("МТС", ("mts", "мтс", "mobile telesystems", "mobile tele", "mts rus")),
    ("МегаФон", ("megafon", "мегафон")),
    ("Билайн", ("beeline", "билайн", "vimpelcom", "вымпелком")),
    ("Tele2", ("tele2", "t2 mobile", "t2 rtk", "теле2", "т2", "t2")),
    ("Yota", ("yota", "йота", "scartel")),
    ("Ростелеком", ("rostelecom", "ростелеком")),
    ("Дом.ру", ("er-telecom", "ertelecom", "dom.ru", "домру", "дом.ру")),
    ("МГТС", ("mgts", "мгтс")),
    ("Tinkoff Mobile", ("tinkoff",)),
    ("СберМобайл", ("sbermobile", "сбермобайл")),
)

# Меньше попыток — не статистика, а случай.
MIN_ATTEMPTS = 8
# Тревога «похоже на блокировку»: окно, порог, сколько молчим после.
DROP_WINDOW_HOURS = 3
DROP_NOW_MAX_PCT = 40.0
DROP_BEFORE_MIN_PCT = 75.0
DROP_MIN_ATTEMPTS = 12
DROP_COOLDOWN = dt.timedelta(hours=12)

_drop_alerted: dict[tuple[str, str], dt.datetime] = {}


def normalize_operator(name: str | None) -> str | None:
    """
    Имя оператора к одному виду. Телефон отдаёт имя как настроил человек —
    бывает «t2💕»: сравниваем по словам, без эмодзи и знаков.
    """
    text = (name or "").strip()
    if not text:
        return None
    import re

    clean = " " + re.sub(r"[^a-zа-яё0-9]+", " ", text.lower()).strip() + " "
    for canonical, needles in OPERATOR_ALIASES:
        if any(f" {n.strip()} " in clean or (" " in n.strip() and n.strip() in clean) for n in needles):
            return canonical
    return text[:64]


def _clip(value: object, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def store(db: OrmSession, session: Session, reports: list[dict], ip: str | None = None) -> int:
    """
    Записывает отчёты сессии, возвращает сколько принято.

    Оператора на сотовой сети называет сам телефон. На Wi-Fi он видит
    только «Wi-Fi» — тогда провайдера берём по адресу: свежему адресу
    этого запроса, если он не наш узел, иначе адресу сессии.
    """
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
    real_ip = ip if ip and ip not in hosts else session.ip
    isp: str | None = None
    isp_known = False
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
        operator = normalize_operator(_clip(network.get("operator"), 64))
        if not operator and kind != "cellular":
            if not isp_known:
                isp_known = True
                isp = normalize_operator(asn.isp_name(real_ip))
            operator = isp
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
                operator=operator,
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



# ───────────────────────── что изменилось: сегодня против вчера


def _pct(bucket: dict) -> float:
    return round(bucket["ok"] / bucket["attempts"] * 100, 1) if bucket["attempts"] else 0.0


def changes(db: OrmSession, hours: int = 24) -> dict:
    """
    Последние `hours` часов против таких же часов перед ними, по парам
    оператор × протокол. Отсортировано от худшего изменения к лучшему:
    то, что просело, — наверху.
    """
    now = utcnow()
    hours = max(1, min(int(hours), 24 * 7))
    mid = now - dt.timedelta(hours=hours)
    start = mid - dt.timedelta(hours=hours)
    rows = list(
        db.scalars(select(ConnectReport).where(ConnectReport.created_at >= start))
    )

    cur: dict[tuple[str, str], dict] = defaultdict(_bucket)
    prev: dict[tuple[str, str], dict] = defaultdict(_bucket)
    cur_proto: dict[str, dict] = defaultdict(_bucket)
    prev_proto: dict[str, dict] = defaultdict(_bucket)
    errors: dict[str, int] = defaultdict(int)
    cur_total = _bucket()
    prev_total = _bucket()

    for r in rows:
        operator = (r.operator or "").strip() or ("Wi-Fi" if r.network_kind == "wifi" else "—")
        recent = r.created_at >= mid
        targets = (
            (cur[(operator, r.protocol)], cur_proto[r.protocol], cur_total)
            if recent
            else (prev[(operator, r.protocol)], prev_proto[r.protocol], prev_total)
        )
        for bucket in targets:
            bucket["attempts"] += 1
            if r.ok:
                bucket["ok"] += 1
        if recent and not r.ok and r.error:
            errors[r.error] += 1

    items = []
    for key in set(cur) | set(prev):
        c, p = cur[key], prev[key]
        if c["attempts"] < MIN_ATTEMPTS and p["attempts"] < MIN_ATTEMPTS:
            continue
        delta = None
        if c["attempts"] >= MIN_ATTEMPTS and p["attempts"] >= MIN_ATTEMPTS:
            delta = round(_pct(c) - _pct(p), 1)
        items.append(
            {
                "operator": key[0],
                "protocol": key[1],
                "attempts": c["attempts"],
                "ok_pct": _pct(c),
                "prev_attempts": p["attempts"],
                "prev_ok_pct": _pct(p) if p["attempts"] else None,
                "delta": delta,
            }
        )
    items.sort(key=lambda x: (x["delta"] if x["delta"] is not None else 1000, -x["attempts"]))

    protocols = []
    for proto in PROTOCOLS:
        c, p = cur_proto.get(proto), prev_proto.get(proto)
        if not c and not p:
            continue
        c = c or _bucket()
        p = p or _bucket()
        protocols.append(
            {
                "protocol": proto,
                "attempts": c["attempts"],
                "ok_pct": _pct(c),
                "prev_attempts": p["attempts"],
                "prev_ok_pct": _pct(p) if p["attempts"] else None,
                "delta": round(_pct(c) - _pct(p), 1) if c["attempts"] and p["attempts"] else None,
            }
        )

    return {
        "hours": hours,
        "reports": cur_total["attempts"],
        "ok_pct": _pct(cur_total),
        "prev_reports": prev_total["attempts"],
        "prev_ok_pct": _pct(prev_total) if prev_total["attempts"] else None,
        "items": items,
        "protocols": protocols,
        "errors": [
            {"error": text, "count": count}
            for text, count in sorted(errors.items(), key=lambda kv: -kv[1])[:8]
        ],
        "generated_at": now,
    }


PROTOCOL_TITLES = {"awg": "AmneziaWG", "vless": "Reality", "hy2": "Hysteria2"}


def _arrow(delta: float | None) -> str:
    if delta is None:
        return ""
    if delta <= -15:
        return " ⬇"
    if delta >= 15:
        return " ⬆"
    return ""


def digest_text(db: OrmSession, site: str) -> str:
    """Сводка за сутки для Telegram — коротко, самое важное первым."""
    data = changes(db, 24)
    lines = ["📊 <b>Связь за сутки</b>", ""]
    if data["reports"] == 0:
        lines.append("Отчётов от приложений не было.")
        return BR.join(lines)

    was = f" (вчера {data['prev_ok_pct']}%)" if data["prev_ok_pct"] is not None else ""
    lines.append(f"Попыток {data['reports']}, удачных {data['ok_pct']}%{was}.")

    protos = []
    for p in data["protocols"]:
        if not p["attempts"]:
            continue
        before = f" ({p['prev_ok_pct']}%)" if p["prev_ok_pct"] is not None else ""
        protos.append(f"{PROTOCOL_TITLES.get(p['protocol'], p['protocol'])} {p['ok_pct']}%{before}{_arrow(p['delta'])}")
    if protos:
        lines.append("По протоколам: " + ", ".join(protos) + ".")

    drops = [i for i in data["items"] if i["delta"] is not None and i["delta"] <= -15]
    if drops:
        lines.append("")
        lines.append("<b>Просело:</b>")
        for i in drops[:6]:
            lines.append(
                f"• {i['operator']} · {PROTOCOL_TITLES.get(i['protocol'], i['protocol'])}: "
                f"{i['ok_pct']}% (было {i['prev_ok_pct']}%), попыток {i['attempts']}"
            )
    else:
        lines.append("Заметных просадок по операторам нет.")

    bad = [i for i in data["items"] if i["attempts"] >= MIN_ATTEMPTS and i["ok_pct"] < 60 and i not in drops]
    if bad:
        lines.append("")
        lines.append("<b>Плохо и вчера, и сегодня:</b>")
        for i in bad[:4]:
            lines.append(f"• {i['operator']} · {PROTOCOL_TITLES.get(i['protocol'], i['protocol'])}: {i['ok_pct']}% из {i['attempts']}")

    if data["errors"]:
        lines.append("")
        lines.append("Ошибки: " + ", ".join(f"{e['error']} ×{e['count']}" for e in data["errors"][:4]))

    lines.append("")
    lines.append(f"Подробнее: {site.rstrip('/')}/admin/telemetry")
    return BR.join(lines)


def _digest_marker() -> "Path":
    from pathlib import Path

    return Path(settings().data_dir) / "telemetry_digest.date"


def daily_digest(db: OrmSession) -> bool:
    """Раз в сутки в заданный час — сводка админам. Отметка на диске переживает перезапуск."""
    now = utcnow()
    if now.hour != int(settings().telemetry_digest_hour_utc):
        return False
    marker = _digest_marker()
    today = now.strftime("%Y-%m-%d")
    try:
        if marker.exists() and marker.read_text().strip() == today:
            return False
    except OSError:
        pass
    chats = admin_chats()
    if not chats:
        return False
    if _notify(chats, digest_text(db, settings().site_url)):
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(today)
        except OSError:
            pass
        return True
    return False


def check_drops(db: OrmSession) -> list[str]:
    """
    Похоже на блокировку: за последние часы у пары оператор × протокол
    успех упал ниже порога, хотя сутки до того всё было хорошо. Одно
    сообщение на пару, потом молчим DROP_COOLDOWN.
    """
    now = utcnow()
    window_start = now - dt.timedelta(hours=DROP_WINDOW_HOURS)
    before_start = window_start - dt.timedelta(hours=24)
    rows = list(db.scalars(select(ConnectReport).where(ConnectReport.created_at >= before_start)))

    recent: dict[tuple[str, str], dict] = defaultdict(_bucket)
    before: dict[tuple[str, str], dict] = defaultdict(_bucket)
    for r in rows:
        operator = (r.operator or "").strip() or ("Wi-Fi" if r.network_kind == "wifi" else "—")
        target = recent if r.created_at >= window_start else before
        bucket = target[(operator, r.protocol)]
        bucket["attempts"] += 1
        if r.ok:
            bucket["ok"] += 1

    chats = admin_chats()
    sent: list[str] = []
    for key, c in recent.items():
        p = before.get(key)
        if c["attempts"] < DROP_MIN_ATTEMPTS or not p or p["attempts"] < DROP_MIN_ATTEMPTS:
            continue
        if _pct(c) > DROP_NOW_MAX_PCT or _pct(p) < DROP_BEFORE_MIN_PCT:
            continue
        last = _drop_alerted.get(key)
        if last and now - last < DROP_COOLDOWN:
            continue
        operator, proto = key
        others = [
            f"{PROTOCOL_TITLES.get(k[1], k[1])} {_pct(b)}%"
            for k, b in recent.items()
            if k[0] == operator and k[1] != proto and b["attempts"] >= MIN_ATTEMPTS
        ]
        text = (
            "🔻 <b>Похоже на блокировку</b>" + BR + BR
            + f"{operator} · {PROTOCOL_TITLES.get(proto, proto)}: за {DROP_WINDOW_HOURS} ч удачных "
            + f"{_pct(c)}% из {c['attempts']}, сутки до этого — {_pct(p)}%."
            + (BR + "Там же: " + ", ".join(others) + "." if others else "")
        )
        if not chats:
            continue
        if _notify(chats, text):
            _drop_alerted[key] = now
            sent.append(f"{operator}/{proto}")
    return sent
