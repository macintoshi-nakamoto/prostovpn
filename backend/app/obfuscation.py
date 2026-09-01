from __future__ import annotations

import re
import secrets as _secrets
from dataclasses import dataclass

FIELDS = ("jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4")

RESERVED_HEADERS = frozenset({0, 1, 2, 3, 4})

H_MIN = 5
H_MAX = 2**31 - 1

INIT_BASE = 148
RESPONSE_BASE = 92

JC_MIN, JC_MAX = 3, 6
S_MIN, S_MAX = 15, 130
JMIN_LO, JMIN_HI = 16, 64
JMAX_LO, JMAX_HI = 256, 1000

JMIN_FLOOR = 1
JMAX_CEILING = 1280


class InvalidObfuscation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObfuscationSet:

    jc: int
    jmin: int
    jmax: int
    s1: int
    s2: int
    h1: int
    h2: int
    h3: int
    h4: int

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in FIELDS}

    def config_lines(self) -> str:
        return "\n".join(
            f"{name} = {value}"
            for name, value in (
                ("Jc", self.jc),
                ("Jmin", self.jmin),
                ("Jmax", self.jmax),
                ("S1", self.s1),
                ("S2", self.s2),
                ("H1", self.h1),
                ("H2", self.h2),
                ("H3", self.h3),
                ("H4", self.h4),
            )
        )


def _as_int(values: dict, name: str) -> int:
    if name not in values:
        raise InvalidObfuscation(f"не хватает параметра {name.upper()}")
    value = values[name]
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise InvalidObfuscation(f"{name.upper()} должен быть целым числом") from None
    return value


def validate(values: dict | ObfuscationSet, *, strict: bool = True) -> ObfuscationSet:
    if isinstance(values, ObfuscationSet):
        values = values.as_dict()

    parsed = {name: _as_int(values, name) for name in FIELDS}

    headers = [parsed["h1"], parsed["h2"], parsed["h3"], parsed["h4"]]
    for index, value in enumerate(headers, start=1):
        if value in RESERVED_HEADERS:
            raise InvalidObfuscation(
                f"H{index} = {value} — это служебный тип пакета WireGuard, "
                f"заголовок с ним выдаёт протокол; нужно ≥ {H_MIN}"
            )
        if not (H_MIN <= value <= H_MAX):
            raise InvalidObfuscation(f"H{index} должен быть от {H_MIN} до {H_MAX}, а не {value}")
    if len(set(headers)) != 4:
        raise InvalidObfuscation("H1..H4 должны быть четырьмя разными числами")

    s1, s2 = parsed["s1"], parsed["s2"]
    if s1 < 0 or s2 < 0:
        raise InvalidObfuscation("S1 и S2 не могут быть отрицательными")
    if INIT_BASE + s1 == RESPONSE_BASE + s2:
        raise InvalidObfuscation(
            f"S1 и S2 дают пакеты одной длины ({INIT_BASE + s1}): "
            f"рукопожатие вычисляется по размеру, нужно S1 + {INIT_BASE} ≠ S2 + {RESPONSE_BASE}"
        )

    jmin, jmax = parsed["jmin"], parsed["jmax"]
    if jmin < JMIN_FLOOR:
        raise InvalidObfuscation(f"Jmin должен быть не меньше {JMIN_FLOOR}")
    if jmax <= jmin:
        raise InvalidObfuscation(f"Jmax ({jmax}) должен быть больше Jmin ({jmin})")
    if jmax > JMAX_CEILING:
        raise InvalidObfuscation(f"Jmax больше {JMAX_CEILING} — пакет не пройдёт целиком")

    if strict:
        jc = parsed["jc"]
        if not (JC_MIN <= jc <= JC_MAX):
            raise InvalidObfuscation(f"Jc должен быть от {JC_MIN} до {JC_MAX}, а не {jc}")
        for name in ("s1", "s2"):
            if not (S_MIN <= parsed[name] <= S_MAX):
                raise InvalidObfuscation(
                    f"{name.upper()} должен быть от {S_MIN} до {S_MAX}, а не {parsed[name]}"
                )
        if not (JMIN_LO <= jmin <= JMIN_HI):
            raise InvalidObfuscation(f"Jmin должен быть от {JMIN_LO} до {JMIN_HI}, а не {jmin}")
        if not (JMAX_LO <= jmax <= JMAX_HI):
            raise InvalidObfuscation(f"Jmax должен быть от {JMAX_LO} до {JMAX_HI}, а не {jmax}")

    return ObfuscationSet(**parsed)


def generate(rng=None) -> ObfuscationSet:
    rng = rng or _secrets.SystemRandom()

    jc = rng.randint(JC_MIN, JC_MAX)
    jmin = rng.randint(JMIN_LO, JMIN_HI)
    jmax = rng.randint(JMAX_LO, JMAX_HI)

    s1 = rng.randint(S_MIN, S_MAX)
    forbidden = s1 + INIT_BASE - RESPONSE_BASE
    s2 = rng.choice([value for value in range(S_MIN, S_MAX + 1) if value != forbidden])

    h1, h2, h3, h4 = rng.sample(range(H_MIN, H_MAX + 1), 4)

    return validate(
        {"jc": jc, "jmin": jmin, "jmax": jmax, "s1": s1, "s2": s2,
         "h1": h1, "h2": h2, "h3": h3, "h4": h4},
        strict=True,
    )


def from_config_text(config: str, *, strict: bool = False) -> ObfuscationSet:
    from .provisioning import interface_params

    interface = interface_params(config or "")
    values = {name: interface.get(name.capitalize() if name.startswith("j") else name.upper())
              for name in FIELDS}
    missing = [name.upper() for name, value in values.items() if value is None]
    if missing:
        raise InvalidObfuscation("в конфиге нет параметров: " + ", ".join(missing))
    return validate(values, strict=strict)


# ---------------------------------------------------------------------------
# AWG 1.5: сигнатурные пакеты I1–I5
# ---------------------------------------------------------------------------
#
# Jc/Jmin/Jmax и S1/S2 прячут размер рукопожатия, но сама картина — серия
# случайного мусора и следом пакет ровно в 148+S1 байт — со временем стала
# приметой. I-пакеты клиент шлёт ПЕРЕД рукопожатием, и их содержимое задаём
# мы: первое, что видит DPI на потоке, — «настоящий» пакет знакомого
# протокола. Сервер такие пакеты просто отбрасывает, поэтому в серверный
# конфиг они не попадают и старым клиентам не мешают: кто не умеет I1,
# тому строки не отдаём (см. services/compat.py).
#
# Язык значения — теги amneziawg-go:
#   <b 0xHEX>  байты как есть      <r N>   N случайных байт
#   <c>        счётчик, 4 байта    <rc N>  N случайных букв/цифр
#   <t>        время, 4 байта      <rd N>  N случайных цифр

SPECIAL_FIELDS = ("i1", "i2", "i3", "i4", "i5")

# Пакет QUIC v1 Initial, каким его шлёт браузер: длинный заголовок (0xc4),
# версия 1, восьмибайтный DCID, пустые SCID и токен, длина 1182 и
# «зашифрованное» тело до ровно 1200 байт — минимального размера Initial по
# RFC 9000. На UDP/443 это неотличимо от открытия сайта по HTTP/3.
QUIC_INITIAL = "<b 0xc40000000108><r 8><b 0x0000449e><r 1182>"

# Больше одного MTU пакет не пройдёт целиком, а движок такого и не примет.
SPECIAL_MAX_BYTES = 1280

_TAG = re.compile(r"<\s*(b|c|t|r|rc|rd)(?:\s+([^<>]*?))?\s*>")


def special_junk_size(value: str) -> int:
    """
    Сколько байт уйдёт в сеть по описанию пакета; заодно проверяет синтаксис.
    """
    text = (value or "").strip()
    if not text:
        return 0
    size = 0
    pos = 0
    for match in _TAG.finditer(text):
        if text[pos : match.start()].strip():
            raise InvalidObfuscation(f"лишний текст вне тегов: {text[pos:match.start()]!r}")
        pos = match.end()
        tag, arg = match.group(1), (match.group(2) or "").strip()
        if tag == "b":
            body = arg[2:] if arg.lower().startswith("0x") else ""
            if not body or len(body) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", body):
                raise InvalidObfuscation(f"<b> ждёт чётное число hex-цифр после 0x, а не {arg!r}")
            size += len(body) // 2
        elif tag in ("c", "t"):
            if arg:
                raise InvalidObfuscation(f"<{tag}> без аргументов")
            size += 4
        else:
            if not arg.isdigit() or int(arg) <= 0:
                raise InvalidObfuscation(f"<{tag}> ждёт число байт, а не {arg!r}")
            size += int(arg)
    if text[pos:].strip():
        raise InvalidObfuscation(f"лишний текст вне тегов: {text[pos:]!r}")
    if size > SPECIAL_MAX_BYTES:
        raise InvalidObfuscation(f"пакет {size} байт не пройдёт целиком: предел {SPECIAL_MAX_BYTES}")
    return size


def special_junk(params: dict | None, *, strict: bool = True) -> dict[str, str]:
    """
    I1–I5 из параметров точки входа: имя → описание пакета, пустые пропущены.

    strict — падать на кривом значении; иначе такое просто не отдаём:
    выдача ключа важнее одного лишнего пакета.
    """
    out: dict[str, str] = {}
    for name in SPECIAL_FIELDS:
        raw = (params or {}).get(name)
        value = str(raw).strip() if raw is not None else ""
        if not value:
            continue
        try:
            special_junk_size(value)
        except InvalidObfuscation:
            if strict:
                raise
            continue
        out[name] = value
    return out


def special_lines(params: dict | None, *, strict: bool = False) -> str:
    return "\n".join(
        f"{name.upper()} = {value}" for name, value in special_junk(params, strict=strict).items()
    )
