"""
Телеметрия: «что изменилось», сводка админам и тревога о просадке.

Отчёты кладём прямо в базу с нужным временем — сегодня хорошо, вчера
плохо или наоборот — и смотрим, что насчитается и кому уйдёт.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import delete

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import ConnectReport, User, utcnow
from app.security import hash_password
from app.services import alerts, asn, telemetry


@pytest.fixture(scope="module", autouse=True)
def schema():
    init_db()


@pytest.fixture()
def clean():
    with SessionLocal() as db:
        db.execute(delete(ConnectReport))
        db.commit()
    telemetry._drop_alerted.clear()
    yield
    with SessionLocal() as db:
        db.execute(delete(ConnectReport))
        db.commit()


def _fill(db, *, operator: str, protocol: str, hours_ago: float, ok: int, fail: int) -> None:
    at = utcnow() - dt.timedelta(hours=hours_ago)
    for i in range(ok + fail):
        db.add(
            ConnectReport(
                platform="android",
                app_version="1.4.0",
                network_kind="cellular",
                operator=operator,
                protocol=protocol,
                ok=i < ok,
                stage="handshake",
                duration_ms=1200,
                attempts=1,
                error=None if i < ok else "no handshake",
                created_at=at,
            )
        )
    db.commit()


def test_нормализация_операторов():
    assert telemetry.normalize_operator("MTS RUS") == "МТС"
    assert telemetry.normalize_operator("Mobile TeleSystems PJSC") == "МТС"
    assert telemetry.normalize_operator("PJSC VimpelCom") == "Билайн"
    assert telemetry.normalize_operator("T2 Mobile LLC") == "Tele2"
    assert telemetry.normalize_operator("Rostelecom") == "Ростелеком"
    assert telemetry.normalize_operator("Some Small ISP") == "Some Small ISP"
    assert telemetry.normalize_operator("") is None
    assert asn.pretty("PJSC ROSTELECOM") == "Rostelecom"
    assert asn.pretty("MegaFon") == "MegaFon"


def test_изменения_сегодня_против_вчера(clean):
    with SessionLocal() as db:
        _fill(db, operator="МТС", protocol="vless", hours_ago=30, ok=19, fail=1)   # вчера 95 %
        _fill(db, operator="МТС", protocol="vless", hours_ago=2, ok=6, fail=14)    # сегодня 30 %
        _fill(db, operator="МТС", protocol="awg", hours_ago=30, ok=18, fail=2)
        _fill(db, operator="МТС", protocol="awg", hours_ago=2, ok=19, fail=1)
        _fill(db, operator="Wi-Fi", protocol="awg", hours_ago=2, ok=3, fail=0)     # мало — не статистика
        data = telemetry.changes(db, 24)

    assert data["reports"] == 43 and data["prev_reports"] == 40
    first = data["items"][0]
    assert (first["operator"], first["protocol"]) == ("МТС", "vless")
    assert first["ok_pct"] == 30.0 and first["prev_ok_pct"] == 95.0 and first["delta"] == -65.0
    assert all(i["operator"] != "Wi-Fi" for i in data["items"]), "три попытки — не строка в сводке"
    protos = {p["protocol"]: p for p in data["protocols"]}
    # awg сегодня: 19 + 3 (Wi-Fi) удачных из 23 → 95.7 % против 90 % вчера
    assert protos["vless"]["delta"] == -65.0 and protos["awg"]["delta"] == 5.7
    assert data["errors"][0] == {"error": "no handshake", "count": 15}


def test_сводка_текстом(clean):
    with SessionLocal() as db:
        _fill(db, operator="МТС", protocol="vless", hours_ago=30, ok=19, fail=1)
        _fill(db, operator="МТС", protocol="vless", hours_ago=2, ok=6, fail=14)
        text = telemetry.digest_text(db, "https://prostovpn.cc")
    assert "Просело" in text and "МТС · Reality: 30.0% (было 95.0%)" in text
    assert "/admin/telemetry" in text


def test_тревога_о_просадке_только_админам(clean, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111, 222")
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(alerts.telegram, "send", lambda chat_id, text: sent.append((chat_id, text)))
    with SessionLocal() as db:
        db.add(User(login="tele-victim", password_hash=hash_password("x"), telegram_id=999779))
        db.commit()
        _fill(db, operator="Билайн", protocol="awg", hours_ago=10, ok=28, fail=2)  # сутки до: 93 %
        _fill(db, operator="Билайн", protocol="awg", hours_ago=1, ok=3, fail=12)   # последние 3 ч: 20 %
        _fill(db, operator="Билайн", protocol="vless", hours_ago=1, ok=9, fail=1)  # для контекста
        assert telemetry.check_drops(db) == ["Билайн/awg"]
        assert telemetry.check_drops(db) == [], "повтор в пределах паузы не шлём"
    assert sorted(chat for chat, _ in sent) == [111, 222]
    assert 999779 not in {chat for chat, _ in sent}
    assert "Билайн · AmneziaWG" in sent[0][1] and "Reality 90.0%" in sent[0][1]
    with SessionLocal() as db:
        victim = db.query(User).filter(User.login == "tele-victim").one_or_none()
        if victim is not None:
            db.delete(victim)
            db.commit()


def test_мало_попыток_не_тревога(clean, monkeypatch):
    monkeypatch.setattr(settings(), "alert_chat_ids", "111")
    sent: list = []
    monkeypatch.setattr(alerts.telegram, "send", lambda chat_id, text: sent.append((chat_id, text)))
    with SessionLocal() as db:
        _fill(db, operator="Tele2", protocol="awg", hours_ago=10, ok=30, fail=0)
        _fill(db, operator="Tele2", protocol="awg", hours_ago=1, ok=1, fail=5)
        assert telemetry.check_drops(db) == []
    assert sent == []


def test_провайдер_по_адресу_без_базы():
    # Базы в тестах нет — просто None, без исключений и без сети.
    assert asn.isp_name("8.8.8.8") is None
    assert asn.isp_name("10.0.0.1") is None
    assert asn.isp_name("мусор") is None
