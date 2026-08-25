from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Order, OrderStatus, Provisioning, Server
from app.payments import cryptocloud
from app.services import create_order

SECRET = "test-cryptocloud-secret"
WEBHOOK = "/api/v1/billing/webhook/cryptocloud"


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Server).limit(1)) is None:
            db.add(
                Server(
                    name="test-cc",
                    country="Нидерланды",
                    country_code="NL",
                    host="10.20.30.2",
                    provisioning=Provisioning.SHARED,
                    shared_config="[Interface]\nAddress = 10.0.0.3/32\n",
                )
            )
            db.commit()
    with TestClient(app) as c:
        yield c


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


@pytest.fixture()
def cc(monkeypatch):
    state: dict = {"invoices": {}, "next_uuid": "INV-1"}

    def post(url: str, **kwargs):
        if url.endswith("/invoice/create"):
            uuid = str(state["next_uuid"])
            state["invoices"][uuid] = {
                "uuid": uuid,
                "order_id": kwargs["json"]["order_id"],
                "status": "created",
                "amount_in_fiat": kwargs["json"]["amount"],
                "fiat_currency": kwargs["json"]["currency"],
            }
            return FakeResponse(
                {
                    "status": "success",
                    "result": {"uuid": uuid, "link": "https://pay.cc/" + uuid},
                }
            )
        if url.endswith("/invoice/merchant/info"):
            wanted = kwargs["json"]["uuids"][0]
            found = state["invoices"].get(wanted)
            return FakeResponse({"status": "success", "result": [found] if found else []})
        raise AssertionError("неожиданный запрос к " + url)

    monkeypatch.setattr(cryptocloud.httpx, "post", post)
    return state


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(claims: dict, secret: str = SECRET) -> str:
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"exp": int(time.time()) + 600, **claims}).encode())
    sign = hmac.new(secret.encode(), (head + "." + body).encode(), hashlib.sha256).digest()
    return head + "." + body + "." + _b64(sign)


def _notify(client, form: dict, as_json: bool = False):
    if as_json:
        return client.post(
            WEBHOOK,
            content=json.dumps(form).encode(),
            headers={"Content-Type": "application/json"},
        )
    return client.post(
        WEBHOOK,
        content=urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def _order(cc, email: str, uuid: str) -> tuple[str, int]:
    cc["next_uuid"] = uuid
    with SessionLocal() as db:
        order = create_order(db, plan_code="basic", email=email, provider_name="cryptocloud")
        assert order.redirect_url and uuid in order.redirect_url
        return order.id, order.amount_kopecks


def _settle(cc, uuid: str, status: str, fiat: float | None) -> None:
    invoice = cc["invoices"][uuid]
    invoice["status"] = status
    if fiat is None:
        invoice.pop("amount_in_fiat", None)
        invoice.pop("fiat_currency", None)
    else:
        invoice["amount_in_fiat"] = fiat


def _status(order_id: str) -> tuple[str, str | None]:
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        return order.status, order.failure_reason


def test_notification_without_token_is_rejected(client, cc):
    r = _notify(client, {"invoice_id": "INV-X", "status": "paid"})
    assert r.status_code == 403


def test_notification_with_foreign_signature_is_rejected(client, cc):
    forged = _token({"id": "INV-X"}, secret="чужой секрет")
    r = _notify(client, {"token": forged, "invoice_id": "INV-X"})
    assert r.status_code == 403


def test_form_that_disagrees_with_the_token_is_rejected(client, cc):
    r = _notify(client, {"token": _token({"id": "INV-A"}), "invoice_id": "INV-B"})
    assert r.status_code == 403


def test_json_body_is_understood(client, cc):
    order_id, kopecks = _order(cc, "cc-json@example.com", "INV-JSON")
    _settle(cc, "INV-JSON", "paid", kopecks / 100)

    r = _notify(client, {"token": _token({"id": "INV-JSON"})}, as_json=True)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "ok"
    assert _status(order_id)[0] == OrderStatus.PAID.value


def test_exact_amount_grants_access(client, cc):
    order_id, kopecks = _order(cc, "cc-exact@example.com", "INV-EXACT")
    _settle(cc, "INV-EXACT", "paid", kopecks / 100)

    r = _notify(client, {"token": _token({"id": "INV-EXACT"}), "invoice_id": "INV-EXACT"})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "ok"

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == OrderStatus.PAID.value
        assert order.user_id, "оплаченный заказ обязан завести учётку"


def test_overpaid_invoice_grants_access(client, cc):
    order_id, kopecks = _order(cc, "cc-over@example.com", "INV-OVER")
    _settle(cc, "INV-OVER", "overpaid", round(kopecks / 100 + 13.37, 2))

    r = _notify(client, {"token": _token({"id": "INV-OVER"}), "invoice_id": "INV-OVER"})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "ok"
    assert _status(order_id)[0] == OrderStatus.PAID.value


def test_underpaid_invoice_is_refused(client, cc):
    order_id, kopecks = _order(cc, "cc-under@example.com", "INV-UNDER")
    _settle(cc, "INV-UNDER", "paid", round(kopecks / 100 - 1, 2))

    r = _notify(client, {"token": _token({"id": "INV-UNDER"}), "invoice_id": "INV-UNDER"})
    assert r.status_code == 200, r.text

    status, reason = _status(order_id)
    assert status == OrderStatus.FAILED.value
    assert reason and "меньше цены" in reason


def test_invoice_without_fiat_amount_does_not_grant(client, cc):
    order_id, _ = _order(cc, "cc-nofiat@example.com", "INV-NOFIAT")
    _settle(cc, "INV-NOFIAT", "paid", None)

    r = _notify(client, {"token": _token({"id": "INV-NOFIAT"}), "invoice_id": "INV-NOFIAT"})
    assert r.status_code == 200, r.text
    assert _status(order_id)[0] != OrderStatus.PAID.value


def test_repeat_delivery_does_not_pay_twice(client, cc):
    order_id, kopecks = _order(cc, "cc-twice@example.com", "INV-TWICE")
    _settle(cc, "INV-TWICE", "paid", kopecks / 100)
    form = {"token": _token({"id": "INV-TWICE"}), "invoice_id": "INV-TWICE"}

    assert _notify(client, form).json()["result"] == "ok"
    again = _notify(client, form)
    assert again.status_code == 200
    assert again.json()["result"] in {"duplicate", "ok"}

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == OrderStatus.PAID.value
