"""
Английские названия стран по коду ISO.

Зачем это вообще нужно. Названия сервера администратор заводит по-русски —
«Нидерланды», «Амстердам», — а приложение с английским интерфейсом честно
откатывалось на них же: английского названия в базе нет, и показывать
нечего. Человек с английским интерфейсом видел кириллицу в списке стран.

Заставлять администратора заполнять второе название для каждой страны —
плохое решение: он забудет, и это будет ровно тот же баг, только позже и
тише. Код страны у сервера и так есть (он нужен для флага), а соответствие
«код → английское название» неизменно и известно заранее. Поэтому имя
берётся отсюда, а поле в панели остаётся для случаев, когда нужно своё.

Список не полный по ISO намеренно: здесь страны, где вообще ставят
VPN-узлы. Незнакомый код — не беда, вызывающий откатится на русское
название, и это по-прежнему лучше пустой строки.
"""

from __future__ import annotations

COUNTRY_NAMES_EN: dict[str, str] = {
    "AE": "United Arab Emirates",
    "AM": "Armenia",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "AZ": "Azerbaijan",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BR": "Brazil",
    "BY": "Belarus",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GE": "Georgia",
    "GR": "Greece",
    "HK": "Hong Kong",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IS": "Iceland",
    "IT": "Italy",
    "JP": "Japan",
    "KG": "Kyrgyzstan",
    "KR": "South Korea",
    "KZ": "Kazakhstan",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MD": "Moldova",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SK": "Slovakia",
    "TH": "Thailand",
    "TR": "Türkiye",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "US": "United States",
    "UZ": "Uzbekistan",
    "VN": "Vietnam",
    "ZA": "South Africa",
}


def country_en(code: str | None, fallback: str | None = None) -> str | None:
    """
    Английское название страны по коду ISO alpha-2.

    Неизвестный код или его отсутствие — возвращаем запасное значение
    (обычно русское название): показать кириллицу английскому интерфейсу
    хуже, чем показать её же вместо пустоты, но лучше, чем пустота.
    """
    if not code:
        return fallback
    return COUNTRY_NAMES_EN.get(code.strip().upper(), fallback)
