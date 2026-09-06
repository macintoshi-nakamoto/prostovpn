"""
Карта блокировок (/api/v1/blocks, services/connectivity.py): сводка по
операторам из отчётов приложений — пороги, статусы, события, кэш.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import ConnectReport, Session as Sess, User, utcnow
from app.security import hash_password
from app.services import connectivity


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample():
    """Сутки телеметрии: МТС ломается на AmneziaWG, Билайн с перебоями,
    Ростелеком по Wi-Fi в порядке, Tele2 — один телефон (не статистика)."""
    now = utcnow()
    with SessionLocal() as db:
        db.execute(delete(ConnectReport))
        user = User(login="blocks-sample", password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        sessions = []
        for i in range(30):
            s = Sess(
                user_id=user.id,
                token_hash=f"blocks-sample-{i:02d}" + "0" * 46,
                platform="android",
                device_id=f"blocks-dev-{i}",
                expires_at=now + dt.timedelta(days=1),
            )
            db.add(s)
            sessions.append(s)
        db.flush()
        sid = [s.id for s in sessions]

        def report(operator, protocol, ok, hours_ago, session_id, kind="cellular"):
            db.add(
                ConnectReport(
                    user_id=user.id,
                    session_id=session_id,
                    platform="android",
                    network_kind=kind,
                    operator=operator,
                    protocol=protocol,
                    ok=ok,
                    created_at=now - dt.timedelta(hours=hours_ago),
                )
            )

        # МТС, 12 устройств: awg сейчас лежит (3 из 14), hy2 работает (10 из 10);
        # вчера awg работал (12 из 12) — это «падение» в событиях.
        for i in range(14):
            report("МТС", "awg", i < 3, 0.5 + i * 0.1, sid[i % 12])
        for i in range(10):
            report("МТС", "hy2", True, 1.0 + i * 0.1, sid[i % 12])
        for i in range(12):
            report("МТС", "awg", True, 30 + i * 0.5, sid[i % 12])
        # Билайн, 8 устройств: vless 10 из 12 за сутки, но не в последние 3 часа.
        for i in range(12):
            report("Билайн", "vless", i < 10, 5 + i, sid[12 + i % 8])
        # Ростелеком по Wi-Fi, 6 устройств, всё хорошо.
        for i in range(12):
            report("Ростелеком", "awg", True, 0.5 + i * 0.2, sid[20 + i % 6], kind="wifi")
        # Tele2 — один телефон, 15 попыток: на карту не попадает.
        for i in range(15):
            report("Tele2", "awg", True, 1 + i * 0.5, sid[29])
        db.commit()
        user_id = user.id
    connectivity.forget()
    yield now
    with SessionLocal() as db:
        db.execute(delete(ConnectReport))
        row = db.get(User, user_id)
        if row is not None:
            db.delete(row)
        db.commit()
    connectivity.forget()


def test_сводка_по_операторам(client, sample):
    with SessionLocal() as db:
        data = connectivity.build(db, now=sample)

    names = [o["name"] for o in data["operators"]]
    assert names == ["МТС", "Билайн", "Ростелеком"], "заблокированные первыми, один телефон — не оператор"
    assert "Tele2" in data["watching"] and "МегаФон" in data["watching"]

    mts = data["operators"][0]
    # В целом у МТС «перебои»: AmneziaWG лежит, но Hysteria2 работает — люди
    # подключаются, просто не первым способом. «Блокировка» — когда не
    # работает ничего.
    assert mts["kind"] == "cellular" and mts["status"] == "partial" and mts["basis"] == "now"
    assert mts["devices_day"] == 12 and mts["attempts_day"] == 24
    assert mts["best_now"] == "hy2"
    by_code = {p["code"]: p for p in mts["protocols"]}
    assert by_code["awg"]["status"] == "blocked" and by_code["awg"]["ok_pct_now"] < 30
    assert by_code["hy2"]["status"] == "ok" and by_code["hy2"]["ok_pct_now"] == 100.0
    assert by_code["awg"]["trend"] == "down" and by_code["awg"]["ok_pct_prev"] == 100.0
    assert len(mts["hourly"]) == 24 and mts["hourly"][-1]["attempts"] > 0

    beeline = data["operators"][1]
    assert beeline["status"] == "partial" and beeline["basis"] == "day"
    assert beeline["ok_pct_now"] is None and round(beeline["ok_pct_day"]) == 83

    rt = data["operators"][2]
    assert rt["kind"] == "wifi" and rt["status"] == "ok"

    drops = [e for e in data["events"] if e["kind"] == "drop"]
    assert drops and drops[0]["operator"] == "МТС" and drops[0]["protocol"] == "awg"

    s = data["summary"]
    assert s["operators"] == 3 and s["blocked"] == 0 and s["trouble"] == 2
    assert s["attempts_day"] == 14 + 10 + 12 + 12 + 15 and s["devices_day"] == 27
    assert s["platforms"] == ["android"]


def test_публичная_ручка_и_кэш(client, sample):
    r = client.get("/api/v1/blocks")
    assert r.status_code == 200, r.text
    assert "max-age=60" in r.headers.get("cache-control", "")
    body = r.json()
    assert body["summary"]["operators"] == 3
    assert body["operators"][0]["name"] == "МТС"
    assert body["updated_at"]

    # Кэш: новые строки за минуту не меняют ответ, сброс — меняет.
    with SessionLocal() as db:
        db.execute(delete(ConnectReport))
        db.commit()
    assert client.get("/api/v1/blocks").json()["summary"]["operators"] == 3
    connectivity.forget()
    assert client.get("/api/v1/blocks").json()["summary"]["operators"] == 0
