from __future__ import annotations

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
