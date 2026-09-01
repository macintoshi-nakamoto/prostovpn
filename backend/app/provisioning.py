from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
import socket
import struct
import zlib

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .models import Provisioning, Server, UserKey


def generate_keypair() -> tuple[str, str]:
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes_raw()
    public_raw = private.public_key().public_bytes_raw()
    return base64.b64encode(private_raw).decode(), base64.b64encode(public_raw).decode()


# S3/S4 и I1–I5 — параметры AWG 1.5 (amneziawg v3): I1 маскирует первый пакет
# под DNS-ответ, без него мобильные операторы местами режут рукопожатие.
AWG_PARAMS = (
    "Jc", "Jmin", "Jmax",
    "S1", "S2", "S3", "S4",
    "H1", "H2", "H3", "H4",
    "I1", "I2", "I3", "I4", "I5",
)


def config_sections(config_ini: str) -> tuple[dict[str, str], dict[str, str]]:
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
    return config_sections(config_ini)[0]


def public_key_of(private_key: str) -> str:
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
    body = url[len("vpn://") :] if url.startswith("vpn://") else url
    blob = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    try:
        return json.loads(zlib.decompress(blob[4:]))
    except zlib.error:
        return json.loads(blob)


QR_CHUNK_BYTES = 850

QR_MAGIC = 1984


def build_qr_payload(url: str) -> str | None:
    body = url[len("vpn://") :] if url.startswith("vpn://") else url
    try:
        packed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, binascii.Error):
        return None

    if len(packed) > QR_CHUNK_BYTES:
        return None

    chunk = struct.pack(">hBBI", QR_MAGIC, 1, 0, len(packed)) + packed
    return base64.urlsafe_b64encode(chunk).decode().rstrip("=")


def endpoint_of(config_ini: str) -> str | None:
    for line in config_ini.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped.lower().startswith("endpoint"):
            continue
        value = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
        return value.rsplit(":", 1)[0].strip("[]") or None
    return None


def next_address(taken: list[str], subnet: str = "10.8.1.0/24") -> str:
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
        if host == next(network.hosts()):
            continue
        if host not in used:
            return f"{host}/32"
    raise RuntimeError(f"в подсети {subnet} не осталось свободных адресов")


def render_from_template(template: str, private_key: str, address: str) -> str:
    missing = [name for name in ("{private_key}", "{address}") if name not in template]
    if missing:
        raise ValueError("в шаблоне нет обязательных полей: " + ", ".join(missing))
    return template.replace("{private_key}", private_key).replace("{address}", address)


def render_endpoint_config(endpoint, server: Server, private_key: str, address: str) -> str:
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
    # Порт, который видит клиент, может отличаться от того, что слушает awg:
    # на узлах уже стоят редиректы с запасных портов. 51820 — эталонный порт
    # WireGuard, и у сотовых операторов он под шейпом: рукопожатие проходит,
    # а дальше растут потери. Отдаём тот, что назначен точке входа.
    port = params.get("advertise_port") or endpoint.listen_port

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
        f"Endpoint = {host}:{port}\n"
        f"PersistentKeepalive = {keepalive}\n"
    )


def create_awg_interface(server: Server, endpoint) -> dict[str, str]:
    interface = iface_name(endpoint.handle)
    obfuscation = endpoint.obfuscation()
    if obfuscation is None:
        raise ValueError(f"у точки входа {interface} нет набора обфускации")

    network = ipaddress.ip_network(endpoint.subnet, strict=False)
    gateway = next(network.hosts())
    port = int(endpoint.listen_port)
    if not (0 < port < 65536):
        raise ValueError(f"недопустимый порт {endpoint.listen_port}")

    # Тот же источник, что и у клиентского конфига, — чтобы стороны не
    # разъезжались: параметры точки входа, иначе безопасные 1280.
    mtu = (endpoint.params or {}).get("mtu") or 1280

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
# Тот же MTU, что и в клиентском конфиге. Без этой строки awg-quick берёт
# свои 1420, и получается перекос: клиент шлёт пакеты по 1280 и они
# доходят, а сервер отвечает по 1420 — на сотовой сети, где путь у́же,
# крупные ответы теряются. Рукопожатие проходит, страницы не грузятся.
MTU = {mtu}
{obfuscation.config_lines()}

# Клампинг MSS: у сотовых операторов ICMP часто режут, и определение
# размера пути не работает — тогда TCP шлёт сегменты больше туннеля и
# соединение встаёт. Пришиваем размер к MTU туннеля прямо в SYN.
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -s {network} -o $EGRESS -j MASQUERADE; iptables -t mangle -A FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu; iptables -t mangle -A FORWARD -i %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s {network} -o $EGRESS -j MASQUERADE; iptables -t mangle -D FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu; iptables -t mangle -D FORWARD -i %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

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
    names = [iface_name(name) for name in interfaces]
    if not names:
        return {}
    parts = [
        f"echo '===AWG {name}==='; awg show {name} dump 2>/dev/null || true" for name in names
    ]
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
        result[names[0]] = out
    return result


ENDPOINT_LINE = re.compile(r"(?im)^([ \t]*Endpoint[ \t]*=[ \t]*)(\S+?)(?::(\d+))?[ \t]*$")


def endpoint_port(config: str) -> int | None:
    match = ENDPOINT_LINE.search(config or "")
    if match is None or not match.group(3):
        return None
    return int(match.group(3))


def with_endpoint_port(config: str, port: int) -> str:
    if not config:
        return config
    return ENDPOINT_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}:{port}", config, count=1)


def with_endpoint_host(config: str, host: str) -> str:
    if not config:
        return config

    literal = f"[{host}]" if (":" in host and not host.startswith("[")) else host

    def _sub(m: re.Match) -> str:
        tail = f":{m.group(3)}" if m.group(3) else ""
        return f"{m.group(1)}{literal}{tail}"

    return ENDPOINT_LINE.sub(_sub, config, count=1)


ENCRYPTED_PLACEHOLDER = "__ENCRYPTED__"

PRIVATE_KEY_LINE = re.compile(r"(?im)^([ \t]*PrivateKey[ \t]*=[ \t]*).*$")


def with_private_key(config: str, private_key: str) -> str:
    if not config or not private_key:
        return config
    return PRIVATE_KEY_LINE.sub(lambda m: f"{m.group(1)}{private_key}", config, count=1)


def private_key_for(key: UserKey) -> str:
    if key.private_key_enc:
        from . import crypto

        try:
            return crypto.decrypt(key.private_key_enc)
        except crypto.SecretsUnavailable:
            pass

    value = interface_params(key.config or "").get("PrivateKey", "")
    return "" if value == ENCRYPTED_PLACEHOLDER else value


def config_for(server: Server, key: UserKey | None) -> str | None:
    if server.provisioning == Provisioning.SHARED:
        return server.shared_config
    if key is not None and key.revoked_at is None:
        return key.config
    return None


def serving_config(server: Server, key: UserKey | None) -> str | None:
    base = config_for(server, key)
    if not base:
        return base
    if server.provisioning != Provisioning.SSH or key is None:
        return base
    base = with_endpoint_host(base, server.host)
    private_key = private_key_for(key)
    if not private_key:
        return None
    return with_private_key(base, private_key)


CONNECT_TIMEOUT = 6

COMMAND_TIMEOUT = 30

INTERFACE = "awg0"

AWG_DIR = "/etc/amnezia/amneziawg"

_IFACE_RE = re.compile(r"^awg([0-9]|[1-9][0-9])$")


def iface_name(value: str) -> str:
    name = (value or "").strip()
    if not _IFACE_RE.match(name):
        raise ValueError(f"недопустимое имя интерфейса: {value!r}")
    return name


def config_path(interface: str) -> str:
    return f"{AWG_DIR}/{iface_name(interface)}.conf"


def lock_path(interface: str) -> str:
    return f"{AWG_DIR}/.{iface_name(interface)}.conf.lock"


CONFIG_PATH = config_path(INTERFACE)
LOCK_PATH = lock_path(INTERFACE)

_PEER_BLOCK = """
[Peer]
PublicKey = {public_key}
AllowedIPs = {address}
"""


def add_peer_over_ssh(server: Server, public_key: str, address: str, *, interface: str) -> None:
    interface = iface_name(interface)
    path = config_path(interface)
    lock = lock_path(interface)
    client = _ssh_connect(server)
    try:
        block = _PEER_BLOCK.format(public_key=public_key, address=address)
        commands = [
            f"exec 9>>{lock}; flock 9; printf '%s' {_quote(block)} >> {path}",
            f"awg set {interface} peer {_quote(public_key)} allowed-ips {_quote(address)}",
        ]
        for command in commands:
            _run(client, command)
    finally:
        client.close()


def remove_peer_over_ssh(server: Server, public_key: str, *, interface: str) -> None:
    interface = iface_name(interface)
    conf = config_path(interface)
    lock_file = lock_path(interface)
    client = _ssh_connect(server)
    try:
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
    client = _ssh_connect(server)
    try:
        return _run(client, command)
    finally:
        client.close()


def run_over_ssh_with_input(server: Server, command: str, payload: str) -> str:
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
    except ImportError as exc:
        raise RuntimeError(
            "для серверов с автогенерацией нужен paramiko: pip install paramiko"
        ) from exc

    if not server.ssh_host or not server.ssh_user:
        raise ValueError(f"у сервера «{server.name}» не заданы доступы по SSH")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

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

    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(5)
    return client


def _load_private_key(paramiko, material: str):
    import io

    errors: list[str] = []
    for key_class in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return key_class.from_private_key(io.StringIO(material))
        except Exception as exc:
            errors.append(f"{key_class.__name__}: {exc}")
    raise ValueError("не удалось прочитать приватный ключ SSH — " + "; ".join(errors))


def _run(client, command: str) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=COMMAND_TIMEOUT)
    channel = stdout.channel
    try:
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


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
