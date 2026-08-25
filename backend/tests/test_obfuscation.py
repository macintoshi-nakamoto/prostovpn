from __future__ import annotations

import random

import pytest

from app import obfuscation as obf


def _valid() -> dict:
    return {"jc": 4, "jmin": 40, "jmax": 700, "s1": 60, "s2": 90,
            "h1": 10, "h2": 20, "h3": 30, "h4": 40}


def test_generate_always_satisfies_every_rule():
    for _ in range(1000):
        s = obf.generate()
        headers = [s.h1, s.h2, s.h3, s.h4]
        assert len(set(headers)) == 4
        assert all(h >= 5 for h in headers)
        assert not (set(headers) & obf.RESERVED_HEADERS)
        assert 15 <= s.s1 <= 130 and 15 <= s.s2 <= 130
        assert s.s1 + 148 != s.s2 + 92
        assert 3 <= s.jc <= 6
        assert s.jmax > s.jmin


def test_generate_is_not_constant():
    seen = {tuple(obf.generate().as_dict().values()) for _ in range(50)}
    assert len(seen) == 50


def test_generate_is_deterministic_with_seeded_rng():
    a = obf.generate(rng=random.Random(1234))
    b = obf.generate(rng=random.Random(1234))
    assert a == b


def test_generate_survives_rng_that_wants_forbidden_s2():
    class Greedy(random.Random):
        def randint(self, a, b):
            return a
        def choice(self, seq):
            return seq[0]
        def sample(self, population, k):
            return [population[i] for i in range(k)]

    s = obf.generate(rng=Greedy())
    assert s.s1 + 148 != s.s2 + 92


def test_reserved_headers_are_rejected():
    for bad in (0, 1, 2, 3, 4):
        values = _valid() | {"h2": bad}
        with pytest.raises(obf.InvalidObfuscation, match="H2"):
            obf.validate(values)


def test_duplicate_headers_are_rejected():
    values = _valid() | {"h3": _valid()["h1"]}
    with pytest.raises(obf.InvalidObfuscation, match="разными"):
        obf.validate(values)


def test_equal_packet_lengths_are_rejected():
    values = _valid() | {"s1": 30, "s2": 86}
    assert 30 + 148 == 86 + 92
    with pytest.raises(obf.InvalidObfuscation, match="одной длины"):
        obf.validate(values)
    obf.validate(_valid() | {"s1": 30, "s2": 87})
    obf.validate(_valid() | {"s1": 30, "s2": 85})


def test_jc_outside_policy_is_rejected_but_only_in_strict():
    values = _valid() | {"jc": 10}
    with pytest.raises(obf.InvalidObfuscation, match="Jc"):
        obf.validate(values)
    assert obf.validate(values, strict=False).jc == 10


def test_jmax_must_exceed_jmin_always():
    for strict in (True, False):
        with pytest.raises(obf.InvalidObfuscation, match="Jmax"):
            obf.validate(_valid() | {"jmin": 500, "jmax": 500}, strict=strict)
        with pytest.raises(obf.InvalidObfuscation, match="Jmax"):
            obf.validate(_valid() | {"jmin": 600, "jmax": 500}, strict=strict)


def test_non_strict_still_rejects_broken_headers():
    with pytest.raises(obf.InvalidObfuscation):
        obf.validate(_valid() | {"h1": 2}, strict=False)
    with pytest.raises(obf.InvalidObfuscation):
        obf.validate(_valid() | {"h1": _valid()["h4"]}, strict=False)
    with pytest.raises(obf.InvalidObfuscation, match="одной длины"):
        obf.validate(_valid() | {"s1": 30, "s2": 86}, strict=False)


def test_bool_is_not_accepted_as_int():
    with pytest.raises(obf.InvalidObfuscation):
        obf.validate(_valid() | {"h1": True})


def test_missing_field_is_named():
    values = _valid()
    del values["s2"]
    with pytest.raises(obf.InvalidObfuscation, match="S2"):
        obf.validate(values)


def test_numeric_strings_are_accepted():
    values = {k: str(v) for k, v in _valid().items()}
    assert obf.validate(values).jc == 4


def test_config_lines_match_wg_quick_shape():
    s = obf.validate(_valid())
    text = s.config_lines()
    assert "Jc = 4" in text and "Jmin = 40" in text and "Jmax = 700" in text
    assert "S1 = 60" in text and "S2 = 90" in text
    assert "H1 = 10" in text and "H4 = 40" in text
    assert text.index("Jc") < text.index("S1") < text.index("H1")


def test_round_trip_through_config_text():
    s = obf.generate()
    config = "[Interface]\nPrivateKey = x\nAddress = 10.8.1.2/32\n" + s.config_lines() + "\n"
    assert obf.from_config_text(config, strict=True) == s


def test_from_config_text_names_missing_params():
    with pytest.raises(obf.InvalidObfuscation, match="H1"):
        obf.from_config_text("[Interface]\nJc = 4\nJmin = 40\nJmax = 700\nS1 = 60\nS2 = 90\n")


def test_from_config_text_imports_legacy_awg0():
    legacy = ("[Interface]\nJc = 10\nJmin = 39\nJmax = 628\nS1 = 27\nS2 = 140\n"
              "H1 = 522668942\nH2 = 1626372724\nH3 = 1116046423\nH4 = 129443659\n")
    s = obf.from_config_text(legacy)
    assert s.jc == 10 and s.s2 == 140
    with pytest.raises(obf.InvalidObfuscation):
        obf.from_config_text(legacy, strict=True)
