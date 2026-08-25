from __future__ import annotations

_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}


def slugify(value: str, fallback: str = "user") -> str:
    out: list[str] = []
    for char in value.lower():
        if char in _MAP:
            out.append(_MAP[char])
        elif char.isascii() and char.isalnum():
            out.append(char)
        else:
            out.append("-")

    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug[:24].strip("-") or fallback
