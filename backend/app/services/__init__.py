"""
Бизнес-логика панели, разложенная по предметным областям.

Модуль собирает публичные имена в одно место, чтобы вызывающий код писал
`services.create_user(...)`, не помня, в каком именно файле это лежит.
"""

from __future__ import annotations

from . import billing_webhook, credentials, delivery, diagnostics, orders, ratelimit
from .diagnostics import can_serve, check as check_server
from .auth import (
    LoginThrottled,
    admin_session_for_token,
    authenticate,
    authenticate_admin,
    revoke_admin_session,
    session_for_token,
    touch,
)
from .billing import (
    add_payment,
    calendar_month,
    dashboard_totals,
    grant_subscription,
    revenue_by_month,
    revenue_by_year,
    revenue_series,
    revenue_summary,
)
from .errors import PanelError
from .keys import active_servers, ensure_keys, issue_key, revoke_key
from .orders import (
    OrderError,
    create_order,
    expire_stale,
    fulfil,
    public_plans,
    refund,
    site_plans,
)
from .releases import check as check_update, latest_for, upsert as upsert_release
from .traffic import enforce_access, sync_server_traffic, sync_all_traffic
from .users import (
    block_user,
    create_user,
    find_by_email,
    generate_credentials,
    reveal_password,
    revoke_access,
    set_password,
    set_traffic_limit,
    reset_traffic,
    set_user_active,
    unblock_user,
)
from ..models import utcnow

__all__ = [
    "PanelError",
    "utcnow",
    # auth
    "LoginThrottled",
    "authenticate",
    "authenticate_admin",
    "admin_session_for_token",
    "revoke_admin_session",
    "session_for_token",
    "touch",
    "ratelimit",
    # users
    "create_user",
    "generate_credentials",
    "reveal_password",
    "set_password",
    "set_user_active",
    "block_user",
    "unblock_user",
    "set_traffic_limit",
    "reset_traffic",
    "revoke_access",
    "credentials",
    # keys
    "active_servers",
    "ensure_keys",
    "issue_key",
    "revoke_key",
    # проверка узлов
    "diagnostics",
    "can_serve",
    "check_server",
    # billing
    "add_payment",
    "grant_subscription",
    "revenue_series",
    "revenue_by_month",
    "revenue_by_year",
    "revenue_summary",
    "calendar_month",
    "dashboard_totals",
    # заказы и оплата с сайта
    "orders",
    "billing_webhook",
    "delivery",
    "OrderError",
    "create_order",
    "find_by_email",
    "expire_stale",
    "fulfil",
    "public_plans",
    "site_plans",
    "refund",
    # версии приложения
    "check_update",
    "latest_for",
    "upsert_release",
    # traffic
    "sync_server_traffic",
    "sync_all_traffic",
    "enforce_access",
]
