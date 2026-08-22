"""
Генератор наборов обфускации.

Здесь проверяются требования, нарушение которых не видно глазом и почти не
диагностируется в бою: совпавшие заголовки дают «трафик идёт, рукопожатия нет
никогда», а совпавшие длины пакетов выдают рукопожатие даже при подменённых
заголовках. Поэтому правила проверяются не «обычно выполняются», а на тысяче
сгенерированных наборов и на каждом граничном случае отдельно.

Запуск: .venv/bin/python -m pytest tests/test_obfuscation.py -q
"""

from __future__ import annotations

import random

import pytest

from app import obfuscation as obf


def _valid() -> dict:
    """Заведомо годный набор — основа для точечных порч."""
    return {"jc": 4, "jmin": 40, "jmax": 700, "s1": 60, "s2": 90,
            "h1": 10, "h2": 20, "h3": 30, "h4": 40}


# --- генератор ---------------------------------------------------------------


def test_generate_always_satisfies_every_rule():
    """Тысяча наборов подряд — все требования ТЗ, без единого исключения."""
    for _ in range(1000):
        s = obf.generate()
        # H1..H4: четыре РАЗНЫХ числа >= 5
        headers = [s.h1, s.h2, s.h3, s.h4]
        assert len(set(headers)) == 4
        assert all(h >= 5 for h in headers)
        assert not (set(headers) & obf.RESERVED_HEADERS)
        # S1, S2 в 15..130 и S1 + 148 != S2 + 92
        assert 15 <= s.s1 <= 130 and 15 <= s.s2 <= 130
        assert s.s1 + 148 != s.s2 + 92
        # Jc = 3..6 (не 10)
        assert 3 <= s.jc <= 6
        # Jmax > Jmin
        assert s.jmax > s.jmin


def test_generate_is_not_constant():
    """Наборы обязаны отличаться — иначе «уникальность» была бы вывеской."""
    seen = {tuple(obf.generate().as_dict().values()) for _ in range(50)}
    assert len(seen) == 50


def test_generate_is_deterministic_with_seeded_rng():
    """С управляемым rng набор воспроизводим — это нужно тестам и отладке."""
    a = obf.generate(rng=random.Random(1234))
    b = obf.generate(rng=random.Random(1234))
    assert a == b


def test_generate_survives_rng_that_wants_forbidden_s2():
    """
    Запрет S1+148 == S2+92 выполняется ПОСТРОЕНИЕМ, а не отбраковкой.

    Подсовываем rng, который всегда просит первый элемент списка кандидатов:
    запрещённое значение обязано отсутствовать в самом списке.
    """
    class Greedy(random.Random):
        def randint(self, a, b):  # noqa: D102 - тестовый дублёр
            return a
        def choice(self, seq):  # noqa: D102
            return seq[0]
        def sample(self, population, k):  # noqa: D102
            # По индексу, а не через list(): популяция заголовков — это
            # range(5, 2**31), и материализовать её значит съесть всю память.
            return [population[i] for i in range(k)]

    s = obf.generate(rng=Greedy())
    assert s.s1 + 148 != s.s2 + 92


# --- валидация: каждое правило ТЗ отдельно -----------------------------------


def test_reserved_headers_are_rejected():
    """H = 1..4 — типы пакетов WireGuard: канонический заголовок обратно."""
    for bad in (0, 1, 2, 3, 4):
        values = _valid() | {"h2": bad}
        with pytest.raises(obf.InvalidObfuscation, match="H2"):
            obf.validate(values)


def test_duplicate_headers_are_rejected():
    values = _valid() | {"h3": _valid()["h1"]}
    with pytest.raises(obf.InvalidObfuscation, match="разными"):
        obf.validate(values)


def test_equal_packet_lengths_are_rejected():
    """S1 + 148 == S2 + 92 — требование владельца, проверяется буквально."""
    values = _valid() | {"s1": 30, "s2": 86}  # 178 == 178
    assert 30 + 148 == 86 + 92
    with pytest.raises(obf.InvalidObfuscation, match="одной длины"):
        obf.validate(values)
    # Соседние значения проходят — правило не шире, чем нужно.
    obf.validate(_valid() | {"s1": 30, "s2": 87})
    obf.validate(_valid() | {"s1": 30, "s2": 85})


def test_jc_outside_policy_is_rejected_but_only_in_strict():
    """Jc=10 (как было раньше) политику не проходит, импорт — проходит."""
    values = _valid() | {"jc": 10}
    with pytest.raises(obf.InvalidObfuscation, match="Jc"):
        obf.validate(values)
    assert obf.validate(values, strict=False).jc == 10


def test_jmax_must_exceed_jmin_always():
    """Это правило корректности — не отключается даже импортом."""
    for strict in (True, False):
        with pytest.raises(obf.InvalidObfuscation, match="Jmax"):
            obf.validate(_valid() | {"jmin": 500, "jmax": 500}, strict=strict)
        with pytest.raises(obf.InvalidObfuscation, match="Jmax"):
            obf.validate(_valid() | {"jmin": 600, "jmax": 500}, strict=strict)


def test_non_strict_still_rejects_broken_headers():
    """Импорт снимает политику, но не корректность: сломанный набор не пройдёт."""
    with pytest.raises(obf.InvalidObfuscation):
        obf.validate(_valid() | {"h1": 2}, strict=False)
    with pytest.raises(obf.InvalidObfuscation):
        obf.validate(_valid() | {"h1": _valid()["h4"]}, strict=False)
    with pytest.raises(obf.InvalidObfuscation, match="одной длины"):
        obf.validate(_valid() | {"s1": 30, "s2": 86}, strict=False)


def test_bool_is_not_accepted_as_int():
    """True прошёл бы как 1, то есть как служебный тип пакета."""
    with pytest.raises(obf.InvalidObfuscation):
        obf.validate(_valid() | {"h1": True})


def test_missing_field_is_named():
    values = _valid()
    del values["s2"]
    with pytest.raises(obf.InvalidObfuscation, match="S2"):
        obf.validate(values)


def test_numeric_strings_are_accepted():
    """Значения приходят из JSON и из текста конфига — строки допустимы."""
    values = {k: str(v) for k, v in _valid().items()}
    assert obf.validate(values).jc == 4


# --- представление -----------------------------------------------------------


def test_config_lines_match_wg_quick_shape():
    s = obf.validate(_valid())
    text = s.config_lines()
    assert "Jc = 4" in text and "Jmin = 40" in text and "Jmax = 700" in text
    assert "S1 = 60" in text and "S2 = 90" in text
    assert "H1 = 10" in text and "H4 = 40" in text
    # Порядок как в конфиге узла: сначала J, потом S, потом H.
    assert text.index("Jc") < text.index("S1") < text.index("H1")


def test_round_trip_through_config_text():
    """Набор читается обратно из текста конфига — на этом стоит импорт awg0."""
    s = obf.generate()
    config = "[Interface]\nPrivateKey = x\nAddress = 10.8.1.2/32\n" + s.config_lines() + "\n"
    assert obf.from_config_text(config, strict=True) == s


def test_from_config_text_names_missing_params():
    with pytest.raises(obf.InvalidObfuscation, match="H1"):
        obf.from_config_text("[Interface]\nJc = 4\nJmin = 40\nJmax = 700\nS1 = 60\nS2 = 90\n")


def test_from_config_text_imports_legacy_awg0():
    """Исторический набор боевого awg0 импортируется (Jc=10 — вне политики)."""
    legacy = ("[Interface]\nJc = 10\nJmin = 39\nJmax = 628\nS1 = 27\nS2 = 140\n"
              "H1 = 522668942\nH2 = 1626372724\nH3 = 1116046423\nH4 = 129443659\n")
    s = obf.from_config_text(legacy)
    assert s.jc == 10 and s.s2 == 140
    with pytest.raises(obf.InvalidObfuscation):
        obf.from_config_text(legacy, strict=True)
