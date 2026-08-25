from datetime import datetime, timedelta


DB_FORMAT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def to_db(value: datetime) -> str:
    return value.strftime(DB_FORMAT)


def from_db(value: str) -> datetime:
    return datetime.strptime(value, DB_FORMAT)


def now_str() -> str:
    return to_db(now())


def human_date(value: datetime) -> str:
    return value.strftime("%d.%m.%Y")


def human_datetime(value: datetime) -> str:
    return value.strftime("%d.%m.%Y в %H:%M")


def days_left(expires_at: datetime) -> int:
    delta = expires_at - now()

    if delta <= timedelta(0):
        return 0

    seconds = int(delta.total_seconds())

    return max(1, -(-seconds // 86400))


def plural(count: int, one: str, few: str, many: str) -> str:
    tail = count % 100

    if 11 <= tail <= 14:
        return f"{count} {many}"

    tail = count % 10

    if tail == 1:
        return f"{count} {one}"

    if tail in (2, 3, 4):
        return f"{count} {few}"

    return f"{count} {many}"


def plural_days(count: int) -> str:
    return plural(count, "день", "дня", "дней")


def plural_devices(count: int) -> str:
    return plural(count, "устройство", "устройства", "устройств")


def plural_countries(count: int) -> str:
    return plural(count, "страна", "страны", "стран")
