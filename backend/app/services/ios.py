from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import (
    IOS_MAX_KEYS,
    Provisioning,
    Server,
    User,
    UserKey,
    ios_slot,
    ios_slot_number,
    is_ios_slot,
    utcnow,
)
from .errors import PanelError
from .keys import active_servers, ensure_keys, issue_key, revoke_key, xray_revoke

log = logging.getLogger("panel.ios")


def key_name(user: User, slot: int = 1) -> str:
    tail = "" if slot <= 1 else f" · {slot}"
    return f"prostovpn.cc ({user.login}){tail}"


slot_number = ios_slot_number


def _prefer_awg2() -> None:
    """
    Ключи vpn:// из кабинета и бота: версия приложения неизвестна, поэтому
    поколение задаётся настройкой PANEL_AWG_KEYS_LEVEL. С 04.09.2026 по
    умолчанию 3 — AmneziaWG 3.0 с шифрованием заголовков: рукопожатие не
    видно даже по типу пакета. Требует AmneziaVPN 5.0.0.5 (iOS 5.0.1.5,
    вышла 21.08.2026); 2 — с 4.8.12.9. Кабинет говорит, какая версия нужна.
    """
    from ..config import settings
    from . import compat

    compat.CLIENT_AWG_LEVEL.set(int(settings().awg_keys_level))


@dataclass(frozen=True)
class IosKey:

    id: int
    slot: int
    name: str
    server_id: int
    server_name: str
    country: str | None
    country_code: str | None
    city: str | None
    address: str | None
    vpn_url: str
    qr_payload: str | None
    traffic_bytes: int
    last_handshake_at: dt.datetime | None
    created_at: dt.datetime
    is_active: bool
    disconnected: bool = False


def _live_slot_keys(user: User) -> list[UserKey]:
    return [
        key
        for key in user.keys
        if is_ios_slot(key.device_id) and key.revoked_at is None
    ]


def sync(db: OrmSession, user: User, home: int | None = None) -> list[str]:
    _prefer_awg2()
    if not user.ios_access:
        return []

    warnings: list[str] = []
    wanted = set(user.ios_slots())

    if user.ios_blocked:
        return []

    if not user.has_access():
        return ["доступ закрыт — ключи появятся после оплаты"]

    for key in _live_slot_keys(user):
        if (key.device_id or "") in wanted:
            continue
        try:
            revoke_key(db, key)
        except Exception as exc:
            warnings.append(f"{key.server.name}: лишний ключ не снят — {exc}")

    warnings += ensure_keys(db, user, devices=wanted, home=home)
    db.refresh(user)
    return warnings


def device_limit_error(user: User) -> str:
    limit = user.device_limit()
    used = user.devices_used()
    return (
        f"по тарифу доступно устройств: {limit}, занято {used}. Отключите "
        "ненужное устройство на главной или выберите тариф больше"
    )


def require_free_device(user: User) -> None:
    """
    Новый ключ — новое устройство, и он должен уместиться в лимит тарифа.
    Раньше лимит только показывался, и человек на тарифе с одним
    устройством спокойно выпускал пять ключей.
    """
    if user.devices_left() <= 0:
        raise PanelError(device_limit_error(user), "device_limit")


def enable(db: OrmSession, user: User, server_id: int | None = None) -> list[str]:
    _prefer_awg2()
    home = home_id(db, server_id)
    if not user.ios_slots_live():
        # Первый ключ занимает место наравне с входом приложения.
        require_free_device(user)
    user.ios_access = True
    user.ios_blocked = False
    for key in user.keys:
        if is_ios_slot(key.device_id):
            key.disconnected_at = None
    db.commit()
    return sync(db, user, home=home)


def disable(db: OrmSession, user: User) -> list[str]:
    problems: list[str] = []
    for key in _live_slot_keys(user):
        try:
            revoke_key(db, key)
        except Exception as exc:
            problems.append(f"{key.server.name}: {exc}")

    user.ios_blocked = True
    db.commit()
    db.refresh(user)
    return problems


def free_slot(user: User) -> int | None:
    taken = set(user.ios_slot_numbers())
    for number in range(1, IOS_MAX_KEYS + 1):
        if number not in taken:
            return number
    return None


def choices(db: OrmSession) -> list[Server]:
    return [s for s in active_servers(db) if s.provisioning != Provisioning.SHARED]


def home_id(db: OrmSession, server_id: int | None) -> int | None:
    if server_id is None:
        return None
    for server in choices(db):
        if server.id == server_id:
            return server.id
    raise PanelError("эта страна сейчас недоступна — выберите другую")


def add_key(db: OrmSession, user: User, server_id: int | None = None) -> tuple[int, list[str]]:
    _prefer_awg2()
    if user.ios_blocked:
        raise PanelError("ключи отключены администратором")
    if not user.has_access():
        raise PanelError("ключ выдаётся по действующей подписке")

    number = free_slot(user)
    if number is None:
        raise PanelError(f"на учётку выдаём не больше {IOS_MAX_KEYS} ключей")
    require_free_device(user)

    home = home_id(db, server_id)

    user.ios_access = True
    db.commit()

    warnings = ensure_keys(db, user, devices={ios_slot(number)}, home=home)
    db.refresh(user)
    return number, warnings


def disconnect_key(db: OrmSession, user: User, number: int) -> list[str]:
    slot = ios_slot(number)
    rows = [key for key in user.keys if (key.device_id or "") == slot]
    if not rows:
        raise PanelError(f"ключа {number} у этой учётки нет")

    problems: list[str] = []
    now = utcnow()
    for key in rows:
        if key.revoked_at is None:
            try:
                revoke_key(db, key)
            except Exception as exc:
                problems.append(f"{key.server.name}: {exc}")
                key.revoked_at = now
        key.disconnected_at = now
        key.last_handshake_at = None
    db.commit()
    # Запасная учётка Reality того же слота — тоже с узлов.
    xray_revoke(db, user.id, slot)
    db.refresh(user)
    return problems


def reconnect_key(db: OrmSession, user: User, number: int) -> list[str]:
    if user.ios_blocked:
        raise PanelError("ключи отключены администратором — напишите в поддержку")
    if not user.has_access():
        raise PanelError("ключ включается по действующей подписке")

    slot = ios_slot(number)
    rows = [key for key in user.keys if (key.device_id or "") == slot]
    if not rows:
        raise PanelError(f"ключа {number} у этой учётки нет")

    # Отключённый ключ место не занимает — включить его обратно можно только
    # в свободное.
    if number not in user.ios_slots_live():
        require_free_device(user)

    user.ios_access = True
    for key in rows:
        key.disconnected_at = None
    db.commit()

    warnings = ensure_keys(db, user, devices={slot})
    db.refresh(user)
    return warnings


def remove_key(db: OrmSession, user: User, number: int) -> list[str]:
    slot = ios_slot(number)
    rows = [key for key in user.keys if (key.device_id or "") == slot]
    if not rows:
        raise PanelError(f"ключа {number} у этой учётки нет")
    if len(user.ios_slot_numbers()) <= 1:
        # Последний ключ удаляется вместе с доступом: человек хочет убрать
        # устройство, а не получить отказ. Новый ключ выпустится по кнопке.
        return remove(db, user)

    problems: list[str] = []
    for key in rows:
        if key.revoked_at is None:
            try:
                revoke_key(db, key)
            except Exception as exc:
                problems.append(f"{key.server.name}: {exc}")

    for key in rows:
        db.delete(key)
    db.commit()
    xray_revoke(db, user.id, slot)
    db.refresh(user)
    return problems


def remove(db: OrmSession, user: User) -> list[str]:
    problems: list[str] = []
    for key in _live_slot_keys(user):
        try:
            revoke_key(db, key)
        except Exception as exc:
            problems.append(f"{key.server.name}: {exc}")

    slots = {k.device_id for k in user.keys if is_ios_slot(k.device_id)}
    for key in [k for k in user.keys if is_ios_slot(k.device_id)]:
        db.delete(key)

    user.ios_access = False
    user.ios_blocked = False
    db.commit()
    for slot in slots:
        xray_revoke(db, user.id, slot)
    db.refresh(user)
    return problems


def reissue(db: OrmSession, user: User) -> list[str]:
    _prefer_awg2()
    if not user.ios_access:
        raise PanelError("у этой учётки нет ключа для iPhone — сначала выдайте его")

    problems: list[str] = []
    for key in _live_slot_keys(user):
        try:
            revoke_key(db, key)
        except Exception as exc:
            problems.append(f"{key.server.name}: старый ключ не снят — {exc}")

    for server in active_servers(db):
        if server.provisioning != Provisioning.SSH:
            continue
        for slot in user.ios_slots():
            try:
                issue_key(db, user, server, rotate=True, device_id=slot)
            except Exception as exc:
                problems.append(f"{server.name}: {exc}")
    db.refresh(user)
    return problems


def _vpn_url(server: Server, key: UserKey, name: str) -> str | None:
    config = provisioning.serving_config(server, key)
    if not config:
        # Отключённый (отозванный) ключ serving_config не отдаёт; в config
        # приватного ключа больше нет — только заглушка, настоящий под
        # шифром. Без него ссылку не собрать — такой ключ не показываем.
        private_key = provisioning.private_key_for(key)
        if not private_key or not key.config:
            return None
        config = provisioning.with_private_key(key.config, private_key)
    # Ключ уходит в AmneziaVPN: с 4.8.5 приложение понимает I1–I5, а более
    # старое незнакомые поля vpn:// просто не читает — сигнатурные пакеты
    # ему не мешают. Значения берём из точки входа, а не из текста ключа.
    from sqlalchemy.orm import object_session

    from ..models import NodeEndpoint

    db = object_session(key)
    endpoint = db.get(NodeEndpoint, key.endpoint_id) if db is not None and key.endpoint_id else None
    if endpoint is not None:
        config = provisioning.with_special_junk(config, endpoint.params)
    return provisioning.build_vpn_key(
        server.host,
        config,
        port=server.port,
        name=name,
        address=key.address,
    )


def keys(
    user: User, include_revoked: bool = False, include_disconnected: bool = False
) -> list[IosKey]:
    out: list[IosKey] = []
    for key in sorted(user.keys, key=lambda k: (slot_number(k.device_id), k.server_id)):
        if not is_ios_slot(key.device_id):
            continue
        if key.revoked_at is not None and not include_revoked:
            if not (include_disconnected and key.disconnected_at is not None):
                continue
        server = key.server
        if server.provisioning != Provisioning.SSH or not key.config:
            continue
        slot = slot_number(key.device_id)
        name = key_name(user, slot)
        url = _vpn_url(server, key, name)
        if not url:
            continue
        out.append(
            IosKey(
                id=key.id,
                slot=slot,
                name=name,
                server_id=server.id,
                server_name=server.name,
                country=server.country,
                country_code=server.country_code,
                city=server.city,
                address=key.address,
                vpn_url=url,
                qr_payload=provisioning.build_qr_payload(url),
                traffic_bytes=key.rx_bytes + key.tx_bytes,
                last_handshake_at=key.last_handshake_at,
                created_at=key.created_at,
                is_active=key.revoked_at is None,
                disconnected=key.disconnected_at is not None,
            )
        )
    return out
