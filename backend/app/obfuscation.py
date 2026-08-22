"""
Наборы параметров обфускации AmneziaWG.

Зачем это отдельным модулем. До сих пор набор был один на весь сервис: те же
Jc/Jmin/Jmax/S1/S2/H1..H4 лежали в шаблоне сервера, в конфиге узла и, значит, у
каждого клиента. Один купленный доступ давал сигнатуру всего парка: чтобы
узнать, как выглядит трафик всех наших пользователей, достаточно было оплатить
один тариф. Теперь набор принадлежит точке входа, а точек входа на узле
несколько — отпечаток дробится.

Модуль намеренно чистый: ни базы, ни SSH. Его зовут генератор точек входа,
миграции и тесты, и он обязан быть проверяемым без окружения.

Главное правило: **невалидный набор нельзя сохранить**. Поэтому `generate()`
заканчивается вызовом `validate()`, а не «обычно и так получается верно», и
единственная дверь к записи в базу (services/endpoints.create) принимает уже
готовый `ObfuscationSet`, а не словарь чисел.
"""

from __future__ import annotations

import secrets as _secrets
from dataclasses import dataclass

# Поля набора в том порядке, в каком они стоят в [Interface] конфига. Порядок
# важен не протоколу, а нам: конфиг сравнивают глазами и диффом.
FIELDS = ("jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4")

# H1..H4 замещают собой типы пакетов WireGuard: 1 — initiation, 2 — response,
# 3 — cookie, 4 — transport. Значение из этого набора возвращает канонический
# заголовок, то есть ровно ту сигнатуру, ради сокрытия которой всё и делается.
# Ноль исключён отдельно: он не тип пакета, но и не значение — его подставляют,
# когда параметр «забыли».
RESERVED_HEADERS = frozenset({0, 1, 2, 3, 4})

H_MIN = 5
# Верхняя граница — 2^31-1: значения уходят в конфиг числом и читаются как
# 32-битное знаковое на стороне клиентских парсеров.
H_MAX = 2**31 - 1

# Постоянные части пакетов рукопожатия, к которым прибавляются S1 и S2.
# Совпадение сумм делает два разных пакета одинаковой длины — по этому
# признаку рукопожатие вычисляется, даже когда заголовки подменены.
INIT_BASE = 148
RESPONSE_BASE = 92

# Границы политики (strict). Отделены от границ корректности намеренно:
# корректность — то, без чего протокол не работает, политика — то, что мы
# считаем разумным. Импорт исторического набора идёт с strict=False.
JC_MIN, JC_MAX = 3, 6
S_MIN, S_MAX = 15, 130
JMIN_LO, JMIN_HI = 16, 64
JMAX_LO, JMAX_HI = 256, 1000

# Границы корректности junk-пакетов.
JMIN_FLOOR = 1
JMAX_CEILING = 1280


class InvalidObfuscation(ValueError):
    """Набор нельзя использовать. Текст объясняет, что именно не так."""


@dataclass(frozen=True, slots=True)
class ObfuscationSet:
    """Проверенный набор. Создаётся только через validate/generate."""

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
        """
        Строки для секции [Interface] — как их пишет и клиент, и узел.

        Имена с заглавной буквы: так их ждёт AmneziaWG и так они лежат во всех
        уже выданных конфигах. Разойдись регистр — параметр молча не применится.
        """
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
    # bool — подкласс int, и True прошёл бы как 1: то есть как зарезервированный
    # тип пакета. Отсекаем явно.
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise InvalidObfuscation(f"{name.upper()} должен быть целым числом") from None
    return value


def validate(values: dict | ObfuscationSet, *, strict: bool = True) -> ObfuscationSet:
    """
    Проверяет набор и возвращает его же в виде `ObfuscationSet`.

    `strict=False` снимает только границы политики (Jc, диапазоны S/J) и нужен
    ровно одному вызывающему — импорту исторического набора работающего узла:
    его значения выбирал не этот генератор, но люди на нём уже подключены, и
    отказать им — значит сломать работающее. Правила корректности не
    отключаются никогда: с ними протокол либо работает, либо нет.
    """
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
        # Два одинаковых заголовка — самый неприятный вид поломки: пакеты идут,
        # рукопожатия нет никогда, и со стороны клиента это неотличимо от
        # «сервер молчит».
        raise InvalidObfuscation("H1..H4 должны быть четырьмя разными числами")

    s1, s2 = parsed["s1"], parsed["s2"]
    if s1 < 0 or s2 < 0:
        raise InvalidObfuscation("S1 и S2 не могут быть отрицательными")
    if INIT_BASE + s1 == RESPONSE_BASE + s2:
        # Требование владельца S1+148 != S2+92. Записано через размеры пакетов,
        # а не через формулу: так видно, что именно проверяется, и так же
        # добавятся S3/S4, когда до них дойдёт дело.
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
            # Jc — сколько мусорных пакетов шлётся перед рукопожатием. Десяток,
            # который стоял раньше, это лишний трафик и лишний расход батареи на
            # телефоне при каждом подключении.
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
    """
    Новый набор — валидный по построению, а не по счастливой случайности.

    Ограничения выполняются конструктивно: разные H берутся выборкой без
    повторений, запрещённое S2 просто не попадает в список кандидатов. Поэтому
    здесь нет цикла «сгенерировали — проверили — не вышло — ещё раз», который
    однажды крутился бы вечно на противоречивых границах.

    Финальный `validate` оставлен намеренно: он ловит расхождение между
    генератором и правилами, если кто-то поправит одно и забудет другое.
    """
    rng = rng or _secrets.SystemRandom()

    jc = rng.randint(JC_MIN, JC_MAX)
    jmin = rng.randint(JMIN_LO, JMIN_HI)
    jmax = rng.randint(JMAX_LO, JMAX_HI)

    s1 = rng.randint(S_MIN, S_MAX)
    # S2, при котором пакеты сравнялись бы по длине, — ровно один: s1 + 56
    # (148 + s1 == 92 + s2). Выкидываем его из кандидатов.
    forbidden = s1 + INIT_BASE - RESPONSE_BASE
    s2 = rng.choice([value for value in range(S_MIN, S_MAX + 1) if value != forbidden])

    h1, h2, h3, h4 = rng.sample(range(H_MIN, H_MAX + 1), 4)

    return validate(
        {"jc": jc, "jmin": jmin, "jmax": jmax, "s1": s1, "s2": s2,
         "h1": h1, "h2": h2, "h3": h3, "h4": h4},
        strict=True,
    )


def from_config_text(config: str, *, strict: bool = False) -> ObfuscationSet:
    """
    Читает набор из текста wg-quick — для импорта уже работающего интерфейса.

    По умолчанию без границ политики: исторический awg0 собран не нами, а люди
    на нём подключены.
    """
    from .provisioning import interface_params

    interface = interface_params(config or "")
    values = {name: interface.get(name.capitalize() if name.startswith("j") else name.upper())
              for name in FIELDS}
    missing = [name.upper() for name, value in values.items() if value is None]
    if missing:
        raise InvalidObfuscation("в конфиге нет параметров: " + ", ".join(missing))
    return validate(values, strict=strict)
