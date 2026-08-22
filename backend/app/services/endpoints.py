"""
Точки входа узла: заведение, применение на узле, вывод из обращения.

Единственная дверь к записи в `node_endpoints`. Правило одно и оно жёсткое:
**набор обфускации живой точки входа не меняется никогда**. Не комментарием, а
отсутствием такой операции — смена H/S/J в секции [Interface] рвёт разом всех
пиров интерфейса, и `awg syncconf` от этого не спасает, потому что применяет и
секцию [Interface] тоже.

Ротация набора устроена иначе: поднимается новая точка входа, старая переводится
в `draining` (новых не селим), люди переезжают на ней сами при перевыпуске, и
когда пиров не остаётся — `retired`.
"""

from __future__ import annotations

import ipaddress
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from .. import obfuscation as obf
from .. import provisioning
from ..models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Server,
    UserKey,
    utcnow,
)
from .errors import PanelError

log = logging.getLogger("panel.endpoints")

# Базовая подсеть awg-интерфейсов: awgN живёт в 10.8.(N+1).0/24.
# awg0 исторически занимает 10.8.1.0/24, поэтому смещение на единицу.
SUBNET_TEMPLATE = "10.8.{octet}.0/24"
BASE_PORT = 51820


def _suggest_slot(db: OrmSession, server: Server) -> tuple[str, int, str]:
    """Следующие свободные имя, порт и подсеть для нового awg-интерфейса."""
    taken_handles = {ep.handle for ep in server.endpoints}
    taken_ports = {ep.listen_port for ep in server.endpoints} | {server.port}
    for ep in server.endpoints:
        taken_ports |= set(ep.alt_port_list())
    taken_ports |= set(server.alt_port_list())
    taken_subnets = {ep.subnet for ep in server.endpoints if ep.subnet}

    for index in range(0, 100):
        handle = f"awg{index}"
        port = BASE_PORT + index
        subnet = SUBNET_TEMPLATE.format(octet=index + 1)
        if handle in taken_handles or port in taken_ports or subnet in taken_subnets:
            continue
        return handle, port, subnet
    raise PanelError("на узле не осталось свободных слотов под интерфейс")


def create_awg_endpoint(
    db: OrmSession,
    server: Server,
    *,
    handle: str | None = None,
    listen_port: int | None = None,
    subnet: str | None = None,
    alt_ports: str = "",
    capacity: int | None = None,
    note: str | None = None,
    obfuscation_set: obf.ObfuscationSet | None = None,
) -> NodeEndpoint:
    """
    Заводит точку входа awg в состоянии `draft` — на узле её ещё нет.

    Набор обфускации генерируется здесь и больше не меняется. Валидность
    гарантирована типом: принимается только готовый `ObfuscationSet`, который
    иначе как через проверку не собрать.
    """
    suggested_handle, suggested_port, suggested_subnet = _suggest_slot(db, server)
    handle = provisioning.iface_name(handle or suggested_handle)
    listen_port = int(listen_port or suggested_port)
    subnet = subnet or suggested_subnet

    # Подсеть и порт — данные, а не строки: они уедут в конфиг и в правило
    # iptables на узле.
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise PanelError(f"неверная подсеть: {exc}") from exc
    if not (0 < listen_port < 65536):
        raise PanelError("порт вне диапазона")

    # Все порты, уже занятые на этом узле: и слушающие, и запасные. Запасной
    # порт — это правило перенаправления на конкретный интерфейс, и один порт
    # не может вести в два места: второе правило просто не сработает, а
    # пользователь получит чужую обфускацию и вечное «подключение».
    spare = _clean_ports(alt_ports, listen_port)
    wanted = {listen_port} | {int(p) for p in spare.split(",") if p}

    # Порты самого узла — это порты ИСТОРИЧЕСКОГО интерфейса, а не чужие:
    # поля Server.port/alt_ports описывают ровно его. Для него они не конфликт,
    # для всех остальных — занято.
    taken: dict[int, str] = {}
    if handle != provisioning.INTERFACE:
        taken[server.port] = "узла"
        for port in server.alt_port_list():
            taken[port] = "узла"
    for ep in server.endpoints:
        if ep.handle == handle:
            raise PanelError(f"точка входа {handle} на этом узле уже есть")
        taken[ep.listen_port] = ep.handle
        for port in ep.alt_port_list():
            taken[port] = ep.handle
        if ep.subnet and ipaddress.ip_network(ep.subnet, strict=False).overlaps(network):
            raise PanelError(f"подсеть {subnet} пересекается с {ep.subnet}")

    for port in sorted(wanted):
        owner = taken.get(port)
        if owner is not None:
            raise PanelError(f"порт {port} уже занят ({owner})")

    values = obfuscation_set or obf.generate()
    endpoint = NodeEndpoint(
        server_id=server.id,
        kind=EndpointKind.AWG,
        transport="udp",
        handle=handle,
        listen_port=listen_port,
        alt_ports=spare,
        subnet=str(network),
        params={
            **values.as_dict(),
            "dns": "1.1.1.1, 1.0.0.1",
            "mtu": 1280,
            "allowed_ips": "0.0.0.0/0, ::/0",
            "keepalive": 25,
            # Публичный ключ узла появится после применения на узле: его
            # генерирует сам узел. Пустой ключ — точка входа неработоспособна,
            # поэтому она и остаётся draft до применения.
            "server_public_key": "",
        },
        priority=0,
        capacity=capacity,
        state=EndpointState.DRAFT,
        note=note,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    log.info("заведена точка входа %s (порт %s, подсеть %s)", handle, listen_port, subnet)
    return endpoint


def _clean_ports(value: str, listen_port: int) -> str:
    out: list[int] = []
    for chunk in (value or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk.isdigit():
            continue
        port = int(chunk)
        if 0 < port < 65536 and port != listen_port and port not in out:
            out.append(port)
    return ",".join(str(p) for p in out)


def apply_awg_endpoint(db: OrmSession, endpoint: NodeEndpoint) -> NodeEndpoint:
    """
    Поднимает точку входа на узле и делает её `active`.

    Порядок обязателен: публичный ключ читается С УЗЛА и только потом
    записывается в базу. Если панель запишет собственный ключ, а на узле
    окажется другой, рукопожатия не будет ни у кого, и выглядеть это будет как
    несовпадение обфускации — самая дорогая в диагностике поломка.
    """
    if endpoint.kind != EndpointKind.AWG:
        raise PanelError("применять на узле умеем только awg-точки входа")
    server = endpoint.server
    result = provisioning.create_awg_interface(server, endpoint)

    params = dict(endpoint.params or {})
    params["server_public_key"] = result["public_key"]
    endpoint.params = params
    endpoint.state = EndpointState.ACTIVE
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()
    db.refresh(endpoint)
    log.info(
        "точка входа %s применена на узле %s (%s)",
        endpoint.handle,
        server.name,
        "уже существовала" if result.get("existed") else "создана",
    )
    return endpoint


def live_count(db: OrmSession, endpoint_ids: list[int]) -> dict[int, int]:
    """
    Сколько адресов занято на каждой точке входа — одним запросом.

    Считаем по строкам с непустым адресом, включая отозванные: отозванная
    строка адрес за собой держит (его переиспользует возврат доступа), и не
    учитывать её значит однажды выдать два пира на один адрес.
    """
    if not endpoint_ids:
        return {}
    from sqlalchemy import func

    rows = db.execute(
        select(UserKey.endpoint_id, func.count(UserKey.id))
        .where(UserKey.endpoint_id.in_(endpoint_ids), UserKey.address.is_not(None))
        .group_by(UserKey.endpoint_id)
    ).all()
    return {row[0]: row[1] for row in rows}


def set_state(db: OrmSession, endpoint: NodeEndpoint, state: EndpointState) -> NodeEndpoint:
    """
    Меняет состояние точки входа.

    В `retired` пускаем только пустую: пока на ней живут пиры, «вывод из
    обращения» означал бы тихую потерю доступа у людей, которые на ней сидят.
    """
    if state in (EndpointState.ACTIVE, EndpointState.DRAINING):
        # Открыть для подключений можно только то, что реально стоит на узле.
        # У awg признак — публичный ключ интерфейса: его записывает применение,
        # прочитав С УЗЛА. Без него панель селила бы людей на интерфейс,
        # которого нет, и они получали бы вечное «подключение».
        if endpoint.kind == EndpointKind.AWG and not (endpoint.params or {}).get(
            "server_public_key"
        ):
            raise PanelError(
                "точка входа ещё не поднята на узле — сначала «Поднять на узле»"
            )

    if state == EndpointState.RETIRED:
        if endpoint.kind == EndpointKind.AWG:
            busy = live_count(db, [endpoint.id]).get(endpoint.id, 0)
            if busy:
                raise PanelError(
                    f"на точке входа ещё {busy} доступов — сначала переведите её в «слив» "
                    f"и дождитесь переезда"
                )
        else:
            # У VLESS доступ живёт в конфиге узла, а не в паре ключей. Вывод из
            # обращения обязан погасить креды: иначе сохранённая у человека
            # ссылка продолжала бы работать после «выключения» точки входа.
            from ..models import UserEndpointCred

            revoked = db.execute(
                update(UserEndpointCred)
                .where(
                    UserEndpointCred.endpoint_id == endpoint.id,
                    UserEndpointCred.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow())
            ).rowcount
            if revoked:
                log.info("точка входа %s: снято доступов %d", endpoint.handle, revoked)
    endpoint.state = state
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()
    db.refresh(endpoint)

    if endpoint.kind == EndpointKind.VLESS:
        # Состав клиентов и сама точка входа изменились — на узел это надо
        # донести, иначе «выключено» существует только в панели.
        from . import xray

        xray.push_to_node(db, endpoint.server)
    return endpoint


def endpoint_for_key(db: OrmSession, key: UserKey) -> NodeEndpoint | None:
    """Точка входа этого ключа. NULL у ключей старше фазы 2."""
    if key.endpoint_id is None:
        return None
    return db.get(NodeEndpoint, key.endpoint_id)


def interface_of(db: OrmSession, key: UserKey) -> str:
    """
    Имя интерфейса, на котором живёт пир этого ключа.

    Ключ без точки входа — это строка, заведённая до фазы 2: она живёт на
    историческом awg0, и других вариантов у неё нет.
    """
    endpoint = endpoint_for_key(db, key)
    return endpoint.handle if endpoint is not None else provisioning.INTERFACE
