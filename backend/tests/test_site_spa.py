"""
Раздача сайта-одностраничника.

Отдельный модуль: SPA-режим включается настройкой на старте приложения, и
проверять его надо на своём экземпляре, а не на общем клиенте из test_api.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def spa(tmp_path_factory):
    site = tmp_path_factory.mktemp("site")
    (site / "index.html").write_text("<!doctype html><title>SPA</title>", encoding="utf-8")
    (site / "assets").mkdir()
    (site / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    previous = {k: os.environ.get(k) for k in ("PANEL_SITE_DIR", "PANEL_SITE_SPA")}
    os.environ["PANEL_SITE_DIR"] = str(site)
    os.environ["PANEL_SITE_SPA"] = "1"

    # Настройки кэшируются, а маршруты объявляются при импорте main — поэтому
    # сбрасываем кэш и перечитываем модуль целиком.
    from app import config

    config.settings.cache_clear()
    from app import main as main_module

    main_module = importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        yield client

    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config.settings.cache_clear()
    importlib.reload(main_module)


def test_client_route_returns_index(spa):
    """По прямой ссылке на /account должен приходить index.html, а не 404."""
    r = spa.get("/account")
    assert r.status_code == 200
    assert "SPA" in r.text


def test_existing_file_is_served(spa):
    r = spa.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_api_still_answers_json(spa):
    """
    Маршрут-перехватчик не должен съедать API.

    Он объявлен последним и ловит всё подряд, поэтому проверяем, что /api
    по-прежнему отвечает своим, а не индексом сайта.
    """
    r = spa.get("/api/v1/version", params={"platform": "windows", "current": "1.0.0"})
    assert r.status_code == 200
    assert "update_available" in r.json()

    assert spa.get("/healthz").json() == {"status": "ok"}


def test_legacy_pages_redirect(spa):
    """
    Адреса старого сайта разошлись по установленным приложениям.

    В 1.0.18 ссылки ведут на /faq.html и /privacy.html — после переезда они
    обязаны работать, иначе кнопки в приложении у людей ведут в никуда.
    """
    for old, new in (("/faq.html", "/faq"), ("/privacy.html", "/privacy"), ("/offer.html", "/terms")):
        r = spa.get(old, follow_redirects=False)
        assert r.status_code == 301, old
        assert r.headers["location"] == new


def test_path_traversal_is_refused(spa):
    """Выход за каталог сайта отдаёт индекс, а не файл с секретами."""
    r = spa.get("/../backend/.env")
    assert r.status_code == 200
    assert "SPA" in r.text
