"""
Доступ с iPhone: готовые ключи `vpn://` для AmneziaVPN.

Своего приложения под iOS нет, и закрыть это приложением в ближайшее время
нельзя. Значит, человек ставит официальный AmneziaVPN и вставляет туда
ссылку — а всё, что обычно делает наше приложение (просит конфиг, следит за
подпиской, отваливается по концу срока), должна сделать панель.

Ключ здесь не отдельная сущность. Это обычный пир на сервере, заведённый на
«устройство» со слотом `ios-1` (см. `User.ios_slots`). Ключ на учётку один:
поделить пир между телефонами нельзя, а второй ключ — это разговор с
поддержкой, а не кнопка. Из этого само собой следует всё нужное:

* трафик считается тем же обходом `awg show dump`, что и у приложений;
* конец подписки, исчерпанный трафик, пауза и бан снимают пир с узла тем же
  `enforce_access`, что и у всех, — ключ перестаёт работать сам;
* «отключить», «включить», «перевыпустить» — это отзыв и выдача пира,
  которые панель уже умеет.

Второй ветки правил для iOS нет нигде, и это главное свойство всей затеи:
разойтись с остальной системой ей просто негде.

Ключи только с серверов на своей генерации (`ssh`). Сервер с общим ключом
раздаёт один конфиг всем сразу — его нельзя ни отозвать одному человеку, ни
посчитать по нему трафик, то есть ровно то, ради чего это написано, там не
работает.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession

from .. import provisioning
from ..models import IOS_SLOT_PREFIX, Provisioning, Server, User, UserKey, is_ios_slot
from .errors import PanelError
from .keys import active_servers, ensure_keys, issue_key, revoke_key

log = logging.getLogger("panel.ios")


def key_name(user: User) -> str:
    """
    Как ключ подписан в списке серверов AmneziaVPN.

    С логином в скобках намеренно: человек присылает в поддержку скриншот
    экрана Amnezia, и по нему сразу видно, чья это учётка. Без логина там
    стояло бы одинаковое «ProstoVPN» у всех.
    """
    return f"ProstoVPN ({user.login})"


def slot_number(device_id: str | None) -> int:
    """Номер устройства из идентификатора слота. Не слот — ноль."""
    if not is_ios_slot(device_id):
        return 0
    tail = (device_id or "")[len(IOS_SLOT_PREFIX) :]
    return int(tail) if tail.isdigit() else 0


@dataclass(frozen=True)
class IosKey:
    """Один ключ для одного устройства на одном сервере."""

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
    traffic_bytes: int
    last_handshake_at: dt.datetime | None
    created_at: dt.datetime
    is_active: bool


def _live_slot_keys(user: User) -> list[UserKey]:
    return [
        key
        for key in user.keys
        if is_ios_slot(key.device_id) and key.revoked_at is None
    ]


def sync(db: OrmSession, user: User) -> list[str]:
    """
    Приводит набор ключей к тарифу: лишние снимает, недостающие заводит.

    Зовётся после всего, что меняет доступ, — покупки, продления, включения
    руками. Заодно подчищает наследство: пока ключей заводилось по одному на
    устройство тарифа, у людей осталось по два-четыре слота, и лишние тут
    снимаются с узлов — иначе оплачен один ключ, а работают четыре.

    Возвращает предупреждения по недоступным узлам: один молчащий сервер не
    повод не выдать остальные.
    """
    if not user.ios_access:
        return []

    warnings: list[str] = []
    wanted = set(user.ios_slots())

    if user.ios_blocked:
        # Ключ отключён администратором — выдавать нечего, и это не ошибка.
        return []

    if not user.has_access():
        # Доступа нет — подписка кончилась, выбран трафик, стоит пауза. Ключи
        # в такой момент не заводим: их всё равно снял бы ближайший обход
        # узлов, а до него ссылка успела бы поработать.
        return ["доступ закрыт — ключи появятся после оплаты"]

    for key in _live_slot_keys(user):
        if (key.device_id or "") in wanted:
            continue
        try:
            revoke_key(db, key)
        except Exception as exc:  # узел не ответил — скажем об этом вслух
            warnings.append(f"{key.server.name}: лишний ключ не снят — {exc}")

    warnings += ensure_keys(db, user, devices=wanted)
    db.refresh(user)
    return warnings


def enable(db: OrmSession, user: User) -> list[str]:
    """
    Выдаёт ключ и снимает отключение, если оно стояло.

    Тем же действием ключ и возвращается: пара ключей и адрес сохраняются,
    на узел возвращается тот же пир — ссылка, лежащая у человека в Amnezia,
    продолжает работать. Новый ключ выдаёт только «перевыпустить».
    """
    user.ios_access = True
    user.ios_blocked = False
    db.commit()
    return sync(db, user)


def disable(db: OrmSession, user: User) -> list[str]:
    """
    Отключает ключ: пир уходит с узла, пометка остаётся.

    Пир снимается сразу, а не «перестаёт выдаваться»: ссылка уже лежит у
    человека в Amnezia, и пока пир на узле жив, туннель работает.

    Пометка нужна, чтобы отключение нельзя было обойти кнопкой в кабинете:
    человек нажмёт «получить ключ» и через полминуты вернёт себе доступ,
    который у него только что забрали. Включает обратно администратор — тем
    же ключом, что был.
    """
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


def remove(db: OrmSession, user: User) -> list[str]:
    """
    Удаляет ключ совсем: пир с узла, строку из базы, пометку с учётки.

    Отличие от «отключить» в том, что после удаления человек может выдать
    себе ключ заново — кнопкой в кабинете, — и это будет уже другой ключ, с
    другой парой и другим адресом. Так и снимают ключ, который куда-то
    утёк: старая ссылка становится мусором навсегда, а не ждёт включения.
    """
    problems: list[str] = []
    for key in _live_slot_keys(user):
        try:
            revoke_key(db, key)
        except Exception as exc:
            problems.append(f"{key.server.name}: {exc}")

    # Строки удаляем целиком, вместе с отозванными: пока они лежат, повторная
    # выдача переиспользует прежнюю пару ключей и вернёт ту же ссылку.
    for key in [k for k in user.keys if is_ios_slot(k.device_id)]:
        db.delete(key)

    user.ios_access = False
    user.ios_blocked = False
    db.commit()
    db.refresh(user)
    return problems


def reissue(db: OrmSession, user: User) -> list[str]:
    """
    Меняет ключи на новые: старые ссылки перестают работать сразу.

    Нужно, когда ссылку переслали дальше — у ключа нет пароля, и утёкшая
    ссылка это и есть утёкший доступ.
    """
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


def _vpn_url(server: Server, key: UserKey, name: str) -> str:
    return provisioning.build_vpn_key(
        server.host,
        key.config,
        port=server.port,
        name=name,
        address=key.address,
    )


def keys(user: User, include_revoked: bool = False) -> list[IosKey]:
    """
    Ключи человека готовыми ссылками — для кабинета, бота и панели.

    Ссылка собирается на месте, а не хранится: в базе лежит конфиг пира, а
    `vpn://` — всего лишь его упаковка. Хранить обе формы значит однажды
    показать человеку ссылку от пира, которого на узле уже нет.
    """
    name = key_name(user)
    out: list[IosKey] = []
    for key in sorted(user.keys, key=lambda k: (slot_number(k.device_id), k.server_id)):
        if not is_ios_slot(key.device_id):
            continue
        if key.revoked_at is not None and not include_revoked:
            continue
        server = key.server
        if server.provisioning != Provisioning.SSH or not key.config:
            continue
        out.append(
            IosKey(
                id=key.id,
                slot=slot_number(key.device_id),
                name=name,
                server_id=server.id,
                server_name=server.name,
                country=server.country,
                country_code=server.country_code,
                city=server.city,
                address=key.address,
                vpn_url=_vpn_url(server, key, name),
                traffic_bytes=key.rx_bytes + key.tx_bytes,
                last_handshake_at=key.last_handshake_at,
                created_at=key.created_at,
                is_active=key.revoked_at is None,
            )
        )
    return out
