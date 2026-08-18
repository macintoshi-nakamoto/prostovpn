"""
Доступ с iPhone: готовые ключи `vpn://` для AmneziaVPN.

Своего приложения под iOS нет, и закрыть это приложением в ближайшее время
нельзя. Значит, человек ставит официальный AmneziaVPN и вставляет туда
ссылку — а всё, что обычно делает наше приложение (просит конфиг, следит за
подпиской, отваливается по концу срока), должна сделать панель.

Ключ здесь не отдельная сущность. Это обычный пир на сервере, заведённый на
«устройство» со слотом `ios-N` (см. `User.ios_slots`). Ключей на учётку до
`IOS_MAX_KEYS`, и заводятся они по одному: поделить пир между телефонами
нельзя — сервер помнит у пира один адрес подключения, и второй телефон
молча отбирает соединение у первого, — поэтому второй телефон это второй
ключ. Из этого само собой следует всё нужное:

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
from ..models import (
    IOS_MAX_KEYS,
    Provisioning,
    Server,
    User,
    UserKey,
    ios_slot,
    ios_slot_number,
    is_ios_slot,
)
from .errors import PanelError
from .keys import active_servers, ensure_keys, issue_key, revoke_key

log = logging.getLogger("panel.ios")


def key_name(user: User, slot: int = 1) -> str:
    """
    Как ключ подписан в списке серверов AmneziaVPN.

    С логином в скобках намеренно: человек присылает в поддержку скриншот
    экрана Amnezia, и по нему сразу видно, чья это учётка. Без логина там
    стояло бы одинаковое «ProstoVPN» у всех.

    Номер добавляется со второго ключа. У первого его нет не из экономии, а
    чтобы у людей с одним ключом — а таких большинство — подпись осталась
    ровно той, что уже лежит у них в Amnezia: ссылка собирается на лету, и
    новое имя означало бы «переимпортируйте ключ» на ровном месте.
    """
    tail = "" if slot <= 1 else f" · {slot}"
    return f"ProstoVPN ({user.login}){tail}"


# Разбор номера слота живёт в моделях: его знают и `User.ios_slots`, и здесь.
slot_number = ios_slot_number


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
    Доводит набор ключей до того, что человеку положено: недостающие пиры
    заводит, лишние снимает.

    Зовётся после всего, что меняет доступ, — покупки, продления, включения
    руками. Ключи при этом не «пересоздаются»: `ensure_keys` трогает только
    те слоты, пира которых на узле нет, а `issue_key` возвращает прежнюю
    пару. Лишними считаются слоты сверх `IOS_MAX_KEYS` — за потолок учётка
    уехать может только из истории или из ручной правки базы, но пир за
    таким слотом работает как настоящий, и снять его должно что-то одно.

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


def free_slot(user: User) -> int | None:
    """
    Наименьший свободный номер ключа. None — потолок выбран.

    Наименьший, а не следующий по счёту: после удаления второго ключа из
    трёх дырка должна закрыться, иначе номера уходят вверх, и человек с
    двумя ключами видит «Ключ 1» и «Ключ 4».
    """
    taken = set(user.ios_slot_numbers())
    for number in range(1, IOS_MAX_KEYS + 1):
        if number not in taken:
            return number
    return None


def add_key(db: OrmSession, user: User) -> tuple[int, list[str]]:
    """
    Заводит ещё один ключ и возвращает его номер и предупреждения.

    Пир создаётся здесь же, а не «когда-нибудь потом»: человек нажал кнопку
    и ждёт ссылку на экране. Недоступный узел ссылку не отменяет — он
    попадает в предупреждения, а слот досоздастся при следующем обращении.
    """
    if user.ios_blocked:
        raise PanelError("ключи отключены администратором")
    if not user.has_access():
        raise PanelError("ключ выдаётся по действующей подписке")

    number = free_slot(user)
    if number is None:
        raise PanelError(f"на учётку выдаём не больше {IOS_MAX_KEYS} ключей")

    # Первый ключ заодно включает доступ: разделять «разрешить» и «выдать»
    # незачем — за кнопкой стоит одно намерение.
    user.ios_access = True
    db.commit()

    warnings = ensure_keys(db, user, devices={ios_slot(number)})
    db.refresh(user)
    return number, warnings


def remove_key(db: OrmSession, user: User, number: int) -> list[str]:
    """
    Убирает один ключ: пир с узлов, строки из базы.

    Строки удаляются целиком, а не отзываются, и это разница между «ключ
    удалён» и «ключ выключен». Отозванная строка держит за собой пару
    ключей и номер: следующая выдача переиспользовала бы их и вернула ту же
    ссылку — то есть удаление утёкшего ключа не удаляло бы ничего.

    Последний ключ так не снимают. Учётка с пометкой `ios_access` и без
    единого ключа — это состояние «ключ положен, но не заведён», из
    которого ближайший `sync` заведёт ключ обратно; чтобы забрать доступ
    насовсем, есть `remove`, а чтобы сменить единственную ссылку —
    `reissue`.
    """
    slot = ios_slot(number)
    rows = [key for key in user.keys if (key.device_id or "") == slot]
    if not rows:
        raise PanelError(f"ключа {number} у этой учётки нет")
    if len(user.ios_slot_numbers()) <= 1:
        raise PanelError("это единственный ключ — перевыпустите его или уберите доступ целиком")

    problems: list[str] = []
    for key in rows:
        if key.revoked_at is None:
            try:
                revoke_key(db, key)
            except Exception as exc:
                # Пир мог остаться на узле. Строку всё равно сносим: сверка
                # reconcile_peers снимет пира, которому нечего предъявить в
                # базе, а живая строка вернула бы человеку ту же ссылку.
                problems.append(f"{key.server.name}: {exc}")

    for key in rows:
        db.delete(key)
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
    out: list[IosKey] = []
    for key in sorted(user.keys, key=lambda k: (slot_number(k.device_id), k.server_id)):
        if not is_ios_slot(key.device_id):
            continue
        if key.revoked_at is not None and not include_revoked:
            continue
        server = key.server
        if server.provisioning != Provisioning.SSH or not key.config:
            continue
        slot = slot_number(key.device_id)
        name = key_name(user, slot)
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
                vpn_url=_vpn_url(server, key, name),
                traffic_bytes=key.rx_bytes + key.tx_bytes,
                last_handshake_at=key.last_handshake_at,
                created_at=key.created_at,
                is_active=key.revoked_at is None,
            )
        )
    return out
