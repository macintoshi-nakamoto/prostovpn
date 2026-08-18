"""
Выдача конфигов пользователям.

Два режима, потому что серверы бывают двух видов:

  SHARED — сервер не наш (нет root). Один готовый ключ раздаётся всем.
           Работает всегда, но отозвать доступ одному человеку нельзя.
  SSH    — сервер наш. Панель сама генерирует пару ключей, добавляет пира
           и умеет его убрать, когда подписка кончилась.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import struct
import zlib

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .models import Provisioning, Server, UserKey


def generate_keypair() -> tuple[str, str]:
    """Пара ключей WireGuard в base64 — как их печатает `wg genkey`."""
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes_raw()
    public_raw = private.public_key().public_bytes_raw()
    return base64.b64encode(private_raw).decode(), base64.b64encode(public_raw).decode()


# Параметры обфускации AmneziaWG. Лежат в [Interface] нашего шаблона, а
# клиент ждёт их ещё и рядом с конфигом — как в ссылках, которые он выдаёт
# сам. Совпадать с сервером они обязаны до цифры: разойдись хоть одна —
# рукопожатие не распознаётся вообще.
AWG_PARAMS = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")


def config_sections(config_ini: str) -> tuple[dict[str, str], dict[str, str]]:
    """Разбирает wg-quick на [Interface] и [Peer]."""
    interface: dict[str, str] = {}
    peer: dict[str, str] = {}
    current = None
    for line in config_ini.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("["):
            name = stripped.strip("[]").lower()
            current = interface if name == "interface" else peer if name == "peer" else None
            continue
        if current is None or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        current[name.strip()] = value.strip()
    return interface, peer


def interface_params(config_ini: str) -> dict[str, str]:
    """Значения из секции [Interface] конфига wg-quick."""
    return config_sections(config_ini)[0]


def public_key_of(private_key: str) -> str:
    """Публичный ключ клиента из приватного — то же умножение X25519."""
    raw = base64.b64decode(private_key)
    return base64.b64encode(
        X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes_raw()
    ).decode()


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_vpn_key(
    host: str,
    config_ini: str,
    port: int = 51820,
    name: str | None = None,
    address: str | None = None,
) -> str:
    """
    Собирает ссылку `vpn://` для официального клиента AmneziaVPN.

    Формат неочевидный, и на каждом его пункте ключ ломается молча.

    Первое: клиент строит туннель НЕ из текста `config`, а из отдельных
    полей `last_config` — приватного и публичного ключей, адреса, списка
    маршрутов. Ссылка с одним лишь текстом конфига импортируется, профиль
    поднимается и рвётся за секунду, не отправив ни пакета: на сервере в
    это время по UDP-порту полная тишина. Именно этим битый конфиг
    отличается от несовпавшей обфускации, где пакеты идут, а рукопожатия
    нет.

    Второе: `allowed_ips` — массив, `mtu` и `persistent_keep_alive` —
    строки, `port` внутри `last_config` — число, а в блоке `awg` — строка.
    Пустой `psk_key` не кладём вовсе: пустое значение рискует превратиться
    в `PresharedKey = ` и сломать разбор.

    Третье: канонический вид — сжатый. `vpn://` + base64url без выравнивания
    от qCompress: четыре байта длины исходных данных плюс обычный поток
    zlib. Несжатое клиент тоже понимает, но выдаёт он всегда сжатое.

    `name` уходит в `description` — под этим именем сервер виден в списке
    Amnezia.
    """
    interface, peer = config_sections(config_ini)

    private_key = interface.get("PrivateKey", "")
    client_ip = (address or interface.get("Address", "")).split("/")[0].strip()
    dns = _split_list(interface.get("DNS", ""))
    mtu = interface.get("MTU", "1280")
    junk = {key: interface[key] for key in AWG_PARAMS if key in interface}

    endpoint = peer.get("Endpoint", "")
    endpoint_port = port
    if ":" in endpoint:
        tail = endpoint.rsplit(":", 1)[1]
        if tail.isdigit():
            endpoint_port = int(tail)

    last_config = {
        **junk,
        "allowed_ips": _split_list(peer.get("AllowedIPs", "0.0.0.0/0, ::/0")),
        "client_ip": client_ip,
        "client_priv_key": private_key,
        "client_pub_key": public_key_of(private_key) if private_key else "",
        "config": config_ini,
        "hostName": host,
        "mtu": str(mtu),
        "persistent_keep_alive": str(peer.get("PersistentKeepalive", "25")),
        "port": endpoint_port,
        "server_pub_key": peer.get("PublicKey", ""),
    }

    awg = {
        **junk,
        "mtu": str(mtu),
        # Строкой: в блоке контейнера клиент читает порт как строку.
        "port": str(endpoint_port),
        "transport_proto": "udp",
        "last_config": json.dumps(last_config, ensure_ascii=False),
    }

    payload: dict[str, object] = {
        "containers": [{"container": "amnezia-awg", "awg": awg}],
        "defaultContainer": "amnezia-awg",
        "hostName": host,
    }
    if name:
        payload["description"] = name
    if dns:
        payload["dns1"] = dns[0]
        if len(dns) > 1:
            payload["dns2"] = dns[1]

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    packed = struct.pack(">I", len(raw)) + zlib.compress(raw, 8)
    return "vpn://" + base64.urlsafe_b64encode(packed).decode().rstrip("=")


def read_vpn_key(url: str) -> dict:
    """
    Разбирает ссылку обратно — ровно так, как это делает клиент при импорте.

    Нужна проверкам: собранный ключ должен читаться, а не «выглядеть
    правильно». Понимает оба вида, сжатый и голый.
    """
    body = url[len("vpn://") :] if url.startswith("vpn://") else url
    blob = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    try:
        return json.loads(zlib.decompress(blob[4:]))
    except zlib.error:
        return json.loads(blob)


def endpoint_of(config_ini: str) -> str | None:
    """Хост из строки Endpoint — нужен, чтобы подписать ключ сервером."""
    for line in config_ini.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped.lower().startswith("endpoint"):
            continue
        value = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
        return value.rsplit(":", 1)[0].strip("[]") or None
    return None


def next_address(taken: list[str], subnet: str = "10.8.1.0/24") -> str:
    """
    Свободный адрес в подсети сервера.

    Занятые адреса берём из уже выданных ключей, а не из состояния сервера:
    состояние узла отстаёт, и адрес, только что выданный соседним запросом,
    там ещё не виден. Сам по себе счёт по базе от гонки не спасает — между
    выбором адреса и записью строки идёт целый сеанс SSH. Спасает связка:
    строка с адресом коммитится до захода на узел (services/keys.py) и
    уникальный индекс (server_id, address) на таблице ключей.
    """
    network = ipaddress.ip_network(subnet, strict=False)
    used = set()
    for item in taken:
        if not item:
            continue
        try:
            used.add(ipaddress.ip_address(item.split("/")[0]))
        except ValueError:
            continue
    for host in network.hosts():
        # .1 обычно занят самим сервером
        if host == next(network.hosts()):
            continue
        if host not in used:
            return f"{host}/32"
    raise RuntimeError(f"в подсети {subnet} не осталось свободных адресов")


def render_from_template(template: str, private_key: str, address: str) -> str:
    """
    Подставляет ключ и адрес в шаблон конфига сервера.

    Шаблон — обычный wg-quick, где вместо личных полей стоят
    {private_key} и {address}. Остальное (обфускация, DNS, Endpoint)
    берётся из шаблона как есть.
    """
    missing = [name for name in ("{private_key}", "{address}") if name not in template]
    if missing:
        raise ValueError("в шаблоне нет обязательных полей: " + ", ".join(missing))
    return template.replace("{private_key}", private_key).replace("{address}", address)


def config_for(server: Server, key: UserKey | None) -> str | None:
    """Что отдать приложению для этого сервера."""
    if server.provisioning == Provisioning.SHARED:
        return server.shared_config
    if key is not None and key.revoked_at is None:
        return key.config
    return None


# --- SSH: создание пира на своём сервере -------------------------------------

# Сколько ждём сервер. Держим коротким: раздача ключей идёт по всем серверам
# подряд внутри одного запроса, и каждый недоступный добавляет эту задержку.
CONNECT_TIMEOUT = 6

# Сколько ждём выполнения одной команды на узле.
COMMAND_TIMEOUT = 30

INTERFACE = "awg0"
CONFIG_PATH = f"/etc/amnezia/amneziawg/{INTERFACE}.conf"

# Блокировка живёт в отдельном файле, который никогда не заменяется. Взять её
# на самом конфиге нельзя: конфиг переписывается через переименование, инод по
# этому пути подменяется, и следующий процесс возьмёт блокировку на ДРУГОМ
# иноде — то есть зайдёт внутрь, пока предыдущий ещё там.
LOCK_PATH = f"/etc/amnezia/amneziawg/.{INTERFACE}.conf.lock"

_PEER_BLOCK = """
[Peer]
PublicKey = {public_key}
AllowedIPs = {address}
"""


def add_peer_over_ssh(server: Server, public_key: str, address: str) -> None:
    """
    Добавляет пира в конфиг AmneziaWG на сервере и применяет его на лету.

    `wg addconf` не рвёт уже поднятые соединения — переподключать остальных
    пользователей из-за нового клиента недопустимо.
    """
    client = _ssh_connect(server)
    try:
        block = _PEER_BLOCK.format(public_key=public_key, address=address)
        commands = [
            # Дописываем в постоянный конфиг, чтобы пир пережил перезагрузку.
            # Под той же блокировкой, что и вычистка: flock консультативный, и
            # односторонняя блокировка не спасает — дописанный между чтением и
            # записью пир иначе пропадал из конфига. Разделитель «;», а не
            # «&&», намеренно: если flock на узле не окажется, ключ всё равно
            # выдастся, просто без блокировки.
            f"exec 9>>{LOCK_PATH}; flock 9; printf '%s' {_quote(block)} >> {CONFIG_PATH}",
            # И применяем немедленно, не трогая существующие сессии
            f"awg set {INTERFACE} peer {_quote(public_key)} allowed-ips {_quote(address)}",
        ]
        for command in commands:
            _run(client, command)
    finally:
        client.close()


def remove_peer_over_ssh(server: Server, public_key: str) -> None:
    """
    Убирает пира: подписка кончилась — доступа быть не должно.

    Порядок обратный добавлению — сначала постоянный конфиг, потом живой
    интерфейс — и это важно. Вызывающий помечает ключ отозванным только после
    успеха обоих шагов, поэтому падение первого шага должно оставлять узел
    нетронутым: пир жив, запись в базе о живом ключе правдива, повтор
    безопасен. При обратном порядке падение вычистки конфига оставляло пира в
    файле, а из интерфейса он уже был снят: человек терял VPN сейчас и
    получал его обратно после ближайшей перезагрузки узла — уже без всякой
    подписки, потому что в базе ключ числился живым и сверка его не трогала.
    """
    client = _ssh_connect(server)
    try:
        # Конфиг переписываем целиком, поэтому под блокировкой и через
        # временный файл с переименованием: open(path, 'w') обрезает файл до
        # нуля ещё до записи, и оборвавшийся SSH оставлял узел вообще без
        # пиров.
        escaped = re.escape(public_key)
        _run(
            client,
            "python3 - <<'PY'\n"
            "import fcntl, os, re, tempfile\n"
            f"path = '{CONFIG_PATH}'\n"
            f"lock = os.open('{LOCK_PATH}', os.O_CREAT | os.O_RDWR, 0o600)\n"
            "fcntl.flock(lock, fcntl.LOCK_EX)\n"
            "try:\n"
            "    text = open(path).read()\n"
            f"    text = re.sub(r'\\n\\[Peer\\][^\\[]*{escaped}[^\\[]*', '\\n', text)\n"
            "    keep = os.stat(path)\n"
            "    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))\n"
            "    with os.fdopen(fd, 'w') as out:\n"
            "        out.write(text)\n"
            "        out.flush()\n"
            "        os.fsync(out.fileno())\n"
            "    os.chmod(tmp, keep.st_mode & 0o7777)\n"
            "    os.chown(tmp, keep.st_uid, keep.st_gid)\n"
            "    os.replace(tmp, path)\n"
            "    folder = os.open(os.path.dirname(path), os.O_RDONLY)\n"
            "    os.fsync(folder)\n"
            "    os.close(folder)\n"
            "finally:\n"
            "    os.close(lock)\n"
            "PY",
        )
        _run(client, f"awg set {INTERFACE} peer {_quote(public_key)} remove")
    finally:
        client.close()


def run_over_ssh(server: Server, command: str) -> str:
    """
    Выполняет команду на сервере и возвращает вывод.

    Нужна учёту трафика: тот читает счётчики пиров, а собственного канала к
    серверу у него нет — весь SSH живёт здесь.
    """
    client = _ssh_connect(server)
    try:
        return _run(client, command)
    finally:
        client.close()


def _ssh_connect(server: Server):
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "для серверов с автогенерацией нужен paramiko: pip install paramiko"
        ) from exc

    if not server.ssh_host or not server.ssh_user:
        raise ValueError(f"у сервера «{server.name}» не заданы доступы по SSH")

    client = paramiko.SSHClient()
    # Ключ хоста запоминаем при первом подключении: панель ходит на свои
    # серверы, адреса которых задаёт администратор.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Все три таймаута заданы явно и коротко. Одного `timeout` мало: он
    # ограничивает только установку TCP, а на адресе, где TCP принимают, но
    # SSH не отвечает, подключение висит на ожидании баннера — и вместе с ним
    # висит запрос администратора.
    common = {
        "timeout": CONNECT_TIMEOUT,
        "banner_timeout": CONNECT_TIMEOUT,
        "auth_timeout": CONNECT_TIMEOUT,
    }
    if server.ssh_key:
        pkey = _load_private_key(paramiko, server.ssh_key)
        client.connect(
            server.ssh_host, port=server.ssh_port, username=server.ssh_user, pkey=pkey, **common
        )
    else:
        client.connect(
            server.ssh_host,
            port=server.ssh_port,
            username=server.ssh_user,
            password=server.ssh_password,
            **common,
        )

    # Без keepalive молча оборвавшееся соединение (упал канал, ушёл маршрут)
    # ждёт системного TCP-таймаута — десятки минут удержания потока на узле,
    # которого уже нет.
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(5)
    return client


def _load_private_key(paramiko, material: str):
    """
    Приватный ключ любого распространённого типа.

    Тип по тексту ключа не определить надёжно: OpenSSH с версии 7.8 пишет
    все ключи под одним заголовком `BEGIN OPENSSH PRIVATE KEY`. Поэтому
    перебираем классы по очереди — начиная с ed25519, которым сейчас
    генерируются новые ключи.
    """
    import io

    errors: list[str] = []
    for key_class in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return key_class.from_private_key(io.StringIO(material))
        except Exception as exc:  # не тот тип либо ключ под паролем
            errors.append(f"{key_class.__name__}: {exc}")
    raise ValueError("не удалось прочитать приватный ключ SSH — " + "; ".join(errors))


def _run(client, command: str) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=COMMAND_TIMEOUT)
    channel = stdout.channel
    try:
        # Сначала вывод, потом код возврата — порядок принципиален. `timeout`
        # у exec_command ограничивает чтение канала, а recv_exit_status ждёт
        # события без всякого срока: зависший процесс на узле держал поток
        # вечно. Обход серверов идёт последовательно в одном потоке, поэтому
        # один такой узел останавливал и учёт трафика, и отключение по концу
        # подписки — по всему сервису, до перезапуска панели.
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        if not channel.status_event.wait(COMMAND_TIMEOUT):
            raise RuntimeError(f"сервер не вернул код выхода за {COMMAND_TIMEOUT} с")
        code = channel.recv_exit_status()
    except socket.timeout as exc:
        raise RuntimeError(f"сервер не ответил за {COMMAND_TIMEOUT} с") from exc
    finally:
        # Иначе зависший канал остаётся висеть в транспорте до закрытия сессии
        channel.close()
    if code != 0:
        raise RuntimeError(f"команда на сервере вернула {code}: {err.strip() or out.strip()}")
    return out


def _quote(value: str) -> str:
    """Одинарные кавычки для shell — значения приходят из панели."""
    return "'" + value.replace("'", "'\\''") + "'"
