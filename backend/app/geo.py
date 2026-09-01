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
    if not code:
        return fallback
    return COUNTRY_NAMES_EN.get(code.strip().upper(), fallback)


def flag(code: str | None) -> str:
    """Флаг страны из кода (NL → 🇳🇱); без кода — глобус."""
    value = (code or "").strip().upper()
    if len(value) != 2 or not value.isalpha():
        return "\U0001F310"
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in value)
