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
