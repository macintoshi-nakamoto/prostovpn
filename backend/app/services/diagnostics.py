"""
Проверка узла: работает ли он на самом деле.

Появилось из одного случая, который стоит того, чтобы его описать. Человек
оплатил подписку, ввёл в приложении логин и пароль, вошёл — и ничего не
заработало. Приложение молчало, панель показывала зелёный статус, а причина
была в том, что все узлы в базе были демонстрационными: адреса из RFC 5737
(`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) не маршрутизируются
никуда, и подключаться там было не к чему.

Панель не имела никакого способа это заметить. Сервер считался рабочим,
если администратор поставил галочку «включён», — а включить можно что
угодно. Здесь эта проверка и живёт: пройтись по узлу и сказать
человеческим языком, что с ним не так, до того как это заметит клиент.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass, field

from .. import provisioning
from ..models import Provisioning, Server
from . import traffic

log = logging.getLogger("panel.diagnostics")

# Диапазоны из RFC 5737: зарезервированы под примеры в документации и не
# маршрутизируются в интернете. Настоящий VPN-сервер такого адреса иметь не
# может — это всегда демонстрационные данные, забытые в базе.
DOC_NETWORKS = ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")

# Сколько ждём UDP-порт. AmneziaWG молчит в ответ на мусор, поэтому проверка
# порта здесь означает только «пакет ушёл и ICMP-отказа не пришло».
UDP_TIMEOUT = 3.0


@dataclass(slots=True)
class Check:
    """Один пункт проверки."""

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
    # Системные данные узла, если до него удалось достучаться по SSH.
    facts: dict = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))


def is_documentation_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Домен, а не адрес — проверить нечего, и это нормально.
        return False
    return any(address in ipaddress.ip_network(net) for net in DOC_NETWORKS)


def can_serve(server: Server) -> bool:
    """
    Может ли узел прямо сейчас выдать клиенту рабочий конфиг.

    Быстрая проверка без обращения к сети: используется в сводке, чтобы
    посчитать, сколько узлов вообще на что-то годны.
    """
    if not server.is_active:
        return False
    if is_documentation_address(server.host):
        return False
    if server.provisioning == Provisioning.SHARED:
        return bool(server.shared_config)
    return bool(server.awg_template and server.ssh_host and (server.ssh_key or server.ssh_password))


def check(server: Server) -> Report:
    """Полная проверка узла — с выходом в сеть."""
    report = Report(
        server_id=server.id, server_name=server.name, usable=False, summary="", checks=[]
    )

    # --- адрес ---------------------------------------------------------------
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

    # --- откуда берётся конфиг ----------------------------------------------
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
        if server.awg_template:
            report.add("Шаблон конфига", True, "задан")
        else:
            report.add(
                "Шаблон конфига",
                False,
                "не задан — панель не сможет собрать конфиг для клиента",
            )

    # --- порт ----------------------------------------------------------------
    if server.host and not is_documentation_address(server.host):
        reachable, note = _probe_udp(server.host, server.port)
        report.add(f"Порт {server.port}/UDP", reachable, note)

    # --- SSH и системные данные ----------------------------------------------
    if server.provisioning == Provisioning.SSH:
        _check_ssh(server, report)

    ok = all(c.ok for c in report.checks)
    report.usable = ok and can_serve(server)
    report.summary = _summarize(report)
    return report


# --- системные данные узла ----------------------------------------------------

# Одна команда вместо десяти подключений. Каждое SSH-подключение — это
# рукопожатие и проверка ключа, а их тут было бы по числу показателей;
# собираем всё разом и разбираем на своей стороне.
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
"""


def collect_facts(server: Server) -> dict:
    """
    Системные данные узла одним заходом по SSH.

    Что показывать администратору, решается здесь, а не в вёрстке: панель
    рисует то, что пришло, и не знает, откуда взялось «12 vCPU».
    """
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
        # Без пересылки пакетов трафик клиента не выйдет в интернет: туннель
        # поднимется, а сайты не откроются. Самая частая тихая поломка.
        "ip_forward": values.get("ip_forward") == "1",
        "panel_service": values.get("panel_service") or None,
        "awg_service": values.get("awg_service") or None,
    }

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
    """
    Стучимся в UDP-порт.

    AmneziaWG на мусор не отвечает — это его свойство, а не поломка. Значит,
    «ответа нет» ничего не доказывает, и единственное, что здесь ловится, —
    ICMP «порт недоступен» и неразрешимое имя.

    Сокет обязательно connect(), хотя протокол этого не требует: в Linux ICMP
    «порт недоступен» доставляется сокету, только если он соединён (либо
    выставлен IP_RECVERR) — на несоединённом ядро ошибку молча выбрасывает.
    С sendto() проверка на боевом Linux не могла вернуть «закрыт» вообще
    никогда: узел с упавшим awg-quick всегда показывался рабочим. Ветку с
    Windows оставляем — там отказ приходит и после connect(), но другой
    ошибкой.
    """
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
            # Обычное поведение AmneziaWG: молчит в ответ на неверный пакет.
            # Говорим об этом честно: молчит и выключенный узел тоже —
            # ICMP-отказ шлёт только живая машина без слушателя на порту.
            return True, (
                "ответа нет — для AmneziaWG это норма. Но так же молчит и "
                "недоступный узел: отказа не пришло, большего отсюда не видно"
            )
    except (ConnectionRefusedError, ConnectionResetError):
        # ECONNREFUSED в Linux, WSAECONNRESET в Windows — оба означают
        # дошедший ICMP «порт недоступен». Отказ может прийти и на send(), и
        # на recv(), поэтому ветка одна на обе операции и стоит до OSError:
        # иначе общий обработчик выдал бы размытое «не достучаться».
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

    # Отдельная дешёвая команда только ради факта «SSH работает». Иначе любая
    # ошибка подключения (или отсутствие paramiko — _ssh_connect бросает то же
    # RuntimeError) выглядела бы как «интерфейс не поднят».
    try:
        provisioning.run_over_ssh(server, "true")
    except Exception as exc:
        report.add("SSH", False, str(exc))
        return

    report.add("SSH", True, "подключились")

    # Раз уж подключились — забираем заодно все системные данные. Второе
    # подключение ради них было бы вторым рукопожатием на ровном месте.
    try:
        report.facts = collect_facts(server)
    except Exception as exc:  # pragma: no cover - зависит от узла
        log.warning("данные узла «%s» не собрались: %s", server.name, exc)

    if report.facts.get("awg_version") is None:
        # `awg --version` ничего не сказал: пакета на узле нет. Раньше это
        # проходило как «поднят, пиров: 0» — вывод «awg: not found» непустой,
        # и ни одна из искомых подстрок в нём не встречалась.
        report.add(
            "Интерфейс awg0",
            False,
            "AmneziaWG на узле не установлен: команда awg не найдена",
        )
        return

    try:
        raw = provisioning.run_over_ssh(server, f"awg show {traffic.INTERFACE} dump")
    except Exception as exc:
        # Код возврата больше не гасим: текст ошибки уже содержит stderr узла —
        # и «No such device», и «Operation not permitted». Показываем как есть.
        report.add(
            "Интерфейс awg0",
            False,
            f"{exc}. На сервере: systemctl status awg-quick@awg0",
        )
        return

    lines = raw.strip().splitlines()
    # Первая строка dump — сам интерфейс: у WireGuard в ней четыре поля, у
    # AmneziaWG двенадцать (параметры обфускации). Меньше четырёх — это не
    # дамп, а чужой текст в stdout, и считать по нему пиров нельзя.
    if not lines or len(lines[0].split("\t")) < 4:
        report.add(
            "Интерфейс awg0",
            False,
            "не поднят: awg show не вернул дамп интерфейса. "
            "На сервере: systemctl status awg-quick@awg0",
        )
        return

    # Пиров считаем тем же разбором, что и учёт трафика, а не по числу строк:
    # лишняя строка предупреждения в выводе сдвигала счётчик на единицу.
    report.add("Интерфейс awg0", True, f"поднят, пиров: {len(traffic._parse_dump(raw))}")

    if report.facts.get("ip_forward") is False:
        # Туннель поднимется, клиент увидит «подключено», а сайты не
        # откроются. Ошибка тихая и очень обидная — ловим её отдельно.
        report.add(
            "Пересылка пакетов",
            False,
            "net.ipv4.ip_forward=0 — туннель поднимется, но интернет через него "
            "не пойдёт. Включить: sysctl -w net.ipv4.ip_forward=1",
        )
