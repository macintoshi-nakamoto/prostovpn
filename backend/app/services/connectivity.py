"""
Карта блокировок — публичная сводка телеметрии связи (prostovpn.cc/blocks).

Приложения сообщают о каждой попытке подключиться: оператор, протокол,
вышло или нет (services/telemetry.py). Здесь из этого складывается картина
для всех, без входа: у какого оператора что работает прямо сейчас.

Что показываем и что нет:
  * только сводные числа по оператору и протоколу — ни адресов, ни
    устройств, ни времени конкретной попытки;
  * оператор попадает на карту, когда за сутки по нему набралось не меньше
    MIN_OPERATOR_ATTEMPTS попыток с MIN_OPERATOR_SESSIONS разных устройств:
    меньше — это чей-то один телефон, а не оператор;
  * «сейчас» — последние NOW_HOURS часов; если за это время попыток мало,
    оценка берётся по суткам и об этом сказано (basis).

Считается не чаще раза в CACHE_SECONDS: страница открыта без входа, и
пересчитывать выборку на каждый запрос значило бы отдать её любому
скрипту. Та же сводка потом пригодится приложениям, чтобы выбирать способ
подключения под оператора.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import ConnectReport, utcnow
from . import telemetry
from .telemetry import PROTOCOLS, PROTOCOL_TITLES, normalize_operator

NOW_HOURS = 3
DAY_HOURS = 24
HOURLY_POINTS = 24

MIN_OPERATOR_ATTEMPTS = 10
MIN_OPERATOR_SESSIONS = 5
MIN_PROTOCOL_ATTEMPTS = 6
MIN_NOW_ATTEMPTS = 6

OK_MIN_PCT = 85.0
PARTIAL_MIN_PCT = 50.0
EVENT_DELTA_PCT = 15.0

CACHE_SECONDS = 60

# Операторы, за которыми следим всегда: без данных за сутки они попадают в
# список «наблюдаем», а не исчезают — карта должна показывать, кого мы
# видим, даже пока данных мало.
WATCHED = ("МТС", "МегаФон", "Билайн", "Tele2", "Yota", "Ростелеком", "Дом.ру", "МГТС")

# Названия операторов, которые телефон отдаёт как «сотовые».
CELLULAR = {"МТС", "МегаФон", "Билайн", "Tele2", "Yota", "Tinkoff Mobile", "СберМобайл"}

_cache: dict = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def _bucket() -> dict:
    return {"attempts": 0, "ok": 0}


def _pct(bucket: dict) -> float | None:
    if not bucket["attempts"]:
        return None
    return round(100.0 * bucket["ok"] / bucket["attempts"], 1)


def _status(pct: float | None) -> str:
    if pct is None:
        return "quiet"
    if pct >= OK_MIN_PCT:
        return "ok"
    if pct >= PARTIAL_MIN_PCT:
        return "partial"
    return "blocked"


def _trend(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "flat"
    if cur - prev >= EVENT_DELTA_PCT:
        return "up"
    if prev - cur >= EVENT_DELTA_PCT:
        return "down"
    return "flat"


def build(db: OrmSession, now: dt.datetime | None = None) -> dict:
    """Сводка без кэша — для тестов и для пересчёта."""
    now = now or utcnow()
    day_ago = now - dt.timedelta(hours=DAY_HOURS)
    two_days_ago = day_ago - dt.timedelta(hours=DAY_HOURS)
    now_edge = now - dt.timedelta(hours=NOW_HOURS)

    rows = db.execute(
        select(
            ConnectReport.operator,
            ConnectReport.network_kind,
            ConnectReport.protocol,
            ConnectReport.ok,
            ConnectReport.created_at,
            ConnectReport.session_id,
            ConnectReport.platform,
        ).where(ConnectReport.created_at >= two_days_ago, ConnectReport.created_at <= now)
    ).all()

    class Op:
        def __init__(self) -> None:
            self.day = _bucket()
            self.now = _bucket()
            self.prev = _bucket()
            self.sessions: set = set()
            self.kinds: dict[str, int] = defaultdict(int)
            self.hourly = [_bucket() for _ in range(HOURLY_POINTS)]
            self.proto: dict[str, dict] = {}

        def proto_of(self, code: str) -> dict:
            slot = self.proto.get(code)
            if slot is None:
                slot = {
                    "day": _bucket(),
                    "now": _bucket(),
                    "prev": _bucket(),
                    "hourly": [_bucket() for _ in range(HOURLY_POINTS)],
                }
                self.proto[code] = slot
            return slot

    ops: dict[str, Op] = defaultdict(Op)
    total_day = _bucket()
    total_now = _bucket()
    total_prev = _bucket()
    sessions_day: set = set()
    platforms: dict[str, int] = defaultdict(int)
    proto_day: dict[str, dict] = {code: _bucket() for code in PROTOCOLS}
    proto_now: dict[str, dict] = {code: _bucket() for code in PROTOCOLS}

    for operator, kind, protocol, ok, created_at, session_id, platform in rows:
        recent = created_at >= day_ago
        name = normalize_operator(operator) if operator else None
        if recent:
            total_day["attempts"] += 1
            total_day["ok"] += 1 if ok else 0
            if session_id:
                sessions_day.add(session_id)
            platforms[(platform or "unknown").lower()] += 1
            if protocol in proto_day:
                proto_day[protocol]["attempts"] += 1
                proto_day[protocol]["ok"] += 1 if ok else 0
            if created_at >= now_edge:
                total_now["attempts"] += 1
                total_now["ok"] += 1 if ok else 0
                if protocol in proto_now:
                    proto_now[protocol]["attempts"] += 1
                    proto_now[protocol]["ok"] += 1 if ok else 0
        else:
            total_prev["attempts"] += 1
            total_prev["ok"] += 1 if ok else 0
        if not name:
            continue
        op = ops[name]
        slot = op.proto_of(protocol) if protocol in PROTOCOLS else None
        if not recent:
            op.prev["attempts"] += 1
            op.prev["ok"] += 1 if ok else 0
            if slot:
                slot["prev"]["attempts"] += 1
                slot["prev"]["ok"] += 1 if ok else 0
            continue
        op.day["attempts"] += 1
        op.day["ok"] += 1 if ok else 0
        if session_id:
            op.sessions.add(session_id)
        op.kinds[kind or "unknown"] += 1
        age_h = int((now - created_at).total_seconds() // 3600)
        index = HOURLY_POINTS - 1 - min(max(age_h, 0), HOURLY_POINTS - 1)
        op.hourly[index]["attempts"] += 1
        op.hourly[index]["ok"] += 1 if ok else 0
        if created_at >= now_edge:
            op.now["attempts"] += 1
            op.now["ok"] += 1 if ok else 0
        if slot:
            slot["day"]["attempts"] += 1
            slot["day"]["ok"] += 1 if ok else 0
            slot["hourly"][index]["attempts"] += 1
            slot["hourly"][index]["ok"] += 1 if ok else 0
            if created_at >= now_edge:
                slot["now"]["attempts"] += 1
                slot["now"]["ok"] += 1 if ok else 0

    operators = []
    watching = []
    for name, op in ops.items():
        if op.day["attempts"] < MIN_OPERATOR_ATTEMPTS or len(op.sessions) < MIN_OPERATOR_SESSIONS:
            if name in WATCHED:
                watching.append(name)
            continue
        kind = "cellular" if name in CELLULAR else max(op.kinds, key=op.kinds.get) if op.kinds else "unknown"
        if kind not in ("cellular", "wifi"):
            kind = "cellular" if name in CELLULAR else "wifi"

        pct_now = _pct(op.now) if op.now["attempts"] >= MIN_NOW_ATTEMPTS else None
        pct_day = _pct(op.day)
        pct_prev = _pct(op.prev) if op.prev["attempts"] >= MIN_OPERATOR_ATTEMPTS else None
        basis = "now" if pct_now is not None else "day"
        status = _status(pct_now if pct_now is not None else pct_day)

        protocols = []
        best = None
        best_pct = -1.0
        for code in PROTOCOLS:
            slot = op.proto.get(code)
            if slot is None or slot["day"]["attempts"] < MIN_PROTOCOL_ATTEMPTS:
                continue
            p_now = _pct(slot["now"]) if slot["now"]["attempts"] >= MIN_NOW_ATTEMPTS else None
            p_day = _pct(slot["day"])
            p_prev = _pct(slot["prev"]) if slot["prev"]["attempts"] >= MIN_PROTOCOL_ATTEMPTS else None
            shown = p_now if p_now is not None else p_day
            protocols.append(
                {
                    "code": code,
                    "title": PROTOCOL_TITLES.get(code, code),
                    "attempts_now": slot["now"]["attempts"],
                    "ok_pct_now": p_now,
                    "attempts_day": slot["day"]["attempts"],
                    "ok_pct_day": p_day,
                    "ok_pct_prev": p_prev,
                    "status": _status(shown),
                    "trend": _trend(p_day, p_prev),
                    "hourly": [
                        {"attempts": h["attempts"], "ok_pct": _pct(h)} for h in slot["hourly"]
                    ],
                }
            )
            if p_now is not None and p_now > best_pct:
                best, best_pct = code, p_now

        operators.append(
            {
                "name": name,
                "kind": kind,
                "status": status,
                "basis": basis,
                "attempts_now": op.now["attempts"],
                "ok_pct_now": pct_now,
                "attempts_day": op.day["attempts"],
                "ok_pct_day": pct_day,
                "ok_pct_prev": pct_prev,
                "trend": _trend(pct_day, pct_prev),
                "devices_day": len(op.sessions),
                "best_now": best,
                "protocols": protocols,
                "hourly": [{"attempts": h["attempts"], "ok_pct": _pct(h)} for h in op.hourly],
            }
        )

    order = {"blocked": 0, "partial": 1, "quiet": 2, "ok": 3}
    operators.sort(key=lambda o: (order.get(o["status"], 9), -o["attempts_day"]))
    for name in WATCHED:
        if name not in ops and name not in watching:
            watching.append(name)

    # События за сутки: пары оператор × протокол, у которых успех изменился
    # на EVENT_DELTA_PCT и больше против прошлых суток — и падения, и
    # восстановления. Считает та же функция, что и дайджест админам.
    events = []
    for item in telemetry.changes(db, DAY_HOURS)["items"]:
        delta = item.get("delta")
        if delta is None or abs(delta) < EVENT_DELTA_PCT:
            continue
        events.append(
            {
                "operator": item["operator"],
                "protocol": item["protocol"],
                "title": PROTOCOL_TITLES.get(item["protocol"], item["protocol"]),
                "kind": "drop" if delta < 0 else "recovery",
                "from_pct": item["prev_ok_pct"],
                "to_pct": item["ok_pct"],
                "delta": delta,
                "attempts": item["attempts"],
            }
        )

    trouble = sum(1 for o in operators if o["status"] in ("partial", "blocked"))
    return {
        "updated_at": now,
        "refresh_seconds": CACHE_SECONDS,
        "now_hours": NOW_HOURS,
        "day_hours": DAY_HOURS,
        "summary": {
            "operators": len(operators),
            "trouble": trouble,
            "blocked": sum(1 for o in operators if o["status"] == "blocked"),
            "attempts_day": total_day["attempts"],
            "attempts_now": total_now["attempts"],
            "devices_day": len(sessions_day),
            "ok_pct_day": _pct(total_day),
            "ok_pct_now": _pct(total_now) if total_now["attempts"] >= MIN_NOW_ATTEMPTS else None,
            "ok_pct_prev": _pct(total_prev) if total_prev["attempts"] >= MIN_OPERATOR_ATTEMPTS else None,
            "platforms": sorted(platforms, key=platforms.get, reverse=True),
        },
        "protocols": [
            {
                "code": code,
                "title": PROTOCOL_TITLES.get(code, code),
                "attempts_day": proto_day[code]["attempts"],
                "ok_pct_day": _pct(proto_day[code]),
                "ok_pct_now": _pct(proto_now[code])
                if proto_now[code]["attempts"] >= MIN_NOW_ATTEMPTS
                else None,
            }
            for code in PROTOCOLS
            if proto_day[code]["attempts"]
        ],
        "operators": operators,
        "watching": watching,
        "events": events,
        "thresholds": {
            "operator_attempts": MIN_OPERATOR_ATTEMPTS,
            "operator_devices": MIN_OPERATOR_SESSIONS,
            "protocol_attempts": MIN_PROTOCOL_ATTEMPTS,
            "ok_min_pct": OK_MIN_PCT,
            "partial_min_pct": PARTIAL_MIN_PCT,
        },
    }


def overview(db: OrmSession) -> dict:
    """Сводка с кэшем на CACHE_SECONDS — то, что отдаёт публичная ручка."""
    now = time.monotonic()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
        data = build(db)
        _cache["data"] = data
        _cache["at"] = now
        return data


def forget() -> None:
    """Сбросить кэш — для тестов."""
    with _cache_lock:
        _cache["data"] = None
        _cache["at"] = 0.0
