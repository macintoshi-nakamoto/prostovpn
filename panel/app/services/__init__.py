"""
Бизнес-логика панели, разложенная по предметным областям.

Модуль собирает публичные имена в одно место, чтобы вызывающий код писал
`services.create_user(...)`, не помня, в каком именно файле это лежит.
"""

from __future__ import annotations

from .auth import (
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
from .releases import check as check_update, latest_for, upsert as upsert_release
from .traffic import sync_server_traffic, sync_all_traffic
from .users import (
    block_user,
    create_user,
    generate_credentials,
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
    "authenticate",
    "authenticate_admin",
    "admin_session_for_token",
    "revoke_admin_session",
    "session_for_token",
    "touch",
    # users
    "create_user",
    "generate_credentials",
    "set_password",
    "set_user_active",
    "block_user",
    "unblock_user",
    "set_traffic_limit",
    "reset_traffic",
    "revoke_access",
    # keys
    "active_servers",
    "ensure_keys",
    "issue_key",
    "revoke_key",
    # billing
    "add_payment",
    "grant_subscription",
    "revenue_series",
    "revenue_by_month",
    "revenue_by_year",
    "revenue_summary",
    "calendar_month",
    "dashboard_totals",
    # версии приложения
    "check_update",
    "latest_for",
    "upsert_release",
    # traffic
    "sync_server_traffic",
    "sync_all_traffic",
]
