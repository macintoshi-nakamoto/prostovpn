from __future__ import annotations

import re
import secrets as _secrets
from dataclasses import dataclass

FIELDS = ("jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4")

# AmneziaWG 2.0 (amneziawg-go v3): S3 — мусор в cookie-ответе, S4 — мусор в
# КАЖДОМ транспортном пакете (размеры перестают быть «почерком» WireGuard),
# H1–H4 — диапазоны «min-max», из которых заголовок выбирается на каждый
# пакет. Старые движки (AmneziaVPN < 4.8.12.9, amneziawg-go v0.2) такие
# строки не понимают, поэтому наборы 2.0 живут на отдельной точке входа.
FIELDS_V2 = ("s3", "s4")

RESERVED_HEADERS = frozenset({0, 1, 2, 3, 4})

H_MIN = 5
H_MAX = 2**32 - 1

INIT_BASE = 148
RESPONSE_BASE = 92

JC_MIN, JC_MAX = 3, 6
S_MIN, S_MAX = 15, 130
JMIN_LO, JMIN_HI = 16, 64
JMAX_LO, JMAX_HI = 256, 1000

JMIN_FLOOR = 1
JMAX_CEILING = 1280

# Границы наборов 2.0 — как у живых конфигов, которые проходят на сотовых
# сетях (Jc = 4, Jmin 161–230, Jmax 649–823, S1 56–73, S2 118–149,
# S3 12–36, S4 12–18, диапазоны заголовков шириной 6–50 тысяч).
V2_JC = 4
V2_JMIN = (120, 240)
V2_JMAX = (600, 900)
V2_S1 = (40, 90)
V2_S2 = (100, 160)
V2_S3 = (10, 40)
V2_S4 = (10, 24)
V2_S_MAX = 64
V2_H_WIDTH = (8_000, 40_000)
V2_H_BASE = (2**24, 2**32 - 2**17)

Header = int | str

_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


class InvalidObfuscation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObfuscationSet:

    jc: int
    jmin: int
    jmax: int
    s1: int
    s2: int
    h1: Header
    h2: Header
    h3: Header
    h4: Header
    s3: int = 0
    s4: int = 0

    @property
    def version(self) -> int:
        if self.s3 or self.s4:
            return 2
        if any(isinstance(getattr(self, name), str) for name in ("h1", "h2", "h3", "h4")):
            return 2
        return 1

    def as_dict(self) -> dict:
        out = {name: getattr(self, name) for name in FIELDS}
        if self.s3 or self.s4:
            out["s3"] = self.s3
            out["s4"] = self.s4
        return out

    def config_lines(self) -> str:
        pairs: list[tuple[str, object]] = [
            ("Jc", self.jc),
            ("Jmin", self.jmin),
            ("Jmax", self.jmax),
            ("S1", self.s1),
            ("S2", self.s2),
        ]
        # S3/S4 пишем только у наборов 2.0: старый движок незнакомую строку
        # отвергает вместе со всем конфигом.
        if self.s3 or self.s4:
            pairs += [("S3", self.s3), ("S4", self.s4)]
        pairs += [("H1", self.h1), ("H2", self.h2), ("H3", self.h3), ("H4", self.h4)]
        return "\n".join(f"{name} = {value}" for name, value in pairs)


def _as_int(values: dict, name: str, *, default: int | None = None) -> int:
    if name not in values or values[name] is None or values[name] == "":
        if default is not None:
            return default
        raise InvalidObfuscation(f"не хватает параметра {name.upper()}")
    value = values[name]
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise InvalidObfuscation(f"{name.upper()} должен быть целым числом") from None
    return value


def _as_header(values: dict, name: str) -> Header:
    if name not in values:
        raise InvalidObfuscation(f"не хватает параметра {name.upper()}")
    value = values[name]
    if isinstance(value, str):
        match = _RANGE.match(value)
        if match:
            lo, hi = int(match.group(1)), int(match.group(2))
            if lo >= hi:
                raise InvalidObfuscation(f"{name.upper()}: диапазон {value.strip()} пуст")
            return f"{lo}-{hi}"
    return _as_int(values, name)


def _bounds(value: Header) -> tuple[int, int]:
    if isinstance(value, str):
        lo, hi = value.split("-", 1)
        return int(lo), int(hi)
    return value, value


def validate(values: dict | ObfuscationSet, *, strict: bool = True) -> ObfuscationSet:
    if isinstance(values, ObfuscationSet):
        values = values.as_dict()

    parsed: dict = {name: _as_int(values, name) for name in ("jc", "jmin", "jmax", "s1", "s2")}
    for name in ("h1", "h2", "h3", "h4"):
        parsed[name] = _as_header(values, name)
    for name in FIELDS_V2:
        parsed[name] = _as_int(values, name, default=0)

    spans: list[tuple[int, int]] = []
    for index, name in enumerate(("h1", "h2", "h3", "h4"), start=1):
        lo, hi = _bounds(parsed[name])
        if lo in RESERVED_HEADERS or hi in RESERVED_HEADERS or lo < H_MIN:
            raise InvalidObfuscation(
                f"H{index} = {parsed[name]} — это служебный тип пакета WireGuard, "
                f"заголовок с ним выдаёт протокол; нужно ≥ {H_MIN}"
            )
        if not (H_MIN <= lo <= hi <= H_MAX):
            raise InvalidObfuscation(f"H{index} должен быть от {H_MIN} до {H_MAX}, а не {parsed[name]}")
        spans.append((lo, hi))
    for i in range(4):
        for j in range(i + 1, 4):
            a, b = spans[i], spans[j]
            if a[0] <= b[1] and b[0] <= a[1]:
                raise InvalidObfuscation(
                    "H1..H4 должны быть четырьмя разными числами или непересекающимися диапазонами"
                )

    s1, s2 = parsed["s1"], parsed["s2"]
    if s1 < 0 or s2 < 0:
        raise InvalidObfuscation("S1 и S2 не могут быть отрицательными")
    if INIT_BASE + s1 == RESPONSE_BASE + s2:
        raise InvalidObfuscation(
            f"S1 и S2 дают пакеты одной длины ({INIT_BASE + s1}): "
            f"рукопожатие вычисляется по размеру, нужно S1 + {INIT_BASE} ≠ S2 + {RESPONSE_BASE}"
        )
    for name in FIELDS_V2:
        if not (0 <= parsed[name] <= V2_S_MAX):
            raise InvalidObfuscation(f"{name.upper()} должен быть от 0 до {V2_S_MAX}, а не {parsed[name]}")

    jmin, jmax = parsed["jmin"], parsed["jmax"]
    if jmin < JMIN_FLOOR:
        raise InvalidObfuscation(f"Jmin должен быть не меньше {JMIN_FLOOR}")
    if jmax <= jmin:
        raise InvalidObfuscation(f"Jmax ({jmax}) должен быть больше Jmin ({jmin})")
    if jmax > JMAX_CEILING:
        raise InvalidObfuscation(f"Jmax больше {JMAX_CEILING} — пакет не пройдёт целиком")

    result = ObfuscationSet(**parsed)
    if strict and result.version == 1:
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

    return result


def generate(rng=None, *, version: int = 1) -> ObfuscationSet:
    rng = rng or _secrets.SystemRandom()

    if version == 2:
        jc = V2_JC
        jmin = rng.randint(*V2_JMIN)
        jmax = rng.randint(*V2_JMAX)
        s1 = rng.randint(*V2_S1)
        forbidden = s1 + INIT_BASE - RESPONSE_BASE
        s2 = rng.choice([value for value in range(V2_S2[0], V2_S2[1] + 1) if value != forbidden])
        s3 = rng.randint(*V2_S3)
        s4 = rng.randint(*V2_S4)
        spans: list[tuple[int, int]] = []
        while len(spans) < 4:
            lo = rng.randint(*V2_H_BASE)
            hi = lo + rng.randint(*V2_H_WIDTH)
            if all(hi < a or lo > b for a, b in spans):
                spans.append((lo, hi))
        headers = {f"h{i + 1}": f"{lo}-{hi}" for i, (lo, hi) in enumerate(spans)}
        return validate(
            {"jc": jc, "jmin": jmin, "jmax": jmax, "s1": s1, "s2": s2, "s3": s3, "s4": s4, **headers},
            strict=False,
        )

    jc = rng.randint(JC_MIN, JC_MAX)
    jmin = rng.randint(JMIN_LO, JMIN_HI)
    jmax = rng.randint(JMAX_LO, JMAX_HI)

    s1 = rng.randint(S_MIN, S_MAX)
    forbidden = s1 + INIT_BASE - RESPONSE_BASE
    s2 = rng.choice([value for value in range(S_MIN, S_MAX + 1) if value != forbidden])

    h1, h2, h3, h4 = rng.sample(range(H_MIN, 2**31), 4)

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
    for name in FIELDS_V2:
        value = interface.get(name.upper())
        if value is not None:
            values[name] = value
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
