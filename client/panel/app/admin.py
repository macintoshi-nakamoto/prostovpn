"""Веб-интерфейс панели: пользователи, серверы, подписки, деньги."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import services
from .config import settings
from .db import get_db
from .models import Admin, Payment, Provisioning, Server, Session, User
from .provisioning import build_vpn_key, config_for
from .security import hash_password, verify_password

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

COOKIE = "panel_session"
_COOKIE_TTL = dt.timedelta(days=7)


# --- вход в панель -----------------------------------------------------------


def _sign(value: str) -> str:
    mac = hmac.new(settings().secret_key.encode(), value.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def _make_cookie(admin_id: int) -> str:
    expires = int((services.utcnow() + _COOKIE_TTL).timestamp())
    payload = f"{admin_id}:{expires}"
    return f"{payload}:{_sign(payload)}"


def _read_cookie(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        admin_id, expires, signature = raw.rsplit(":", 2)
    except ValueError:
        return None
    payload = f"{admin_id}:{expires}"
    # Сравнение постоянного времени: иначе подпись подбирается побайтно
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    if int(expires) < services.utcnow().timestamp():
        return None
    return int(admin_id)


def current_admin(request: Request, db: OrmSession = Depends(get_db)) -> Admin:
    admin_id = _read_cookie(request.cookies.get(COOKIE))
    admin = db.get(Admin, admin_id) if admin_id else None
    if admin is None:
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return admin


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: OrmSession = Depends(get_db),
):
    admin = db.scalar(select(Admin).where(Admin.login == login.strip()))
    if admin is None or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE, _make_cookie(admin.id), httponly=True, samesite="lax", max_age=int(_COOKIE_TTL.total_seconds())
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


# --- сводка ------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "totals": services.dashboard_totals(db),
            "daily": services.revenue_series(db, days=30),
            "monthly": services.revenue_by_month(db, months=12),
            "yearly": services.revenue_by_year(db),
            "recent_sessions": list(
                db.scalars(select(Session).order_by(Session.last_seen_at.desc()).limit(10))
            ),
        },
    )


# --- пользователи ------------------------------------------------------------


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)):
    users = list(db.scalars(select(User).order_by(User.created_at.desc())))
    return templates.TemplateResponse(
        request,
        "users.html",
        {"users": users, "now": services.utcnow(), "flash": request.query_params.get("flash")},
    )


@router.post("/users")
def users_create(
    login: str = Form(...),
    password: str = Form(...),
    days: int = Form(30),
    plan: str = Form("basic"),
    note: str = Form(""),
    amount: str = Form(""),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
):
    try:
        user, warnings = services.create_user(
            db, login=login, password=password, days=days, plan=plan, note=note or None
        )
        # Сразу занесённая оплата избавляет от второго шага при заведении
        if amount.strip():
            services.add_payment(db, amount=_money(amount), user=user, method="вручную")
    except services.PanelError as exc:
        return RedirectResponse(f"/users?flash={exc}", status_code=303)

    message = f"Создан {user.login}"
    if warnings:
        message += ". Ключи не выданы: " + "; ".join(warnings)
    return RedirectResponse(f"/users/{user.id}?flash={message}", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
def user_page(
    user_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "нет такого пользователя")

    by_server = {key.server_id: key for key in user.keys if key.revoked_at is None}
    rows = []
    for server in services.active_servers(db):
        config = config_for(server, by_server.get(server.id))
        rows.append(
            {
                "server": server,
                "config": config,
                "key": build_vpn_key(server.host, config, server.port) if config else None,
            }
        )

    return templates.TemplateResponse(
        request,
        "user.html",
        {
            "user": user,
            "rows": rows,
            "now": services.utcnow(),
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/users/{user_id}/subscription")
def user_extend(
    user_id: int,
    days: int = Form(30),
    plan: str = Form("basic"),
    amount: str = Form(""),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "нет такого пользователя")
    services.grant_subscription(db, user, days=days, plan=plan)
    if amount.strip():
        try:
            services.add_payment(db, amount=_money(amount), user=user, method="вручную")
        except services.PanelError as exc:
            return RedirectResponse(f"/users/{user_id}?flash={exc}", status_code=303)
    # Продление могло вернуть доступ — досоздаём ключи
    if not user.is_active:
        user.is_active = True
        db.commit()
    services.ensure_keys(db, user)
    return RedirectResponse(f"/users/{user_id}?flash=Подписка продлена на {days} дн.", status_code=303)


@router.post("/users/{user_id}/password")
def user_password(
    user_id: int,
    password: str = Form(...),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "нет такого пользователя")
    if len(password) < 4:
        return RedirectResponse(f"/users/{user_id}?flash=Пароль короче четырёх символов", status_code=303)
    user.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse(f"/users/{user_id}?flash=Пароль изменён", status_code=303)


@router.post("/users/{user_id}/revoke")
def user_revoke(
    user_id: int, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "нет такого пользователя")
    problems = services.revoke_access(db, user)
    message = "Доступ отключён" + ("; не убрано: " + "; ".join(problems) if problems else "")
    return RedirectResponse(f"/users/{user_id}?flash={message}", status_code=303)


# --- серверы -----------------------------------------------------------------


@router.get("/servers", response_class=HTMLResponse)
def servers_page(request: Request, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)):
    servers = list(db.scalars(select(Server).order_by(Server.sort_order, Server.id)))
    return templates.TemplateResponse(
        request,
        "servers.html",
        {"servers": servers, "flash": request.query_params.get("flash")},
    )


@router.post("/servers")
def servers_create(
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(51820),
    country: str = Form(""),
    country_en: str = Form(""),
    city: str = Form(""),
    city_en: str = Form(""),
    country_code: str = Form(""),
    provisioning: str = Form("shared"),
    shared_config: str = Form(""),
    awg_template: str = Form(""),
    ssh_host: str = Form(""),
    ssh_port: int = Form(22),
    ssh_user: str = Form(""),
    ssh_password: str = Form(""),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
):
    mode = Provisioning(provisioning)
    if mode == Provisioning.SHARED and not shared_config.strip():
        return RedirectResponse("/servers?flash=Для общего ключа нужен сам конфиг", status_code=303)
    if mode == Provisioning.SSH and not (ssh_host.strip() and ssh_user.strip() and awg_template.strip()):
        return RedirectResponse(
            "/servers?flash=Для автогенерации нужны доступ по SSH и шаблон конфига", status_code=303
        )

    server = Server(
        name=name.strip(),
        host=host.strip(),
        port=port,
        country=country.strip() or None,
        country_en=country_en.strip() or None,
        city=city.strip() or None,
        city_en=city_en.strip() or None,
        country_code=(country_code.strip() or None),
        provisioning=mode,
        shared_config=shared_config.strip() or None,
        awg_template=awg_template.strip() or None,
        ssh_host=ssh_host.strip() or None,
        ssh_port=ssh_port,
        ssh_user=ssh_user.strip() or None,
        ssh_password=ssh_password or None,
    )
    db.add(server)
    db.commit()

    # Новый сервер должен появиться у всех — досоздаём ключи сразу, не
    # дожидаясь, пока каждый откроет приложение.
    warnings: list[str] = []
    for user in db.scalars(select(User).where(User.is_active.is_(True))):
        warnings += services.ensure_keys(db, user)

    message = f"Сервер «{server.name}» добавлен"
    if warnings:
        message += ". Часть ключей не выдана: " + "; ".join(sorted(set(warnings))[:3])
    return RedirectResponse(f"/servers?flash={message}", status_code=303)


@router.post("/servers/{server_id}/toggle")
def server_toggle(
    server_id: int, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "нет такого сервера")
    server.is_active = not server.is_active
    db.commit()
    state = "включён" if server.is_active else "выключен"
    return RedirectResponse(f"/servers?flash=Сервер «{server.name}» {state}", status_code=303)


@router.post("/servers/{server_id}/delete")
def server_delete(
    server_id: int, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "нет такого сервера")
    name = server.name
    db.delete(server)
    db.commit()
    return RedirectResponse(f"/servers?flash=Сервер «{name}» удалён", status_code=303)


# --- деньги ------------------------------------------------------------------


@router.get("/payments", response_class=HTMLResponse)
def payments_page(request: Request, db: OrmSession = Depends(get_db), _: Admin = Depends(current_admin)):
    return templates.TemplateResponse(
        request,
        "payments.html",
        {
            "payments": list(db.scalars(select(Payment).order_by(Payment.paid_at.desc()).limit(200))),
            "users": list(db.scalars(select(User).order_by(User.login))),
            "totals": services.dashboard_totals(db),
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/payments")
def payments_create(
    amount: str = Form(...),
    user_id: str = Form(""),
    method: str = Form(""),
    comment: str = Form(""),
    db: OrmSession = Depends(get_db),
    _: Admin = Depends(current_admin),
):
    user = db.get(User, int(user_id)) if user_id.strip() else None
    try:
        services.add_payment(
            db, amount=_money(amount), user=user, method=method or None, comment=comment or None
        )
    except services.PanelError as exc:
        return RedirectResponse(f"/payments?flash={exc}", status_code=303)
    return RedirectResponse("/payments?flash=Платёж записан", status_code=303)


def _money(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", ".").strip())
    except InvalidOperation as exc:
        raise services.PanelError(f"не похоже на сумму: {raw}") from exc
