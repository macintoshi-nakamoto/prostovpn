from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass, field

from .. import provisioning
from ..models import EndpointKind, Provisioning, Server
from . import traffic

log = logging.getLogger("panel.diagnostics")

DOC_NETWORKS = ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")

UDP_TIMEOUT = 3.0


@dataclass(slots=True)
class Check:

    name: str
    ok: bool
    detail: str = ""


@dataclass(slots=True)
class Report:
    server_id: int
    server_name: str
    usable: bool
    summary: str
    checks: list[Check] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))


def is_documentation_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(net) for net in DOC_NETWORKS)


def can_serve(server: Server) -> bool:
    if not server.is_active:
        return False
    if is_documentation_address(server.host):
        return False
    if server.provisioning == Provisioning.SHARED:
        return bool(server.shared_config)
    if not (server.ssh_host and (server.ssh_key or server.ssh_password)):
        return False
    # Шаблон конфига — наследие времён, когда точек входа не было и параметры
    # обфускации лежали прямо на узле. Узел, заведённый через точки входа,
    # шаблона не имеет вовсе, и конфиг ему собирают из endpoint.params —
    # требовать шаблон значит объявить исправный узел неработоспособным.
    if server.awg_template:
        return True
    return any(
        ep.kind == EndpointKind.AWG and ep.is_live for ep in server.endpoints
    )


def check(server: Server) -> Report:
    report = Report(
        server_id=server.id, server_name=server.name, usable=False, summary="", checks=[]
    )

    if not server.host:
        report.add("Адрес", False, "не задан")
    elif is_documentation_address(server.host):
        report.add(
            "Адрес",
            False,
            f"{server.host} — из диапазона для примеров в документации. "
            "Такой адрес никуда не ведёт: это демонстрационные данные, "
            "их надо заменить настоящим адресом сервера.",
        )
    else:
        report.add("Адрес", True, f"{server.host}:{server.port}")

    if server.provisioning == Provisioning.SHARED:
        if server.shared_config:
            report.add("Общий конфиг", True, f"{len(server.shared_config)} символов")
        else:
            report.add(
                "Общий конфиг",
                False,
                "режим «общий ключ», но сам ключ не вставлен — выдавать клиенту нечего",
            )
    else:
        live_awg = [
            ep for ep in server.endpoints if ep.kind == EndpointKind.AWG and ep.is_live
        ]
        if server.awg_template:
            report.add("Шаблон конфига", True, "задан")
        elif live_awg:
            # Узлу с точками входа шаблон не нужен: конфиг собирается из их
            # параметров. Ругаться на его отсутствие значит объявлять
            # исправный узел сломанным.
            report.add(
                "Шаблон конфига",
                True,
                "не нужен: конфиг собирается из точек входа ("
                + ", ".join(ep.handle for ep in live_awg)
                + ")",
            )
        else:
            report.add(
                "Шаблон конфига",
                False,
                "не задан, и живых точек входа нет — собрать конфиг клиенту не из чего",
            )

    if server.host and not is_documentation_address(server.host):
        reachable, note = _probe_udp(server.host, server.port)
        report.add(f"Порт {server.port}/UDP", reachable, note)

    if server.provisioning == Provisioning.SSH:
        _check_ssh(server, report)

    ok = all(c.ok for c in report.checks)
    report.usable = ok and can_serve(server)
    report.summary = _summarize(report)
    return report


_FACTS_SCRIPT = r"""
echo "os=$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -s )"
echo "kernel=$(uname -r)"
echo "arch=$(uname -m)"
echo "hostname=$(hostname)"
echo "uptime_seconds=$(cut -d. -f1 /proc/uptime 2>/dev/null)"
echo "load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"
echo "cpu_count=$(nproc 2>/dev/null)"
echo "cpu_model=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//')"
echo "mem_total_kb=$(grep -m1 MemTotal /proc/meminfo 2>/dev/null | tr -dc 0-9)"
echo "mem_available_kb=$(grep -m1 MemAvailable /proc/meminfo 2>/dev/null | tr -dc 0-9)"
echo "disk=$(df -B1 --output=size,used,avail / 2>/dev/null | tail -1 | tr -s ' ')"
echo "awg_version=$(awg --version 2>/dev/null | head -1)"
echo "awg_module=$(lsmod 2>/dev/null | grep -c '^amneziawg' )"
echo "iface_up=$(ip link show awg0 >/dev/null 2>&1 && echo 1 || echo 0)"
echo "iface_addr=$(ip -4 -o addr show awg0 2>/dev/null | awk '{print $4}')"
echo "iface_stats=$(cat /sys/class/net/awg0/statistics/rx_bytes /sys/class/net/awg0/statistics/tx_bytes 2>/dev/null | tr '\n' ' ')"
echo "peers=$(awg show awg0 peers 2>/dev/null | grep -c .)"
echo "listen_port=$(awg show awg0 listen-port 2>/dev/null)"
echo "public_ip=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null)"
echo "ip_forward=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null)"
echo "panel_service=$(systemctl is-active prosto-panel 2>/dev/null)"
echo "awg_service=$(systemctl is-active awg-quick@awg0 2>/dev/null)"
echo "xray_service=$(systemctl is-active prosto-xray 2>/dev/null)"
# Все awg-интерфейсы узла: по строке на каждый. Нужны, чтобы панель видела
# интерфейс, поднятый мимо неё, — такой невидим и для учёта, и для сверки.
for _i in $(ls /etc/amnezia/amneziawg/awg*.conf 2>/dev/null | sed 's#.*/##; s#\\.conf$##'); do
  echo "iface:$_i=$(ip link show $_i >/dev/null 2>&1 && echo up || echo down),$(awg show $_i listen-port 2>/dev/null),$(awg show $_i peers 2>/dev/null | grep -c .)"
done
"""


def collect_facts(server: Server) -> dict:
    raw = provisioning.run_over_ssh(server, _FACTS_SCRIPT)

    values: dict[str, str] = {}
    for line in raw.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key.strip()] = value.strip()

    def as_int(key: str) -> int | None:
        try:
            return int(values.get(key, ""))
        except (TypeError, ValueError):
            return None

    disk = (values.get("disk") or "").split()
    stats = (values.get("iface_stats") or "").split()

    facts: dict = {
        "os": values.get("os") or None,
        "kernel": values.get("kernel") or None,
        "arch": values.get("arch") or None,
        "hostname": values.get("hostname") or None,
        "uptime_seconds": as_int("uptime_seconds"),
        "load": values.get("load") or None,
        "cpu_count": as_int("cpu_count"),
        "cpu_model": values.get("cpu_model") or None,
        "mem_total_bytes": (as_int("mem_total_kb") or 0) * 1024 or None,
        "mem_available_bytes": (as_int("mem_available_kb") or 0) * 1024 or None,
        "awg_version": values.get("awg_version") or None,
        "awg_module_loaded": (as_int("awg_module") or 0) > 0,
        "interface_up": values.get("iface_up") == "1",
        "interface_address": values.get("iface_addr") or None,
        "peers": as_int("peers"),
        "listen_port": as_int("listen_port"),
        "public_ip": values.get("public_ip") or None,
        "ip_forward": values.get("ip_forward") == "1",
        "panel_service": values.get("panel_service") or None,
        "awg_service": values.get("awg_service") or None,
        "xray_service": values.get("xray_service") or None,
    }

    interfaces: list[dict] = []
    total_peers = 0
    for key, value in values.items():
        if not key.startswith("iface:"):
            continue
        name = key[len("iface:") :]
        parts = (value or "").split(",")
        up = parts[0] == "up" if parts else False
        port = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        peers = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        interfaces.append({"name": name, "up": up, "listen_port": port, "peers": peers})
        total_peers += peers
    if interfaces:
        facts["interfaces"] = sorted(interfaces, key=lambda item: item["name"])
        facts["peers"] = total_peers

    if len(disk) >= 3:
        facts["disk_total_bytes"] = int(disk[0]) if disk[0].isdigit() else None
        facts["disk_used_bytes"] = int(disk[1]) if disk[1].isdigit() else None
        facts["disk_free_bytes"] = int(disk[2]) if disk[2].isdigit() else None
    if len(stats) >= 2:
        facts["interface_rx_bytes"] = int(stats[0]) if stats[0].isdigit() else None
        facts["interface_tx_bytes"] = int(stats[1]) if stats[1].isdigit() else None

    return facts


def _summarize(report: Report) -> str:
    failed = [c for c in report.checks if not c.ok]
    if not failed:
        return "Узел рабочий: конфиг соберётся, клиент подключится."
    if len(failed) == 1:
        return f"Не работает: {failed[0].name.lower()} — {failed[0].detail}"
    return "Не работает: " + "; ".join(f"{c.name.lower()}" for c in failed)


def _probe_udp(host: str, port: int) -> tuple[bool, str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_UDP)
    except socket.gaierror as exc:
        return False, f"имя не разрешается: {exc}"

    family, socktype, proto, _canon, address = infos[0]
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(UDP_TIMEOUT)
    try:
        sock.connect(address)
        sock.send(b"\x00" * 16)
        try:
            sock.recv(64)
            return True, "порт отвечает"
        except socket.timeout:
            return True, (
                "ответа нет — для AmneziaWG это норма. Но так же молчит и "
                "недоступный узел: отказа не пришло, большего отсюда не видно"
            )
    except (ConnectionRefusedError, ConnectionResetError):
        return False, "порт закрыт: сервер не слушает или его режет файрвол"
    except OSError as exc:
        return False, f"не достучаться: {exc}"
    finally:
        sock.close()


def _check_ssh(server: Server, report: Report) -> None:
    if not server.ssh_host:
        report.add("SSH", False, "адрес не задан — панель не сможет завести пира")
        return
    if not (server.ssh_key or server.ssh_password):
        report.add("SSH", False, "нет ни ключа, ни пароля")
        return

    try:
        provisioning.run_over_ssh(server, "true")
    except Exception as exc:
        report.add("SSH", False, str(exc))
        return

    report.add("SSH", True, "подключились")

    try:
        report.facts = collect_facts(server)
    except Exception as exc:
        log.warning("данные узла «%s» не собрались: %s", server.name, exc)

    if report.facts.get("awg_version") is None:
        report.add(
            "Интерфейс awg0",
            False,
            "AmneziaWG на узле не установлен: команда awg не найдена",
        )
        return

    try:
        raw = provisioning.run_over_ssh(server, f"awg show {traffic.INTERFACE} dump")
    except Exception as exc:
        report.add(
            "Интерфейс awg0",
            False,
            f"{exc}. На сервере: systemctl status awg-quick@awg0",
        )
        return

    lines = raw.strip().splitlines()
    if not lines or len(lines[0].split("\t")) < 4:
        report.add(
            "Интерфейс awg0",
            False,
            "не поднят: awg show не вернул дамп интерфейса. "
            "На сервере: systemctl status awg-quick@awg0",
        )
        return

    report.add("Интерфейс awg0", True, f"поднят, пиров: {len(traffic._parse_dump(raw))}")

    if report.facts.get("ip_forward") is False:
        report.add(
            "Пересылка пакетов",
            False,
            "net.ipv4.ip_forward=0 — туннель поднимется, но интернет через него "
            "не пойдёт. Включить: sysctl -w net.ipv4.ip_forward=1",
        )
