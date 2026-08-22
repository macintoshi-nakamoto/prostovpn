"""
Админское API веб-панели: /api/admin/*.

Отдельно от /api/v1, которым пользуются приложения: у них разные читатели,
разные токены и разный темп изменений.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    audit,
    auth,
    endpoints,
    finance,
    keys,
    orders,
    plans,
    recurring,
    referrals,
    releases,
    servers,
    transfers,
    tunnel,
    users,
)

router = APIRouter(prefix="/api/admin")

router.include_router(auth.router)
router.include_router(users.router)
router.include_router(servers.router)
router.include_router(endpoints.router)
router.include_router(keys.router)
router.include_router(plans.router)
router.include_router(releases.router)
router.include_router(tunnel.router)
router.include_router(finance.router)
router.include_router(orders.router)
router.include_router(orders.deliveries)
router.include_router(orders.events)
router.include_router(recurring.router)
router.include_router(referrals.router)
router.include_router(transfers.router)
router.include_router(audit.router)

__all__ = ["router"]
