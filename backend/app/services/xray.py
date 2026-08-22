"""
VLESS + XTLS-Reality на узле: конфиг, выдача и отзыв доступов, счётчики.

Зачем второй протокол. AmneziaWG — это UDP, и он ложится целиком там, где UDP
режут или пропускают только по белому списку. Reality решает другую задачу:
соединение неотличимо от обычного HTTPS к крупному чужому сайту, потому что им
и является — на чужой ClientHello наш узел молча проксирует запрос настоящему
донору и отдаёт его настоящий сертификат.

Приоритет у него ниже awg намеренно: AWG быстрее (UDP против TCP-в-TCP) и
дешевле по батарее. VLESS — запасной путь, а не основной.

Что здесь важно понимать про отзыв доступа. `xray api rmu` запрещает НОВЫЕ
подключения, но не рвёт уже установленную TCP-сессию — в отличие от
`awg set peer remove`, который останавливает трафик сразу. Поэтому отзыв
записывается и в конфиг на диске, и в живой демон: без первого доступ вернётся
при ближайшем перезапуске, без второго — продолжит работать до конца сессии.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import crypto, provisioning
from ..models import (
    EndpointKind,
    EndpointState,
    NodeEndpoint,
    Server,
    User,
    UserEndpointCred,
    utcnow,
)
from .errors import PanelError

log = logging.getLogger("panel.xray")

# Куда ставим xray и где живут его файлы.
XRAY_DIR = "/opt/prosto-xray"
XRAY_BIN = f"{XRAY_DIR}/xray"
XRAY_CONFIG = f"{XRAY_DIR}/config.json"
XRAY_LOCK = f"{XRAY_DIR}/.config.lock"
XRAY_UNIT = "prosto-xray"
# Системный пользователь, под которым работает демон (см. deploy/setup-xray.sh).
# Конфиг обязан оставаться читаемым для него после каждой перезаписи.
SERVICE_USER = "prosto-xray"

# Порт локального API демона — через него добавляются и снимаются клиенты без
# перезапуска. Слушает только loopback.
API_PORT = 10085

# Значение flow для XTLS: включает vision-обёртку, без неё Reality работает
# заметно медленнее на больших передачах.
FLOW = "xtls-rprx-vision"


def _label() -> str:
    """
    Непрозрачная метка клиента для статистики узла.

    Случайная, а не `pv-<номер учётки>`: метка попадает в статистику и логи
    xray, и человекочитаемый идентификатор там — это готовое сопоставление
    «трафик ↔ конкретный клиент» для всякого, кто получит доступ к узлу.
    """
    return secrets.token_hex(8)


def generate_reality_keypair(server: Server) -> tuple[str, str]:
    """
    Пара ключей Reality — генерирует сам узел командой xray.

    Своей реализации X25519 здесь мало: xray кодирует ключи своим способом, и
    несовпадение формата даёт «клиент подключается, но рукопожатие не проходит»
    вместо честной ошибки.
    """
    out = provisioning.run_over_ssh(server, f"{XRAY_BIN} x25519")
    private = public = ""
    for line in out.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        # Подпись менялась между версиями: раньше «Private key:»/«Public key:»,
        # теперь «PrivateKey:»/«Password (PublicKey):». Ищем по содержанию, а
        # не по началу строки — иначе public молча остаётся пустым, и точка
        # входа заводится с ключом, которого клиент не сможет проверить.
        flat = label.lower().replace(" ", "").replace("_", "")
        value = value.strip()
        if not value:
            continue
        if "privatekey" in flat:
            private = value
        elif "publickey" in flat:
            public = value
    if not private or not public:
        raise PanelError(f"xray не вернул пару ключей Reality: {out!r}")
    return private, public


def create_vless_endpoint(
    db: OrmSession,
    server: Server,
    *,
    listen_port: int,
    server_names: list[str],
    dest: str | None = None,
    handle: str | None = None,
    capacity: int | None = None,
    note: str | None = None,
) -> NodeEndpoint:
    """
    Заводит точку входа VLESS+Reality в состоянии «черновик».

    `server_names` — донорские имена: клиент пишет их в SNI, и наблюдателю
    соединение выглядит походом на этот сайт. `dest` — куда узел проксирует
    чужие подключения; по умолчанию первый донор.

    Донор и список имён обязаны быть согласованы: Reality пересылает исходный
    ClientHello на `dest`, и зонд с чужим SNI получит сертификат не того сайта,
    который назвал. Поэтому один донор на точку входа, а ротация — это ВТОРАЯ
    точка входа, а не правка живой.
    """
    if not crypto.available():
        # UUID клиента — единственный секрет доступа, и хранить его открытым
        # текстом нельзя. Лучше честно отказаться, чем завести протокол,
        # который тихо не защищён.
        raise PanelError(
            "не задан PANEL_SECRETS_KEY — без него креды VLESS негде хранить безопасно"
        )
    if not server_names:
        raise PanelError("нужен хотя бы один донорский домен")

    listen_port = int(listen_port)
    if not (0 < listen_port < 65536):
        raise PanelError("порт вне диапазона")
    for ep in server.endpoints:
        if ep.listen_port == listen_port or listen_port in ep.alt_port_list():
            raise PanelError(f"порт {listen_port} на этом узле уже занят")
    if listen_port == server.port or listen_port in server.alt_port_list():
        raise PanelError(f"порт {listen_port} уже объявлен у самого узла")

    handle = handle or f"vless-reality-{listen_port}"
    if any(ep.handle == handle for ep in server.endpoints):
        raise PanelError(f"точка входа {handle} уже есть")

    private_key, public_key = generate_reality_keypair(server)
    # Короткие идентификаторы: клиент присылает один из них, и по нему узел
    # отличает наших от случайных зондов. Пустую строку не кладём — она
    # означает «принимать любого», то есть отключает эту проверку.
    short_ids = [secrets.token_hex(4), secrets.token_hex(8)]

    endpoint = NodeEndpoint(
        server_id=server.id,
        kind=EndpointKind.VLESS,
        transport="tcp",
        handle=handle,
        listen_port=listen_port,
        alt_ports="",
        subnet=None,
        params={
            "security": "reality",
            "flow": FLOW,
            "public_key": public_key,
            "short_ids": short_ids,
            "server_names": list(server_names),
            "dest": dest or f"{server_names[0]}:443",
            "fingerprint": "chrome",
            "api_port": API_PORT,
        },
        secret_enc=crypto.encrypt(private_key),
        # Ниже awg: тот быстрее и дешевле по батарее.
        priority=100,
        capacity=capacity,
        state=EndpointState.DRAFT,
        # Счётчики xray живут в памяти и обнуляются перезапуском демона.
        counter_mode="absolute",
        note=note,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    log.info("заведена точка входа %s (порт %s, донор %s)", handle, listen_port, server_names[0])
    return endpoint


def _host_cidr(host: str) -> str | None:
    """Адрес узла маской, если это адрес. Домен — None: в routing.ip его нельзя."""
    import ipaddress

    try:
        address = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return None
    return f"{address}/{'32' if address.version == 4 else '128'}"


def build_config(db: OrmSession, server: Server) -> dict:
    """
    Собирает config.json целиком из состояния базы.

    Панель — единственный источник правды: всё, что дописали на узле руками,
    исчезнет при ближайшем применении. Так и задумано, иначе «что на узле» и
    «что в базе» разъедутся, и сверять их будет нечем.
    """
    inbounds: list[dict] = []
    # Локальное API — через него клиенты добавляются без перезапуска демона.
    inbounds.append(
        {
            "tag": "api-in",
            "listen": "127.0.0.1",
            "port": API_PORT,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        }
    )

    # Запросом, а не через server.endpoints: коллекция отношения могла быть
    # загружена до того, как точку входа завели, и тогда конфиг собрался бы
    # без неё — узел молча не принимал бы подключения.
    endpoints = db.scalars(
        select(NodeEndpoint)
        .where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
        )
        .order_by(NodeEndpoint.id)
    )
    for endpoint in endpoints:
        if endpoint.state == EndpointState.RETIRED:
            continue
        params = endpoint.params or {}
        private_key = ""
        if endpoint.secret_enc:
            try:
                private_key = crypto.decrypt(endpoint.secret_enc)
            except crypto.SecretsUnavailable:
                log.error("точка входа %s: приватный ключ Reality не читается", endpoint.handle)
                continue

        clients = []
        for cred in db.scalars(
            select(UserEndpointCred).where(
                UserEndpointCred.endpoint_id == endpoint.id,
                UserEndpointCred.revoked_at.is_(None),
            )
        ):
            identity = cred.identity
            if not identity:
                continue
            clients.append(
                {"id": identity, "flow": params.get("flow", FLOW), "email": cred.label}
            )

        inbounds.append(
            {
                "tag": f"in-{endpoint.handle}",
                "listen": "0.0.0.0",
                "port": endpoint.listen_port,
                "protocol": "vless",
                "settings": {"clients": clients, "decryption": "none"},
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": params.get("dest", ""),
                        "serverNames": params.get("server_names", []),
                        "privateKey": private_key,
                        "shortIds": params.get("short_ids", []),
                    },
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            }
        )

    return {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "services": ["HandlerService", "StatsService"]},
        "stats": {},
        "policy": {
            # Считать трафик по каждому клиенту — на этом стоит учёт расхода.
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "inbounds": inbounds,
        "outbounds": [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            # IPIfNonMatch обязателен: без него правила по адресам НЕ
            # применяются к цели, заданной доменом, и весь блок ниже
            # становится украшением.
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"},
                # Узел и панель — одна машина. Без этого правила клиент VLESS
                # ходил бы из loopback в панель, в API самого xray и в соседний
                # продукт: то есть мог бы добавить себе доступ и снять чужие.
                {
                    "type": "field",
                    "ip": ["geoip:private", "127.0.0.0/8", "10.8.0.0/16"],
                    "outboundTag": "block",
                },
                # Порты администрирования — только на самом узле, а не всюду:
                # запрет по голому номеру порта отнял бы у пользователя ssh и
                # чужие сайты на нестандартных портах, чего у awg-клиентов нет.
                #
                # `host` может быть и доменом (панель это допускает), а в
                # routing.ip домен недопустим — xray на таком конфиге не
                # стартует вовсе. Поэтому маску строим, только когда это
                # действительно адрес.
                *(
                    [
                        {
                            "type": "field",
                            "ip": [_host_cidr(server.host)],
                            "port": "22,22222,8000,8080,8081,8443,10085",
                            "outboundTag": "block",
                        }
                    ]
                    if _host_cidr(server.host)
                    else []
                ),
                {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
            ],
        },
    }


def apply_config(db: OrmSession, server: Server) -> None:
    """
    Записывает конфиг на узел и перезагружает демон.

    Через временный файл с переименованием и под тем же замком, что и выдача:
    оборванная запись оставила бы узел с битым JSON, а xray на битом конфиге не
    поднимается вовсе — это отказ всех VLESS-доступов узла разом.
    """
    payload = json.dumps(build_config(db, server), ensure_ascii=False, indent=2)
    # Конфиг уходит через stdin, а не аргументом: в нём приватный ключ Reality
    # и UUID всех клиентов, а командная строка видна каждому, кто смотрит ps.
    #
    # Читает stdin именно `cat`. Через `python3 - <<'PY'` это не работает:
    # heredoc сам занимает стандартный ввод команды, и присланные по SSH данные
    # до скрипта не доходят вовсе — конфиг молча остаётся прежним.
    script = f"""set -e
exec 9>>{XRAY_LOCK}
flock 9
umask 077
tmp="$(mktemp {XRAY_DIR}/.config.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp"
# Битый JSON демон не переживёт: он не поднимется вовсе, а это отказ всех
# доступов узла разом. Проверяем ДО подмены.
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$tmp"
# Владельца и режим восстанавливаем явно: новый файл создан от root, а демон
# работает под своим пользователем и с 0640 просто не смог бы его прочитать.
chown --reference={XRAY_CONFIG} "$tmp" 2>/dev/null || chown root:{SERVICE_USER} "$tmp"
chmod 0640 "$tmp"
mv "$tmp" {XRAY_CONFIG}
sync
"""
    provisioning.run_over_ssh_with_input(server, script, payload)
    # restart, а не reload: xray-core не подписан на SIGHUP, и ExecReload с ним
    # просто убивал бы процесс. Перезапуск рвёт живые VLESS-сессии узла — это
    # цена применения конфига, и поэтому применяем пакетно, а не на каждого.
    provisioning.run_over_ssh(server, f"systemctl restart {XRAY_UNIT}")


def _mark_dirty(db: OrmSession, endpoint: NodeEndpoint) -> None:
    """
    Помечает точку входа как разошедшуюся с узлом.

    `rev` растёт при каждой правке состава клиентов, `applied_rev` — это то,
    что реально записано на узел. Расхождение чинит фоновый обход
    (`sync_pending`), поэтому неудачная запись на узел не остаётся навсегда:
    иначе отзыв доступа жил бы только в базе, а человек продолжал бы ходить.
    """
    endpoint.rev = (endpoint.rev or 1) + 1
    db.commit()


def push_to_node(db: OrmSession, server: Server) -> bool:
    """
    Записывает состав клиентов на узел. Возвращает False, если не вышло.

    Ошибку не поднимаем: отзыв в базе должен состояться в любом случае, а
    расхождение с узлом подхватит `sync_pending` на ближайшем обходе.
    """
    try:
        apply_config(db, server)
    except Exception as exc:  # noqa: BLE001 — недоступный узел не рвёт операцию
        log.warning("узел %s: конфиг VLESS не записан (%s), починим обходом", server.name, exc)
        return False

    applied = utcnow()
    for endpoint in db.scalars(
        select(NodeEndpoint).where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
        )
    ):
        params = dict(endpoint.params or {})
        params["applied_rev"] = endpoint.rev
        params["applied_at"] = applied.isoformat()
        endpoint.params = params
    db.commit()
    return True


def sync_pending(db: OrmSession, server: Server) -> bool:
    """
    Досылает на узел то, что не доехало раньше.

    Зовётся из фонового обхода. Без этого любая неудачная запись (узел не
    ответил, демон перезапускался) означала бы, что отозванный доступ живёт на
    узле до тех пор, пока администратор не нажмёт кнопку руками.
    """
    stale = [
        endpoint
        for endpoint in db.scalars(
            select(NodeEndpoint).where(
                NodeEndpoint.server_id == server.id,
                NodeEndpoint.kind == EndpointKind.VLESS,
                NodeEndpoint.state != EndpointState.DRAFT,
            )
        )
        if (endpoint.params or {}).get("applied_rev") != endpoint.rev
    ]
    if not stale:
        return True
    log.info("узел %s: досылаем конфиг VLESS (%d точек входа)", server.name, len(stale))
    return push_to_node(db, server)


def issue_cred(
    db: OrmSession,
    user: User,
    server: Server,
    endpoint: NodeEndpoint,
    device_id: str = "",
) -> UserEndpointCred:
    """
    Выдаёт доступ VLESS этому устройству. Идемпотентно: живой доступ вернётся
    тем же.

    Двойная запись — сначала в базу и конфиг на диске, потом в живой демон.
    Клиент, добавленный только через API, не переживёт перезапуск демона
    (обновление, OOM, reboot) и молча исчезнет.
    """
    device_id = (device_id or "").strip()
    existing = db.scalar(
        select(UserEndpointCred).where(
            UserEndpointCred.endpoint_id == endpoint.id,
            UserEndpointCred.user_id == user.id,
            UserEndpointCred.device_id == device_id,
        )
    )
    if existing is not None and existing.revoked_at is None:
        return existing

    if not crypto.available():
        raise PanelError("не задан PANEL_SECRETS_KEY — выдать доступ VLESS нечем")

    identity = str(uuid.uuid4())
    params = endpoint.params or {}
    short_ids = params.get("short_ids") or [""]

    if existing is not None:
        cred = existing
        cred.revoked_at = None
    else:
        cred = UserEndpointCred(
            user_id=user.id,
            server_id=server.id,
            endpoint_id=endpoint.id,
            device_id=device_id,
        )
        db.add(cred)

    cred.cred_type = "vless"
    cred.identity_enc = crypto.encrypt(identity)
    cred.identity_fp = crypto.blind_index(identity)
    cred.label = cred.label or _label()
    cred.extra = {
        "flow": params.get("flow", FLOW),
        "short_id": secrets.choice(short_ids),
    }
    db.commit()
    db.refresh(cred)

    # На узел — сразу. Не вышло (узел не ответил) — строку НЕ откатываем: она
    # останется в базе, а расхождение подхватит sync_pending на ближайшем
    # обходе. Откатывать нельзя, иначе каждый запрос подписки при недоступном
    # узле плодил бы новый UUID и тут же его гасил.
    #
    # Рекламировать доступ до того, как он доехал, тоже нельзя: ссылка, которой
    # демон не знает, выглядит рабочей и молча не подключается — человек винит
    # своё устройство. Поэтому наружу его отдаёт только `is_on_node`.
    _mark_dirty(db, endpoint)
    push_to_node(db, server)
    return cred


def is_on_node(endpoint: NodeEndpoint) -> bool:
    """Доехал ли текущий состав клиентов до узла."""
    return (endpoint.params or {}).get("applied_rev") == endpoint.rev


def revoke_cred(db: OrmSession, cred: UserEndpointCred) -> None:
    """
    Снимает доступ: сначала из базы, потом из живого демона.

    Честно: живую TCP-сессию это не рвёт — xray прекращает принимать новые
    подключения этого клиента, но уже открытое соединение доживает само.
    Мгновенный обрыв возможен только перезапуском демона, то есть ценой всех
    VLESS-сессий узла.
    """
    cred.revoked_at = utcnow()
    db.commit()
    endpoint = db.get(NodeEndpoint, cred.endpoint_id)
    if endpoint is not None:
        _mark_dirty(db, endpoint)
        push_to_node(db, endpoint.server)


def revoke_for_user(db: OrmSession, user_id: int, device_id: str | None = None) -> int:
    """
    Снимает доступы VLESS человека (или одного его устройства).

    Запись в базу и запись на узел — разные вещи, и отказ второй не должен
    отменять первую: доступ обязан считаться отозванным даже при недоступном
    узле, а расхождение подхватит `sync_pending` на ближайшем обходе.
    """
    query = select(UserEndpointCred).where(
        UserEndpointCred.user_id == user_id,
        UserEndpointCred.revoked_at.is_(None),
    )
    if device_id is not None:
        query = query.where(UserEndpointCred.device_id == (device_id or "").strip())
    rows = list(db.scalars(query))
    if not rows:
        return 0

    now = utcnow()
    server_ids = set()
    endpoint_ids = set()
    for cred in rows:
        cred.revoked_at = now
        server_ids.add(cred.server_id)
        endpoint_ids.add(cred.endpoint_id)
    db.commit()

    for endpoint_id in endpoint_ids:
        endpoint = db.get(NodeEndpoint, endpoint_id)
        if endpoint is not None:
            _mark_dirty(db, endpoint)
    for server_id in server_ids:
        server = db.get(Server, server_id)
        if server is not None:
            push_to_node(db, server)
    return len(rows)


def live_creds(db: OrmSession, user: User, server: Server, device_id: str = "") -> list[UserEndpointCred]:
    """Живые доступы VLESS этого устройства на этом узле."""
    device_id = (device_id or "").strip()
    return list(
        db.scalars(
            select(UserEndpointCred).where(
                UserEndpointCred.user_id == user.id,
                UserEndpointCred.server_id == server.id,
                UserEndpointCred.device_id == device_id,
                UserEndpointCred.revoked_at.is_(None),
            )
        )
    )


def _parse_stats(raw: str) -> dict[str, tuple[int, int]]:
    """
    Разбирает вывод `xray api statsquery` в «метка → (принято, отдано)».

    Имена счётчиков выглядят как `user>>>метка>>>traffic>>>uplink`. Нулевые
    значения xray в ответе ОПУСКАЕТ — поэтому счётчик без поля `value` это
    ноль, а не повод падать: иначе первый же новый клиент ронял бы весь обход.
    """
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}

    out: dict[str, list[int]] = {}
    for item in data.get("stat") or []:
        name = item.get("name") or ""
        if not name.startswith("user>>>"):
            continue
        parts = name.split(">>>")
        if len(parts) < 4:
            continue
        label, direction = parts[1], parts[-1]
        value = int(item.get("value") or 0)
        bucket = out.setdefault(label, [0, 0])
        if direction == "uplink":
            bucket[0] = value
        elif direction == "downlink":
            bucket[1] = value
    return {label: (values[0], values[1]) for label, values in out.items()}


def sync_traffic(db: OrmSession, server: Server) -> dict[str, object]:
    """
    Снимает счётчики VLESS и прибавляет расход пользователям.

    Зовётся из общего обхода узлов, ПОСЛЕ awg и вне его замка: замок на сервер
    не реентрантный, а считать дельту дважды — ровно тот баг, который им и
    лечили.

    Счётчики xray живут в памяти и обнуляются перезапуском демона, поэтому
    работает та же эвристика, что у awg: значение уехало вниз — считаем текущее
    приростом с нуля, а не отрицательной разницей.
    """
    from sqlalchemy import update as sql_update

    from ..models import TrafficSample

    has_vless = db.scalar(
        select(NodeEndpoint.id).where(
            NodeEndpoint.server_id == server.id,
            NodeEndpoint.kind == EndpointKind.VLESS,
            NodeEndpoint.state != EndpointState.RETIRED,
        )
    )
    if not has_vless:
        return {"server_id": server.id, "skipped": "нет точек входа VLESS"}

    try:
        raw = provisioning.run_over_ssh(
            server,
            f"{XRAY_BIN} api statsquery --server=127.0.0.1:{API_PORT} "
            f"-pattern 'user>>>' -reset=false",
        )
    except Exception as exc:  # noqa: BLE001 — недоступный демон не рвёт обход
        log.warning("узел %s: счётчики VLESS не сняты: %s", server.name, exc)
        return {"server_id": server.id, "error": str(exc)}

    counters = _parse_stats(raw)
    if not counters:
        return {"server_id": server.id, "peers": 0, "added_bytes": 0}

    now = utcnow()
    updated = 0
    added_bytes = 0
    creds = db.scalars(
        select(UserEndpointCred).where(
            UserEndpointCred.server_id == server.id,
            UserEndpointCred.revoked_at.is_(None),
        )
    )
    for cred in creds:
        pair = counters.get(cred.label or "")
        if pair is None:
            continue
        rx, tx = pair
        delta_rx = rx - cred.rx_bytes if rx >= cred.rx_bytes else rx
        delta_tx = tx - cred.tx_bytes if tx >= cred.tx_bytes else tx
        delta = max(0, delta_rx + delta_tx)

        cred.rx_bytes = rx
        cred.tx_bytes = tx
        cred.traffic_synced_at = now
        if delta > 0:
            # Для не-awg это «признак живого соединения», а не рукопожатие:
            # у VLESS рукопожатий в смысле WireGuard нет вовсе.
            cred.last_seen_at = now
            db.execute(
                sql_update(User)
                .where(User.id == cred.user_id)
                .values(traffic_used_bytes=User.traffic_used_bytes + delta)
                .execution_options(synchronize_session="fetch")
            )
            db.add(
                TrafficSample(
                    user_id=cred.user_id,
                    server_id=server.id,
                    delta_bytes=delta,
                    rx_bytes=rx,
                    tx_bytes=tx,
                    sampled_at=now,
                )
            )
            added_bytes += delta
        updated += 1

    db.commit()
    return {"server_id": server.id, "peers": updated, "added_bytes": added_bytes}


def share_link(endpoint: NodeEndpoint, cred: UserEndpointCred, server: Server) -> str | None:
    """
    Ссылка `vless://` — то, что понимают сторонние клиенты.

    Формат конвенционный, а не стандартизованный: имя параметра или его
    отсутствие меняет поведение клиента молча, поэтому набор здесь ровно тот,
    что ждут распространённые сборки.
    """
    identity = cred.identity
    if not identity:
        return None
    params = endpoint.params or {}
    extra = cred.extra or {}
    host = endpoint.public_host(server)
    names = params.get("server_names") or [""]
    query = {
        "type": "tcp",
        "security": "reality",
        "pbk": params.get("public_key", ""),
        "fp": params.get("fingerprint", "chrome"),
        "sni": names[0],
        "sid": extra.get("short_id", ""),
        "flow": extra.get("flow", FLOW),
    }
    from urllib.parse import quote, urlencode

    tail = urlencode({k: v for k, v in query.items() if v})
    name = quote(f"{server.country or server.name}")
    return f"vless://{identity}@{host}:{endpoint.listen_port}?{tail}#{name}"
