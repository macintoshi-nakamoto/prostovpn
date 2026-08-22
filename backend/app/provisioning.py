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


def render_endpoint_config(endpoint, server: Server, private_key: str, address: str) -> str:
    """
    Собирает wg-quick для клиента из точки входа, а не из текстового шаблона.

    Порядок строк повторяет `seed.AWG_TEMPLATE` и `deploy/setup-awg.sh` не из
    аккуратности: этот текст разбирают `config_sections`, `with_endpoint_port`,
    `build_vpn_key`, парсер Go у Windows-клиента и `WGQuick.swift` у macOS.
    Перестановка секций или другое написание ключа — это молча не применённый
    параметр, а с обфускацией любой такой промах даёт «пакеты идут, рукопожатия
    нет никогда».
    """
    params = endpoint.params or {}
    obfuscation = endpoint.obfuscation()
    if obfuscation is None:
        raise ValueError(f"у точки входа {endpoint.handle} нет набора обфускации")

    dns = params.get("dns") or "1.1.1.1, 1.0.0.1"
    if isinstance(dns, (list, tuple)):
        dns = ", ".join(dns)
    allowed = params.get("allowed_ips") or "0.0.0.0/0, ::/0"
    if isinstance(allowed, (list, tuple)):
        allowed = ", ".join(allowed)
    mtu = params.get("mtu") or 1280
    keepalive = params.get("keepalive") or 25
    server_public_key = params.get("server_public_key") or ""
    host = endpoint.public_host(server)

    return (
        "[Interface]\n"
        f"Address = {address}\n"
        f"PrivateKey = {private_key}\n"
        f"DNS = {dns}\n"
        f"MTU = {mtu}\n"
        f"{obfuscation.config_lines()}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"AllowedIPs = {allowed}\n"
        f"Endpoint = {host}:{endpoint.listen_port}\n"
        f"PersistentKeepalive = {keepalive}\n"
    )


def create_awg_interface(server: Server, endpoint) -> dict[str, str]:
    """
    Поднимает новый awg-интерфейс на узле и возвращает его публичный ключ.

    Идемпотентно: существующий конфиг не перезаписывается — иначе повторный
    вызов сменил бы набор обфускации под живыми пирами.

    Приватный ключ интерфейса генерируется НА УЗЛЕ и там же остаётся: панели он
    не нужен ни для чего, а перенос его в базу — лишняя поверхность утечки.

    Про `-s <подсеть>` в MASQUERADE. Правило awg0 в deploy/setup-awg.sh стоит
    без него, то есть побуквенно совпало бы с правилом нового интерфейса. А
    `iptables -D` удаляет ПЕРВОЕ совпадение — значит любой `stop` или откат
    нового интерфейса снял бы NAT у пиров awg0: туннель поднят, «подключено»,
    интернета нет. Поэтому подсеть указывается явно.
    """
    interface = iface_name(endpoint.handle)
    obfuscation = endpoint.obfuscation()
    if obfuscation is None:
        raise ValueError(f"у точки входа {interface} нет набора обфускации")

    # Подсеть и адрес узла проверяем как данные, а не как строку: они уезжают
    # в конфиг и в правило iptables на root-машине.
    network = ipaddress.ip_network(endpoint.subnet, strict=False)
    gateway = next(network.hosts())
    port = int(endpoint.listen_port)
    if not (0 < port < 65536):
        raise ValueError(f"недопустимый порт {endpoint.listen_port}")

    conf = config_path(interface)
    lock = lock_path(interface)
    script = f"""set -e
if [ -e {conf} ]; then echo "exists"; awg show {interface} public-key; exit 0; fi
umask 077
awg genkey > {AWG_DIR}/{interface}_private.key
awg pubkey < {AWG_DIR}/{interface}_private.key > {AWG_DIR}/{interface}_public.key
EGRESS=$(ip route show default | awk '/default/{{print $5; exit}}')
cat > {conf} <<CONF
[Interface]
Address = {gateway}/{network.prefixlen}
ListenPort = {port}
PrivateKey = $(cat {AWG_DIR}/{interface}_private.key)
{obfuscation.config_lines()}

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -s {network} -o $EGRESS -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s {network} -o $EGRESS -j MASQUERADE

# Пиры дописывает панель — руками ниже ничего не добавляйте.
CONF
chmod 600 {conf}
touch {lock}; chmod 600 {lock}
systemctl enable --now awg-quick@{interface}
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow {port}/udp >/dev/null || true
  ufw status | grep -q '{port}' || {{ echo "ufw-not-open"; exit 1; }}
fi
awg show {interface} public-key
"""
    client = _ssh_connect(server)
    try:
        out = _run(client, script)
    finally:
        client.close()

    lines = [line.strip() for line in out.splitlines() if line.strip()]
    existed = "exists" in lines
    public_key = lines[-1] if lines else ""
    if not public_key or public_key == "exists":
        raise RuntimeError(f"узел не вернул публичный ключ {interface}: {out!r}")
    return {"public_key": public_key, "existed": "1" if existed else ""}


def dumps_over_ssh(server: Server, interfaces: list[str]) -> dict[str, str]:
    """
    Снимает `awg show <iface> dump` со всех интерфейсов одним заходом SSH.

    Одним, а не по заходу на интерфейс: `_ssh_connect` открывает новое
    соединение на каждый вызов, а обход узлов идёт последовательно в одном
    потоке — недоступный узел иначе множит задержку на число интерфейсов.

    Недоступный интерфейс не рвёт остальные: его вывод пуст, а вызывающий
    отличает пустоту по отсутствию маркера.
    """
    names = [iface_name(name) for name in interfaces]
    if not names:
        return {}
    parts = [
        f"echo '===AWG {name}==='; awg show {name} dump 2>/dev/null || true" for name in names
    ]
    # Через run_over_ssh, а не собственным соединением: SSH-дверь в модуле одна,
    # и подменить её (в тестах, в диагностике) можно в одном месте.
    out = run_over_ssh(server, "; ".join(parts))

    result: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in out.splitlines():
        if line.startswith("===AWG ") and line.endswith("==="):
            if current is not None:
                result[current] = "\n".join(buffer)
            current = line[len("===AWG ") : -3].strip()
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    if current is not None:
        result[current] = "\n".join(buffer)

    if not result and out.strip():
        # Маркеров в выводе нет вовсе — значит команду выполнил не наш скрипт
        # (подменённый транспорт, нестандартный shell). Считаем весь вывод
        # дампом первого интерфейса: это ровно то поведение, что было до
        # мультиинтерфейсности, и оно безопаснее, чем «данных нет».
        result[names[0]] = out
    return result


ENDPOINT_LINE = re.compile(r"(?im)^([ \t]*Endpoint[ \t]*=[ \t]*)(\S+?)(?::(\d+))?[ \t]*$")


def endpoint_port(config: str) -> int | None:
    """Порт из строки Endpoint; None — строки нет или порт не указан."""
    match = ENDPOINT_LINE.search(config or "")
    if match is None or not match.group(3):
        return None
    return int(match.group(3))


def with_endpoint_port(config: str, port: int) -> str:
    """
    Тот же конфиг, но эндпоинт смотрит в другой порт.

    Меняем ровно одну строку и ровно её хвост: в конфиге хватает других
    чисел после «=» и «:» — MTU, junk-параметры, адреса, — и любая менее
    строгая замена однажды испортит ключ вместо порта. Такая порча не
    видна глазом: конфиг остаётся синтаксически верным, а туннель просто
    перестаёт подниматься.
    """
    if not config:
        return config
    return ENDPOINT_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}:{port}", config, count=1)


def with_endpoint_host(config: str, host: str) -> str:
    """
    Тот же конфиг, но эндпоинт смотрит на другой хост, порт не трогаем.

    Ключ к цели «сменил IP ноды — доступ у всех обновился без перевыпуска».
    Раньше host был вшит в текст `key.config` намертво, и переезд узла делал
    все выданные конфиги мусором. Теперь host подставляется из `Server.host`
    в момент отдачи, а хранимый текст остаётся снимком на случай отката.
    """
    if not config:
        return config

    # «Голый» IPv6 (в нём есть «:») обязан быть в скобках, иначе `host:port`
    # не разобрать: 2a01:4f8::1:51820 — где адрес, где порт, непонятно.
    literal = f"[{host}]" if (":" in host and not host.startswith("[")) else host

    def _sub(m: re.Match) -> str:
        tail = f":{m.group(3)}" if m.group(3) else ""
        return f"{m.group(1)}{literal}{tail}"

    return ENDPOINT_LINE.sub(_sub, config, count=1)


# Плейсхолдер на месте вырезанного открытого приватного ключа. Строка
# `PrivateKey = ...` остаётся в конфиге (не пустеет), но реального ключа в ней
# нет — его подставляют при отдаче из `private_key_enc`.
ENCRYPTED_PLACEHOLDER = "__ENCRYPTED__"

PRIVATE_KEY_LINE = re.compile(r"(?im)^([ \t]*PrivateKey[ \t]*=[ \t]*).*$")


def with_private_key(config: str, private_key: str) -> str:
    """
    Подставляет приватный ключ в строку `PrivateKey =` конфига.

    Пустой ключ не подставляем: лучше оставить как есть (или плейсхолдер),
    чем записать `PrivateKey = ` и молча сломать разбор. Меняем ровно строку
    приватного ключа — публичный ключ пира в [Peer] не трогается.
    """
    if not config or not private_key:
        return config
    return PRIVATE_KEY_LINE.sub(lambda m: f"{m.group(1)}{private_key}", config, count=1)


def private_key_for(key: UserKey) -> str:
    """
    Приватный ключ клиента: сначала из шифра, потом откат на открытый текст.

    Единая точка чтения для всех, кто собирает конфиг или ссылку. Пока идёт
    переход, ключ лежит и там и там; после вычистки плейнтекста остаётся только
    шифр. Если шифр не читается (нет/сменили PANEL_SECRETS_KEY) и в тексте уже
    плейсхолдер — возвращаем пустую строку: пусть туннель честно не поднимется,
    чем в конфиг попадёт мусорное `__ENCRYPTED__`.
    """
    if key.private_key_enc:
        from . import crypto

        try:
            return crypto.decrypt(key.private_key_enc)
        except crypto.SecretsUnavailable:
            pass  # откат на открытый текст ниже — он ещё может быть в config

    value = interface_params(key.config or "").get("PrivateKey", "")
    return "" if value == ENCRYPTED_PLACEHOLDER else value


def config_for(server: Server, key: UserKey | None) -> str | None:
    """Что отдать приложению для этого сервера (снимок, без свежего host/ключа)."""
    if server.provisioning == Provisioning.SHARED:
        return server.shared_config
    if key is not None and key.revoked_at is None:
        return key.config
    return None


def serving_config(server: Server, key: UserKey | None) -> str | None:
    """
    Конфиг, готовый к отдаче: свежий host из `Server.host` и расшифрованный
    приватный ключ.

    Порт здесь не трогаем — его выбирает и подставляет вызывающий (подбор
    рабочего порта живёт в api_client). Для SHARED-узлов возвращаем общий
    конфиг как есть: там host принадлежит чужому узлу и подменять его нельзя,
    а приватный ключ общий и в шифровании не участвует.
    """
    base = config_for(server, key)
    if not base:
        return base
    if server.provisioning != Provisioning.SSH or key is None:
        return base
    base = with_endpoint_host(base, server.host)
    private_key = private_key_for(key)
    if not private_key:
        # Приватник не разрешился: шифр не читается (потерян/сменён
        # PANEL_SECRETS_KEY), а открытый текст уже вычищен. Отдать конфиг с
        # плейсхолдером вместо ключа хуже, чем не отдать: туннель молча не
        # поднимется. Роняем узел — вызывающий отсеет его по `if not config`.
        return None
    return with_private_key(base, private_key)


# --- SSH: создание пира на своём сервере -------------------------------------

# Сколько ждём сервер. Держим коротким: раздача ключей идёт по всем серверам
# подряд внутри одного запроса, и каждый недоступный добавляет эту задержку.
CONNECT_TIMEOUT = 6

# Сколько ждём выполнения одной команды на узле.
COMMAND_TIMEOUT = 30

# Интерфейс по умолчанию. Остаётся ради тех, кто ещё не знает про точки входа
# (диагностика старых узлов); новый код обязан передавать имя явно.
INTERFACE = "awg0"

AWG_DIR = "/etc/amnezia/amneziawg"

# Имя интерфейса впервые приезжает из базы в команду, исполняемую на узле от
# root. Поэтому оно не подставляется, а сначала проверяется белым списком:
# строка вида `1/24\nEOF\ncurl …|sh` в этом месте — это выполнение чего угодно
# на машине, где живёт ещё и второй продукт.
_IFACE_RE = re.compile(r"^awg([0-9]|[1-9][0-9])$")


def iface_name(value: str) -> str:
    """Проверенное имя awg-интерфейса. Всё, что не подошло, — исключение."""
    name = (value or "").strip()
    if not _IFACE_RE.match(name):
        raise ValueError(f"недопустимое имя интерфейса: {value!r}")
    return name


def config_path(interface: str) -> str:
    return f"{AWG_DIR}/{iface_name(interface)}.conf"


def lock_path(interface: str) -> str:
    """
    Блокировка живёт в отдельном файле, который никогда не заменяется. Взять её
    на самом конфиге нельзя: конфиг переписывается через переименование, инод по
    этому пути подменяется, и следующий процесс возьмёт блокировку на ДРУГОМ
    иноде — то есть зайдёт внутрь, пока предыдущий ещё там.
    """
    return f"{AWG_DIR}/.{iface_name(interface)}.conf.lock"


CONFIG_PATH = config_path(INTERFACE)
LOCK_PATH = lock_path(INTERFACE)

_PEER_BLOCK = """
[Peer]
PublicKey = {public_key}
AllowedIPs = {address}
"""


def add_peer_over_ssh(server: Server, public_key: str, address: str, *, interface: str) -> None:
    """
    Добавляет пира в конфиг AmneziaWG на сервере и применяет его на лету.

    `awg set` меняет ровно одну запись в ядре: не трогает секцию [Interface] и
    не шевелит чужие сессии — переподключать остальных пользователей из-за
    нового клиента недопустимо.

    `interface` — обязательный именованный параметр без значения по умолчанию.
    Это не педантизм: забытый вызов должен падать, а не молча уходить на awg0.
    Пир, заведённый не на том интерфейсе, потом снимается командой
    `awg set <чужой> peer X remove`, которая возвращает 0 — то есть панель
    считает доступ отозванным, а он продолжает работать.
    """
    interface = iface_name(interface)
    path = config_path(interface)
    lock = lock_path(interface)
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
            f"exec 9>>{lock}; flock 9; printf '%s' {_quote(block)} >> {path}",
            # И применяем немедленно, не трогая существующие сессии
            f"awg set {interface} peer {_quote(public_key)} allowed-ips {_quote(address)}",
        ]
        for command in commands:
            _run(client, command)
    finally:
        client.close()


def remove_peer_over_ssh(server: Server, public_key: str, *, interface: str) -> None:
    """
    Убирает пира: подписка кончилась — доступа быть не должно.

    `interface` обязателен по той же причине, что и в `add_peer_over_ssh`:
    `awg set <не тот интерфейс> peer X remove` завершается успешно и ничего не
    снимает, а вызывающий по коду возврата решает, что доступ отозван.

    Порядок обратный добавлению — сначала постоянный конфиг, потом живой
    интерфейс — и это важно. Вызывающий помечает ключ отозванным только после
    успеха обоих шагов, поэтому падение первого шага должно оставлять узел
    нетронутым: пир жив, запись в базе о живом ключе правдива, повтор
    безопасен. При обратном порядке падение вычистки конфига оставляло пира в
    файле, а из интерфейса он уже был снят: человек терял VPN сейчас и
    получал его обратно после ближайшей перезагрузки узла — уже без всякой
    подписки, потому что в базе ключ числился живым и сверка его не трогала.
    """
    interface = iface_name(interface)
    conf = config_path(interface)
    lock_file = lock_path(interface)
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
            f"path = '{conf}'\n"
            f"lock = os.open('{lock_file}', os.O_CREAT | os.O_RDWR, 0o600)\n"
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
        _run(client, f"awg set {interface} peer {_quote(public_key)} remove")
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


def run_over_ssh_with_input(server: Server, command: str, payload: str) -> str:
    """
    То же, что `run_over_ssh`, но данные уходят в stdin команды.

    Нужна там, где передаётся секрет: аргументы командной строки видны любому
    процессу на узле через `ps`, а конфиг xray несёт приватный ключ Reality и
    UUID всех клиентов.
    """
    client = _ssh_connect(server)
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=COMMAND_TIMEOUT)
        channel = stdout.channel
        try:
            stdin.write(payload)
            stdin.flush()
            stdin.channel.shutdown_write()
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            if not channel.status_event.wait(COMMAND_TIMEOUT):
                raise RuntimeError(f"сервер не вернул код выхода за {COMMAND_TIMEOUT} с")
            code = channel.recv_exit_status()
        except socket.timeout as exc:
            raise RuntimeError(f"сервер не ответил за {COMMAND_TIMEOUT} с") from exc
        finally:
            channel.close()
        if code != 0:
            raise RuntimeError(f"команда на сервере вернула {code}: {err.strip() or out.strip()}")
        return out
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
