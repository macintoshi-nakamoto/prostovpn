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
    r = spa.get("/account")
    assert r.status_code == 200
    assert "SPA" in r.text


def test_existing_file_is_served(spa):
    r = spa.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_api_still_answers_json(spa):
    r = spa.get("/api/v1/version", params={"platform": "windows", "current": "1.0.0"})
    assert r.status_code == 200
    assert "update_available" in r.json()

    assert spa.get("/healthz").json() == {"status": "ok"}


def test_legacy_pages_redirect(spa):
    for old, new in (("/faq.html", "/faq"), ("/privacy.html", "/privacy"), ("/offer.html", "/terms")):
        r = spa.get(old, follow_redirects=False)
        assert r.status_code == 301, old
        assert r.headers["location"] == new


def test_path_traversal_is_refused(spa):
    r = spa.get("/../backend/.env")
    assert r.status_code == 200
    assert "SPA" in r.text
