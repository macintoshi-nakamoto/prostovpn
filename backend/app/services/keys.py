from __future__ import annotations

import datetime as dt
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, provisioning
from ..models import NodeEndpoint, Provisioning, Server, User, UserKey, is_ios_slot, utcnow
from .errors import PanelError

ENSURE_DEADLINE_SECONDS = 20

ADDRESS_ATTEMPTS = 5

# Сколько ключ должен молчать, чтобы его можно было перевыпустить на другой точке.
MIGRATE_IDLE = dt.timedelta(minutes=5)


def active_servers(db: OrmSession) -> list[Server]:
    return list(
        db.scalars(
            select(Server).where(Server.is_active.is_(True)).order_by(Server.sort_order, Server.id)
        )
    )


def known_devices(user: User) -> set[str]:
    return {""} | {key for key in user.devices() if key} | set(user.ios_slots())


def ios_homes(user: User) -> dict[str, set[int]]:
    homes: dict[str, set[int]] = {}
    for key in user.keys:
        if is_ios_slot(key.device_id):
            homes.setdefault(key.device_id or "", set()).add(key.server_id)
    return homes


def ensure_keys(
    db: OrmSession,
    user: User,
    devices: set[str] | None = None,
    deadline: float | None = None,
    home: int | None = None,
) -> list[str]:
    warnings: list[str] = []
    wanted = known_devices(user) if devices is None else {(d or "").strip() for d in devices}
    existing = {
        (key.server_id, key.device_id or "") for key in user.keys if key.revoked_at is None
    }
    if deadline is None:
        deadline = time.monotonic() + ENSURE_DEADLINE_SECONDS

    servers = [s for s in active_servers(db) if s.provisioning != Provisioning.SHARED]
    homes = ios_homes(user)
    fallback_home = servers[0].id if servers else None

    def belongs(device_id: str, server_id: int) -> bool:
        if not is_ios_slot(device_id):
            return True
        lives = homes.get(device_id)
        if lives:
            return server_id in lives
        target = home if home is not None else fallback_home
        return target is not None and server_id == target

    for server in servers:
        for device_id in sorted(wanted):
            if (server.id, device_id) in existing:
                continue
            if not belongs(device_id, server.id):
                continue
            if time.monotonic() + provisioning.CONNECT_TIMEOUT >= deadline:
                warnings.append(
                    f"{server.name}: не успели за отведённое время, ключ будет создан позже"
                )
                return warnings
            try:
                issue_key(db, user, server, device_id=device_id)
            except Exception as exc:
                warnings.append(f"{server.name}: {exc}")
    return warnings


def find_key(db: OrmSession, user: User, server: Server, device_id: str = "") -> UserKey | None:
    return db.scalar(
        select(UserKey).where(
            UserKey.user_id == user.id,
            UserKey.server_id == server.id,
            UserKey.device_id == (device_id or ""),
        )
    )


def issue_key(
    db: OrmSession, user: User, server: Server, rotate: bool = False, device_id: str = ""
) -> UserKey:
    device_id = (device_id or "").strip()
    key = find_key(db, user, server, device_id)

    from .placement import pick_endpoint

    endpoint = pick_endpoint(db, user, server, device_id)
    if endpoint is None and not server.awg_template:
        raise PanelError("не задан шаблон конфига")

    interface = endpoint.handle if endpoint is not None else provisioning.INTERFACE
    old_interface = interface
    if key is not None and key.endpoint_id is not None:
        old = db.get(NodeEndpoint, key.endpoint_id)
        if old is not None:
            old_interface = old.handle

    reuse = not rotate and key is not None and key.config and key.public_key and key.address
    if reuse:
        provisioning.add_peer_over_ssh(
            server, key.public_key, key.address, interface=old_interface
        )
        key.revoked_at = None
        db.commit()
        db.refresh(key)
        return key

    address = key.address if key is not None and key.address else None
    if key is not None and endpoint is not None and key.endpoint_id != endpoint.id:
        # Переезд на другую точку входа: у неё своя подсеть, старый адрес
        # там чужой — берём новый.
        address = None
    if address is None:
        key, address = _reserve_address(db, key, user, server, device_id, endpoint=endpoint)

    private_key, public_key = provisioning.generate_keypair()
    if endpoint is not None:
        config = provisioning.render_endpoint_config(endpoint, server, private_key, address)
    else:
        config = provisioning.render_from_template(server.awg_template, private_key, address)

    if key is not None and key.public_key and key.public_key != public_key:
        try:
            provisioning.remove_peer_over_ssh(server, key.public_key, interface=old_interface)
        except Exception:
            pass

    provisioning.add_peer_over_ssh(server, public_key, address, interface=interface)

    key.config = config
    if endpoint is not None:
        key.endpoint_id = endpoint.id
    key.private_key_enc = crypto.encrypt(private_key) if crypto.available() else None
    key.public_key = public_key
    key.address = address
    key.revoked_at = None
    key.rx_bytes = 0
    key.tx_bytes = 0
    key.last_handshake_at = None

    db.commit()
    db.refresh(key)
    return key


def _reserve_address(
    db: OrmSession,
    key: UserKey | None,
    user: User,
    server: Server,
    device_id: str = "",
    endpoint: NodeEndpoint | None = None,
) -> tuple[UserKey, str]:
    for _attempt in range(ADDRESS_ATTEMPTS):
        taken = list(
            db.scalars(
                select(UserKey.address).where(
                    UserKey.server_id == server.id, UserKey.address.is_not(None)
                )
            )
        )
        if endpoint is not None and endpoint.subnet:
            address = provisioning.next_address(taken, subnet=endpoint.subnet)
        else:
            address = provisioning.next_address(taken)

        if key is None:
            key = UserKey(user_id=user.id, server_id=server.id, device_id=device_id or "")
            db.add(key)
        if endpoint is not None:
            key.endpoint_id = endpoint.id
        key.address = address
        key.config = key.config or ""
        key.revoked_at = utcnow()
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            key = find_key(db, user, server, device_id)
            continue
        return key, address

    raise PanelError("не удалось занять свободный адрес: адреса разбирают быстрее, чем выдаём")


def xray_revoke(db: OrmSession, user_id: int, device_id: str | None = None) -> int:
    from . import xray

    return xray.revoke_for_user(db, user_id, device_id=device_id)


def interface_for(db: OrmSession, key: UserKey) -> str:
    if key.endpoint_id is not None:
        endpoint = db.get(NodeEndpoint, key.endpoint_id)
        if endpoint is not None:
            return endpoint.handle
    return provisioning.INTERFACE


def revoke_key(db: OrmSession, key: UserKey) -> None:
    server = key.server
    if server.provisioning == Provisioning.SSH and key.public_key:
        provisioning.remove_peer_over_ssh(
            server, key.public_key, interface=interface_for(db, key)
        )
    key.revoked_at = utcnow()
    db.commit()


def migrate_to_awg2(db: OrmSession, user: User, server: Server, key: UserKey | None) -> UserKey | None:
    """
    Переносит ключ на точку 2.0, если клиент её понимает, а ключ ещё на
    старой. Перевыпуск меняет ключ и адрес — годится для приложений и
    подписок, которые забирают конфиг сами; ключи iOS-слотов (vpn://,
    вставленные руками) не трогаем: их пришлось бы переимпортировать.
    """
    from . import compat
    from .placement import is_awg2, pick_endpoint

    if key is None or key.revoked_at is not None or not compat.CLIENT_AWG2.get():
        return key
    if is_ios_slot(key.device_id) or server.provisioning != Provisioning.SSH:
        return key
    current = db.get(NodeEndpoint, key.endpoint_id) if key.endpoint_id else None
    if current is not None and is_awg2(current):
        return key
    # Живой туннель не рвём: перевыпуск снимает старого пира с узла, и тот,
    # кто сейчас подключён этим ключом, отвалился бы посреди сессии. Переезд
    # только для ключа, который молчит хотя бы пять минут, — при следующем
    # подключении приложение и так забирает свежий конфиг.
    if key.last_handshake_at is not None and utcnow() - key.last_handshake_at < MIGRATE_IDLE:
        return key
    target = pick_endpoint(db, user, server, key.device_id)
    if target is None or not is_awg2(target):
        return key
    try:
        return issue_key(db, user, server, rotate=True, device_id=key.device_id)
    except Exception as exc:
        log_migrate(server, key, exc)
        return key


def log_migrate(server: Server, key: UserKey, exc: Exception) -> None:
    import logging

    logging.getLogger("panel.keys").warning(
        "ключ %s на %s не переехал на точку 2.0: %s", key.id, server.name, exc
    )
