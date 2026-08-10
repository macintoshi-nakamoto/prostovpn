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

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .models import Provisioning, Server, UserKey


def generate_keypair() -> tuple[str, str]:
    """Пара ключей WireGuard в base64 — как их печатает `wg genkey`."""
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes_raw()
    public_raw = private.public_key().public_bytes_raw()
    return base64.b64encode(private_raw).decode(), base64.b64encode(public_raw).decode()


def build_vpn_key(host: str, config_ini: str, port: int = 51820) -> str:
    """
    Упаковывает wg-quick в ссылку `vpn://` формата Amnezia.

    Так ключ принимают и наши приложения, и официальный клиент Amnezia —
    удобно, когда человека надо быстро проверить чужим клиентом.
    """
    awg = {
        "last_config": json.dumps({"config": config_ini}, ensure_ascii=False),
        "port": port,
        "transport_proto": "udp",
    }
    payload = {
        "hostName": host,
        "containers": [{"container": "amnezia-awg", "awg": awg}],
        "defaultContainer": "amnezia-awg",
    }
    raw = json.dumps(payload, ensure_ascii=False).encode()
    return "vpn://" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


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
    иначе два одновременных создания пользователя получат один адрес.
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
        interface = "awg0"
        commands = [
            # Дописываем в постоянный конфиг, чтобы пир пережил перезагрузку
            f"printf '%s' {_quote(block)} >> /etc/amnezia/amneziawg/{interface}.conf",
            # И применяем немедленно, не трогая существующие сессии
            f"awg set {interface} peer {_quote(public_key)} allowed-ips {_quote(address)}",
        ]
        for command in commands:
            _run(client, command)
    finally:
        client.close()


def remove_peer_over_ssh(server: Server, public_key: str) -> None:
    """Убирает пира: подписка кончилась — доступа быть не должно."""
    client = _ssh_connect(server)
    try:
        interface = "awg0"
        _run(client, f"awg set {interface} peer {_quote(public_key)} remove")
        # И вычищаем из постоянного конфига, иначе вернётся после перезагрузки
        escaped = re.escape(public_key)
        _run(
            client,
            "python3 - <<'PY'\n"
            "import re\n"
            f"path = '/etc/amnezia/amneziawg/{interface}.conf'\n"
            "text = open(path).read()\n"
            f"text = re.sub(r'\\n\\[Peer\\][^\\[]*{escaped}[^\\[]*', '\\n', text)\n"
            "open(path, 'w').write(text)\n"
            "PY",
        )
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
    if server.ssh_key:
        import io

        pkey = paramiko.RSAKey.from_private_key(io.StringIO(server.ssh_key))
        client.connect(
            server.ssh_host, port=server.ssh_port, username=server.ssh_user, pkey=pkey, timeout=15
        )
    else:
        client.connect(
            server.ssh_host,
            port=server.ssh_port,
            username=server.ssh_user,
            password=server.ssh_password,
            timeout=15,
        )
    return client


def _run(client, command: str) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=30)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    if code != 0:
        raise RuntimeError(f"команда на сервере вернула {code}: {err.strip() or out.strip()}")
    return out


def _quote(value: str) -> str:
    """Одинарные кавычки для shell — значения приходят из панели."""
    return "'" + value.replace("'", "'\\''") + "'"
