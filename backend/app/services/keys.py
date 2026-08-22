"""
Раздача ключей: у каждого пользователя свой конфиг на каждом сервере.

Здесь же правило «сервер добавили — он появился у всех»: ключи не привязаны
к моменту регистрации пользователя, а досоздаются по факту.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, provisioning
from ..models import Provisioning, Server, User, UserKey, utcnow
from .errors import PanelError

# Потолок на раздачу ключей одному пользователю. Недоступных серверов может
# быть сколько угодно, и без срока запрос администратора растягивается на
# минуты. Пропущенные серверы досоздадутся при следующем обращении:
# ensure_keys вызывается и из приложения при каждом входе. Кто раздаёт ключи
# многим пользователям подряд — заводит один срок на весь запрос и передаёт
# его в ensure_keys, иначе потолок молча множится на число пользователей.
ENSURE_DEADLINE_SECONDS = 20

# Сколько раз пробуем занять адрес, если его увели прямо из-под нас. Больше
# одной-двух попыток подряд не бывает: свободных адресов в подсети сотни.
ADDRESS_ATTEMPTS = 5


def active_servers(db: OrmSession) -> list[Server]:
    return list(
        db.scalars(
            select(Server).where(Server.is_active.is_(True)).order_by(Server.sort_order, Server.id)
        )
    )


def known_devices(user: User) -> set[str]:
    """
    Устройства, которым положен пир прямо сейчас.

    Пустая строка есть всегда — это «ключ учётки»: им пользуются приложения
    старых версий, не присылающие идентификатор установки, и он же выдаётся
    при заведении пользователя, когда устройств ещё нет. Остальное — живые
    входы с приложений; браузер в кабинете сюда не попадает, туннеля у него
    нет и выдавать ему нечего.

    Слоты `ios-N` живут наравне с ними, хотя входа за ними не стоит: под
    iPhone приложения нет, и человек подключается ссылкой `vpn://` из
    кабинета. Пир ему нужен так же, как телефону с приложением, — и по тем
    же правилам снимается, когда кончается подписка. См. services/ios.py.
    """
    return {""} | {key for key in user.devices() if key} | set(user.ios_slots())


def ensure_keys(
    db: OrmSession,
    user: User,
    devices: set[str] | None = None,
    deadline: float | None = None,
) -> list[str]:
    """
    Досоздаёт пользователю ключи на всех включённых серверах.

    Вызывается и при создании пользователя, и при добавлении сервера, и при
    входе из приложения: так новый сервер появляется у всех сам, без ручной
    раздачи.

    `devices` — для каких устройств. По умолчанию для всех известных, то
    есть при разблокировке или включении человек получает обратно пиры на
    все свои устройства, а не только «ключ учётки». Вход передаёт сюда одно
    своё устройство: остальные его не ждут.

    `deadline` — момент `time.monotonic()`, после которого раздачу пора
    прекратить. Передаётся теми, кто зовёт ensure_keys в цикле по многим
    пользователям: свой срок на каждого превращает недоступный узел в
    минуты удержания воркера. Без него берётся собственный срок.

    Возвращает список предупреждений — сервер может быть недоступен, и это
    не повод валить всю операцию: остальные серверы человек получить должен.
    """
    warnings: list[str] = []
    wanted = known_devices(user) if devices is None else {(d or "").strip() for d in devices}
    existing = {
        (key.server_id, key.device_id or "") for key in user.keys if key.revoked_at is None
    }
    if deadline is None:
        deadline = time.monotonic() + ENSURE_DEADLINE_SECONDS

    for server in active_servers(db):
        if server.provisioning == Provisioning.SHARED:
            # Общий ключ лежит на самом сервере, отдельная запись не нужна
            continue
        for device_id in sorted(wanted):
            if (server.id, device_id) in existing:
                continue
            # Запас на один заход: проверка только перед попыткой позволяла
            # перескочить срок на целый сеанс SSH с недоступным узлом.
            if time.monotonic() + provisioning.CONNECT_TIMEOUT >= deadline:
                # Дальше не идём: пользователь уже создан и с частью серверов
                # работает, а остальные подтянутся сами при следующем входе.
                warnings.append(
                    f"{server.name}: не успели за отведённое время, ключ будет создан позже"
                )
                return warnings
            try:
                issue_key(db, user, server, device_id=device_id)
            except Exception as exc:  # сервер недоступен или шаблон кривой
                warnings.append(f"{server.name}: {exc}")
    return warnings


def find_key(db: OrmSession, user: User, server: Server, device_id: str = "") -> UserKey | None:
    """Ключ этого устройства на этом сервере — живой или отозванный."""
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
    """
    Заводит пира на сервере и выдаёт пользователю конфиг.

    Строка на пару «пользователь + сервер» одна и переиспользуется. Отзыв
    ключа её не удаляет, а помечает `revoked_at` — и повторная выдача
    обязана обновить ту же строку, а не вставлять вторую: на таблице стоит
    уникальность по этой паре, и вставка падала с IntegrityError уже после
    того, как пир добавлен на узел. Получался худший из исходов: в базе
    ключа нет, в панели доступа нет, а пир на сервере работает.

    `rotate=False` — возвращение доступа: пара ключей и адрес остаются
    прежними, на узел возвращается тот же пир. Это важнее, чем кажется.
    Конфиг лежит у человека в приложении, и генерация новой пары при
    каждом «включить» молча превращала его в мусор: панель показывает
    доступ, узел ждёт другой ключ, приложение стучится старым и не
    получает ответа. Заметить это со стороны клиента невозможно — просто
    «перестало работать».

    `rotate=True` — осознанный перевыпуск из панели, когда ключ надо
    именно сменить. Тогда старый пир снимается, а человек получает новый
    конфиг при следующем обращении приложения к списку серверов.
    """
    if not server.awg_template:
        raise PanelError("не задан шаблон конфига")

    device_id = (device_id or "").strip()
    key = find_key(db, user, server, device_id)

    # Возвращаем прежний доступ: всё, что нужно, уже лежит в строке.
    reuse = not rotate and key is not None and key.config and key.public_key and key.address
    if reuse:
        provisioning.add_peer_over_ssh(server, key.public_key, key.address)
        key.revoked_at = None
        db.commit()
        db.refresh(key)
        return key

    address = key.address if key is not None and key.address else None
    if address is None:
        key, address = _reserve_address(db, key, user, server, device_id)

    private_key, public_key = provisioning.generate_keypair()
    config = provisioning.render_from_template(server.awg_template, private_key, address)

    # Старый пир снимаем перед добавлением нового: иначе на узле остаются
    # два пира с разными ключами на один адрес, и сервер отвечает не тому.
    if key is not None and key.public_key and key.public_key != public_key:
        try:
            provisioning.remove_peer_over_ssh(server, key.public_key)
        except Exception:
            # Узел мог не ответить. Не повод не выдавать доступ: лишний пир
            # подчистит сверка в reconcile_peers.
            pass

    provisioning.add_peer_over_ssh(server, public_key, address)

    key.config = config
    # Шифр приватника обязан ехать вместе с новой парой. Иначе при перевыпуске
    # (rotate=True, «скомпрометирован», перевыпуск iOS) в private_key_enc остаётся
    # СТАРЫЙ ключ, а provisioning.private_key_for предпочитает шифр тексту — и
    # клиент получил бы конфиг со старым приватником при новом пире на узле:
    # рукопожатие не проходит. Нет ключа шифрования — обнуляем enc, чтобы чтение
    # честно откатилось на свежий открытый текст в config.
    key.private_key_enc = crypto.encrypt(private_key) if crypto.available() else None
    key.public_key = public_key
    key.address = address
    key.revoked_at = None
    # Счётчики нового пира на узле начинаются с нуля — иначе первый же замер
    # даст отрицательную разницу и потеряет весь прирост.
    key.rx_bytes = 0
    key.tx_bytes = 0
    key.last_handshake_at = None

    db.commit()
    db.refresh(key)
    return key


def _reserve_address(
    db: OrmSession, key: UserKey | None, user: User, server: Server, device_id: str = ""
) -> tuple[UserKey, str]:
    """
    Занимает свободный адрес в базе ДО захода по SSH.

    Раньше адрес выбирался, потом шёл целый сеанс SSH, и только после него
    строка коммитилась. Между чтением занятых адресов и коммитом проходили
    секунды, а параллельная выдача — обычное дело: вход в приложении, раздача
    ключей всем пользователям при добавлении узла, фоновые циклы. Оба вызова
    видели один и тот же свободный адрес и брали его. На узле адрес
    принадлежит ровно одному пиру, поэтому второй молча отбирал его у
    первого: туннель поднимается, трафик не идёт, и ни сверка, ни диагностика
    этого не видят — оба ключа «известные».

    Заготовку помечаем `revoked_at`: с пустым конфигом и `revoked_at is None`
    ensure_keys считал бы её готовым ключом и человек навсегда остался бы без
    конфига на этом сервере, если SSH не ответил. Отозванная строка адрес всё
    равно держит — занятые адреса считаются без учёта отзыва.
    """
    for _attempt in range(ADDRESS_ATTEMPTS):
        taken = list(
            db.scalars(
                select(UserKey.address).where(
                    UserKey.server_id == server.id, UserKey.address.is_not(None)
                )
            )
        )
        address = provisioning.next_address(taken)

        if key is None:
            key = UserKey(user_id=user.id, server_id=server.id, device_id=device_id or "")
            db.add(key)
        key.address = address
        key.config = key.config or ""  # колонка NOT NULL, а конфига ещё нет
        key.revoked_at = utcnow()
        try:
            db.commit()
        except IntegrityError:
            # Адрес увели между выбором и коммитом — уникальный индекс по
            # (server_id, address) для того и стоит. Берём следующий.
            db.rollback()
            key = find_key(db, user, server, device_id)
            continue
        return key, address

    raise PanelError("не удалось занять свободный адрес: адреса разбирают быстрее, чем выдаём")


def revoke_key(db: OrmSession, key: UserKey) -> None:
    """Убирает пира с сервера и помечает ключ отозванным."""
    server = key.server
    if server.provisioning == Provisioning.SSH and key.public_key:
        provisioning.remove_peer_over_ssh(server, key.public_key)
    key.revoked_at = utcnow()
    db.commit()
