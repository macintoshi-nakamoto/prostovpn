"""
Что умеет клиент, судя по тому, как он представился.

Панель отдаёт один и тот же ключ разным приложениям, а понимают они не
одно и то же: строку `I1 = …` (AWG 1.5) старый движок отвергает целиком —
«invalid UAPI device key», и человек остаётся без связи вовсе. Поэтому
новые параметры отдаём только тем, кто их точно разберёт, а остальным —
конфиг без них. Сведения о версиях взяты не из документации, а из самих
сборок: движок в Android-библиотеке (amneziawg-go v3.0.1, есть разбор
«failed to parse I1»), туннель Windows и macOS (v3.1.20260814, есть тест
на ключи i1–i5), AmneziaVPN — с 4.8.5.
"""

from __future__ import annotations

import contextvars
import re

Version = tuple[int, ...]

# С какой версии наше приложение понимает I1–I5. Платформы — как в
# sessions.platform, то есть как клиент назвал себя при входе.
SPECIAL_JUNK_SINCE: dict[str, Version] = {
    "android": (1, 1, 0),
    "windows": (1, 0, 30),
    "macos": (1, 0, 5),
}

# AmneziaVPN представляется в User-Agent подписки как «AmneziaVPN/4.8.7 …».
AMNEZIA_SPECIAL_JUNK_SINCE: Version = (4, 8, 5)

_VERSION = re.compile(r"(\d+(?:\.\d+)+)")


def parse_version(text: str | None) -> Version | None:
    """«1.1.8», «v1.0.31-beta» → (1, 1, 8), (1, 0, 31); мусор → None."""
    match = _VERSION.search(text or "")
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def supports_special_junk(platform: str | None, app_version: str | None) -> bool:
    since = SPECIAL_JUNK_SINCE.get((platform or "").strip().lower())
    if since is None:
        return False
    version = parse_version(app_version)
    return version is not None and version >= since


def amnezia_supports_special_junk(user_agent: str | None) -> bool:
    """
    Только по явно названной версии. Старый AmneziaVPN не представлялся
    вовсе — такому и не отдаём: неизвестно, что у него за движок.
    """
    agent = (user_agent or "").lower()
    at = agent.find("amneziavpn/")
    if at < 0:
        return False
    version = parse_version(agent[at + len("amneziavpn/") :])
    return version is not None and version >= AMNEZIA_SPECIAL_JUNK_SINCE


# --- Поколения AmneziaWG ------------------------------------------------------
#
# 1 — исходный набор (Jc/Jmin/Jmax, S1/S2, фиксированные H1–H4) + I1;
# 2 — S3/S4 и диапазоны заголовков (amneziawg-go v3, «AmneziaWG 2.0»);
# 3 — шифрование заголовков ключом HeaderProtectionKey и случайное
#     дополнение содержимого («AmneziaWG 3.0», июль 2026). 3.0 несовместим
#     со старыми клиентами, 2.0 старый движок тоже отвергает, поэтому ключ
#     каждой точки получают только те, кто её понимает. Кто спрашивает —
#     известно лишь в обработчике запроса (сессия приложения или User-Agent
#     подписки), а решение принимается глубоко в выдаче ключей, так что
#     уровень едет через контекст запроса.
#
# Свои приложения: Android — awg-tunnel.aar на amneziawg-go v3 с
# header_protection_key/content_padding_addition (с 1.1.9 точно эта
# библиотека); Windows — туннель v3.1 умеет всё, но санитайзер конфига до
# 1.0.32 выбрасывал незнакомые строки, 3.0 — с 1.0.33; macOS — 2.0 (3.0 не
# проверен). AmneziaVPN: 2.0 с 4.8.12.9, 3.0 с 5.0.0.5 (docs.amnezia.org,
# wiki.zapret.moe).
AWG_LEVELS: dict[str, list[tuple[Version, int]]] = {
    "android": [((1, 1, 9), 3), ((1, 1, 0), 2)],
    "windows": [((1, 0, 33), 3), ((1, 0, 30), 2)],
    "macos": [((1, 0, 5), 2)],
}

AMNEZIA_LEVELS: list[tuple[Version, int]] = [((5, 0, 0, 5), 3), ((4, 8, 12, 9), 2)]

# Какое поколение наборов AmneziaWG понимает клиент текущего запроса:
# 1, 2 или 3. Ноль — «неизвестно / наборы ему не нужны» (сайт, бот, Happ,
# незнакомый User-Agent): такому новые ключи выдаются на самой старой
# точке, а существующие с места не трогаются.
CLIENT_AWG_LEVEL: contextvars.ContextVar[int] = contextvars.ContextVar("client_awg_level", default=0)


def _level(version: Version | None, table: list[tuple[Version, int]]) -> int:
    if version is None:
        return 1
    for since, level in table:
        if version >= since:
            return level
    return 1


def awg_level(platform: str | None, app_version: str | None) -> int:
    table = AWG_LEVELS.get((platform or "").strip().lower())
    if not table:
        return 1
    return _level(parse_version(app_version), table)


def amnezia_awg_level(user_agent: str | None) -> int:
    agent = (user_agent or "").lower()
    at = agent.find("amneziavpn/")
    if at < 0:
        return 0
    return _level(parse_version(agent[at + len("amneziavpn/") :]), AMNEZIA_LEVELS)
