from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field

import aiohttp

from config.settings import config
from utils.logger import logger


CLIENT = "/api/v1"
ADMIN = "/api/admin"

TIMEOUT = aiohttp.ClientTimeout(total=25)

GB = 1024**3


class PanelError(RuntimeError):

    def __init__(self, message: str, *, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class PanelUnavailable(PanelError):
    pass


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    duration_days: int
    price_kopecks: int
    currency: str
    device_limit: int
    traffic_limit_bytes: int | None
    purchasable: bool
    server_limit: int = 0

    @property
    def rub(self) -> int:
        return self.price_kopecks // 100

    @property
    def stars(self) -> int:
        return max(1, round(self.rub * config.stars_rate))

    @property
    def traffic_gb(self) -> int | None:
        if self.traffic_limit_bytes is None:
            return None

        return round(self.traffic_limit_bytes / GB)


@dataclass(frozen=True)
class Session:
    token: str
    login: str
    expires_at: dt.datetime


@dataclass(frozen=True)
class Payment:
    amount: float
    currency: str
    comment: str | None
    paid_at: dt.datetime


@dataclass(frozen=True)
class IosKey:

    slot: int
    name: str
    server: str
    vpn_url: str
    is_connected: bool = False


@dataclass(frozen=True)
class TunnelFile:

    filename: str
    version: str | None
    size_bytes: int
    url: str


@dataclass(frozen=True)
class Account:
    login: str
    active: bool
    plan: str | None
    plan_title: str | None
    expires_at: dt.datetime | None
    days_left: int | None
    device_limit: int
    devices: int
    traffic_used_bytes: int
    traffic_limit_bytes: int | None
    payments: list[Payment] = field(default_factory=list)
    ios_keys: list[IosKey] = field(default_factory=list)
    ios_access: bool = False
    guide_url: str = ""

    @property
    def traffic_left_gb(self) -> float | None:
        if self.traffic_limit_bytes is None:
            return None

        return max(0, self.traffic_limit_bytes - self.traffic_used_bytes) / GB


@dataclass(frozen=True)
class Download:
    platform: str
    version: str
    url: str


_session: aiohttp.ClientSession | None = None
_admin_token: str = ""
_admin_expires: dt.datetime | None = None


async def _http() -> aiohttp.ClientSession:
    global _session

    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=TIMEOUT)

    return _session


async def close() -> None:
    global _session

    if _session and not _session.closed:
        await _session.close()

    _session = None


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None

    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))

    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(dt.timezone.utc).replace(tzinfo=None)

    return stamp


async def _request(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    token: str | None = None,
) -> dict | list:
    http = await _http()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        async with http.request(
            method,
            f"{config.panel_url}{path}",
            json=payload,
            headers=headers,
        ) as response:
            try:
                body = await response.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                body = None

                if response.status < 400:
                    raise PanelUnavailable("панель ответила непонятным")

            if response.status >= 400:
                detail = ""

                if isinstance(body, dict):
                    detail = str(body.get("detail") or "")

                raise PanelError(
                    detail or f"панель вернула {response.status}",
                    status=response.status,
                    code=response.headers.get("X-Error-Code", ""),
                )

            return body
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        logger.warning("панель недоступна: %s %s — %s", method, path, error)
        raise PanelUnavailable("панель недоступна") from error


def _plan(row: dict) -> Plan:
    return Plan(
        code=row["code"],
        title=row["title"],
        duration_days=row["duration_days"],
        price_kopecks=row["price_kopecks"],
        currency=row.get("currency", "RUB"),
        device_limit=row.get("device_limit", 1),
        traffic_limit_bytes=row.get("traffic_limit_bytes"),
        purchasable=row.get("purchasable", False),
        server_limit=row.get("server_limit") or 0,
    )


async def plans() -> list[Plan]:
    rows = await _request("GET", f"{CLIENT}/plans")

    return [_plan(row) for row in rows if row.get("purchasable")]


async def plan_by_code(code: str) -> Plan | None:
    for plan in await plans():
        if plan.code == code:
            return plan

    return None


async def login(user_login: str, password: str) -> Session:
    body = await _request(
        "POST",
        f"{CLIENT}/login",
        payload={
            "login": user_login,
            "password": password,
            "platform": "telegram",
            "app_version": config.brand_version,
        },
    )

    return Session(
        token=body["token"],
        login=body["account"]["login"],
        expires_at=_parse_time(body["expires_at"]),
    )


async def logout(token: str) -> None:
    try:
        await _request("POST", f"{CLIENT}/logout", token=token)
    except PanelError as error:
        logger.info("выход из панели не удался: %s", error)


async def account(token: str) -> Account:
    body = await _request("GET", f"{CLIENT}/account", token=token)
    ios = body.get("ios") or {}

    return Account(
        login=body["login"],
        active=body["active"],
        plan=body.get("plan"),
        plan_title=body.get("plan_title"),
        expires_at=_parse_time(body.get("expires_at")),
        days_left=body.get("days_left"),
        device_limit=body.get("device_limit", 0),
        devices=len(body.get("devices", [])),
        traffic_used_bytes=body.get("traffic_used_bytes", 0),
        traffic_limit_bytes=body.get("traffic_limit_bytes"),
        payments=[
            Payment(
                amount=row["amount"],
                currency=row.get("currency", "RUB"),
                comment=row.get("comment"),
                paid_at=_parse_time(row["paid_at"]),
            )
            for row in body.get("payments", [])
        ],
        ios_access=bool(ios.get("available")),
        guide_url=ios.get("guide_url") or f"{config.site_url.rstrip('/')}/guide",
        ios_keys=[
            IosKey(
                slot=row.get("slot", 0),
                name=row.get("name", ""),
                server=row.get("server", ""),
                vpn_url=row["vpn_url"],
                is_connected=bool(row.get("is_connected")),
            )
            for row in ios.get("keys", [])
            if row.get("vpn_url")
        ],
    )


async def change_password(token: str, current: str, fresh: str) -> None:
    await _request(
        "POST",
        f"{CLIENT}/account/password",
        payload={"current_password": current, "new_password": fresh},
        token=token,
    )


async def tunnel_file() -> TunnelFile | None:
    body = await _request("GET", f"{CLIENT}/tunnel-file")

    if not isinstance(body, dict) or not body.get("available"):
        return None

    return TunnelFile(
        filename=body.get("filename") or "prostovpn-ru-sites.json",
        version=body.get("version"),
        size_bytes=body.get("size_bytes") or 0,
        url=body.get("url") or f"{CLIENT}/tunnel-file/download",
    )


async def tunnel_file_bytes(url: str) -> bytes:
    http = await _http()
    address = url if url.startswith("http") else f"{config.panel_url}{url}"

    try:
        async with http.get(address) as response:
            if response.status >= 400:
                raise PanelError(f"файл недоступен ({response.status})", status=response.status)

            return await response.read()
    except aiohttp.ClientError as error:
        logger.warning("файл списка не забрался: %s", error)
        raise PanelUnavailable("панель недоступна") from error


async def downloads() -> list[Download]:
    rows = await _request("GET", f"{CLIENT}/downloads")

    return [
        Download(platform=row["platform"], version=row["version"], url=row["url"])
        for row in rows
    ]


async def _admin() -> str:
    global _admin_token, _admin_expires

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    if _admin_token and _admin_expires and _admin_expires > now + dt.timedelta(minutes=5):
        return _admin_token

    if not config.panel_admin_login or not config.panel_admin_password:
        raise PanelError("доступ к панели не настроен")

    body = await _request(
        "POST",
        f"{ADMIN}/login",
        payload={
            "login": config.panel_admin_login,
            "password": config.panel_admin_password,
        },
    )

    _admin_token = body["token"]
    _admin_expires = _parse_time(body.get("expires_at")) or now + dt.timedelta(hours=6)

    return _admin_token


async def _admin_request(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
) -> dict | list:
    global _admin_token

    try:
        return await _request(method, path, payload=payload, token=await _admin())
    except PanelError as error:
        if error.status not in (401, 403):
            raise

        _admin_token = ""

        return await _request(method, path, payload=payload, token=await _admin())


async def create_account(user_login: str, password: str) -> None:
    await _admin_request(
        "POST",
        f"{ADMIN}/users",
        payload={
            "login": user_login,
            "password": password,
            "plan_code": config.signup_plan,
            "note": "регистрация в Telegram-боте",
        },
    )


async def find_user_id(user_login: str) -> int | None:
    rows = await _admin_request("GET", f"{ADMIN}/users?q={user_login}")

    for row in rows:
        if row["login"].lower() == user_login.lower():
            return row["id"]

    return None


async def grant_days(user_login: str, days: int, reason: str = "промо") -> bool:
    user_id = await find_user_id(user_login)

    if user_id is None:
        return False

    await _admin_request(
        "POST",
        f"{ADMIN}/referrals/bonus/{user_id}",
        payload={"days": days, "reason": reason},
    )

    return True


async def extend(
    user_login: str,
    plan: Plan,
    method: str,
    external_id: str | None = None,
    provider: str | None = None,
    payment_method: str | None = None,
    quantity: int = 1,
) -> None:
    user_id = await find_user_id(user_login)

    if user_id is None:
        raise PanelError(f"учётка «{user_login}» не найдена")

    await _admin_request(
        "POST",
        f"{ADMIN}/users/{user_id}/extend",
        payload={
            "plan_code": plan.code,
            "days": plan.duration_days * quantity,
            "price": plan.rub * quantity,
            "quantity": quantity,
            "register_payment": True,
            "method": method,
            "external_id": external_id,
            "order_provider": provider,
            "payment_method": payment_method,
        },
    )


@dataclass(frozen=True)
class Transfer:

    days: int
    direction: str
    counterpart: str
    created_at: dt.datetime | None


async def transfer_days(user_login: str, recipient: str, days: int) -> Transfer:
    user_id = await find_user_id(user_login)

    if user_id is None:
        raise PanelError(f"учётка «{user_login}» не найдена")

    body = await _admin_request(
        "POST",
        f"{ADMIN}/transfers",
        payload={
            "fromUserId": user_id,
            "recipient": recipient,
            "days": days,
            "note": "перевод из Telegram",
            "origin": "bot",
        },
    )

    return Transfer(
        days=body["days"],
        direction="sent",
        counterpart=body["toPublicId"],
        created_at=_parse_time(body.get("createdAt")),
    )


async def transfers(user_login: str, limit: int = 10) -> list[Transfer]:
    user_id = await find_user_id(user_login)

    if user_id is None:
        return []

    rows = await _admin_request("GET", f"{ADMIN}/transfers?user_id={user_id}&limit={limit}")
    result = []

    for row in rows:
        outgoing = row["fromId"] == user_id
        result.append(
            Transfer(
                days=row["days"],
                direction="sent" if outgoing else "received",
                counterpart=row["toPublicId"] if outgoing else row["fromPublicId"],
                created_at=_parse_time(row.get("createdAt")),
            )
        )

    return result


@dataclass(frozen=True)
class Referrals:

    invited: int = 0
    purchased: int = 0
    days: int = 0
    pending: int = 0
    join_days: int = 2
    purchase_days: int = 5


def _referrals(body: dict) -> Referrals:
    return Referrals(
        invited=body.get("invited", 0),
        purchased=body.get("purchased", 0),
        days=body.get("days", 0),
        pending=body.get("pending", 0),
        join_days=body.get("join_days", 2),
        purchase_days=body.get("purchase_days", 5),
    )


async def referral_stats(telegram_id: int) -> Referrals:
    body = await _admin_request("GET", f"{ADMIN}/referrals/stats/{telegram_id}")

    return _referrals(body)


async def referral_invite(
    inviter_telegram_id: int,
    invited_telegram_id: int,
    invited_login: str | None = None,
) -> Referrals:
    body = await _admin_request(
        "POST",
        f"{ADMIN}/referrals/invite",
        payload={
            "inviter_telegram_id": inviter_telegram_id,
            "invited_telegram_id": invited_telegram_id,
            "invited_login": invited_login,
        },
    )

    return _referrals(body)


async def referral_link_account(telegram_id: int, user_login: str) -> None:
    try:
        await _admin_request(
            "POST",
            f"{ADMIN}/referrals/link",
            payload={"telegram_id": telegram_id, "login": user_login},
        )
    except PanelError as error:
        logger.info("связка telegram↔учётка не прошла: %s", error)


@dataclass(frozen=True)
class PaymentLink:
    order_id: str
    url: str
    amount_kopecks: int
    currency: str

    @property
    def rub(self) -> int:
        return self.amount_kopecks // 100


@dataclass(frozen=True)
class Recurring:

    status: str | None = None
    plan_code: str | None = None
    plan_title: str | None = None
    amount_kopecks: int | None = None
    currency: str | None = None
    interval: str | None = None
    next_charge_at: dt.datetime | None = None
    last_charge_error: str | None = None
    redirect_url: str | None = None

    @property
    def rub(self) -> int:
        return (self.amount_kopecks or 0) // 100

    @property
    def live(self) -> bool:
        return self.status in ("pending", "active", "past_due")

    @property
    def interval_label(self) -> str:
        return {"month": "раз в месяц", "year": "раз в год"}.get(self.interval or "", "")


def _recurring(body: dict) -> Recurring:
    return Recurring(
        status=body.get("status"),
        plan_code=body.get("plan_code"),
        plan_title=body.get("plan_title"),
        amount_kopecks=body.get("amount_kopecks"),
        currency=body.get("currency"),
        interval=body.get("interval"),
        next_charge_at=_parse_time(body.get("next_charge_at")),
        last_charge_error=body.get("last_charge_error"),
        redirect_url=body.get("redirect_url"),
    )


async def payment_link(
    user_login: str, plan: Plan, quantity: int = 1, method: str | None = None
) -> PaymentLink:
    body = await _admin_request(
        "POST",
        f"{ADMIN}/orders/for-user",
        payload={
            "login": user_login,
            "plan_code": plan.code,
            "quantity": quantity,
            "payment_method": method,
        },
    )

    url = body.get("redirect_url")

    if not url:
        raise PanelError("платёжная ссылка не создана")

    return PaymentLink(
        order_id=body["id"],
        url=url,
        amount_kopecks=body["amount_kopecks"],
        currency=body.get("currency", "RUB"),
    )


async def refund_by_payment(provider: str, external_id: str, reason: str) -> str:
    order = await _admin_request("GET", f"{ADMIN}/orders/by-payment/{provider}/{external_id}")
    order_id = order["id"]

    await _admin_request(
        "POST", f"{ADMIN}/orders/{order_id}/refund", payload={"reason": reason}
    )

    return order_id


async def recurring_state(user_login: str) -> Recurring:
    body = await _admin_request("GET", f"{ADMIN}/recurring/by-login/{user_login}")

    return _recurring(body)


async def recurring_create(user_login: str, plan_code: str) -> Recurring:
    body = await _admin_request(
        "POST",
        f"{ADMIN}/recurring",
        payload={"login": user_login, "plan_code": plan_code},
    )

    return _recurring(body)


async def recurring_cancel(user_login: str) -> Recurring:
    body = await _admin_request(
        "POST",
        f"{ADMIN}/recurring/cancel",
        payload={"login": user_login},
    )

    return _recurring(body)
