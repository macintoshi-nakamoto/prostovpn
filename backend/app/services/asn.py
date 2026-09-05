"""
Кто провайдер по адресу: ASN из открытой базы iptoasn.com.

Телеметрия из приложений называет оператора только на сотовой сети —
телефон сам знает, в чьей он сети. На Wi-Fi приложение видит лишь
«Wi-Fi», а нам важно, что за ним: Ростелеком режет не так, как Дом.ру.
Адрес запроса + эта база дают имя провайдера без единого внешнего
запроса с чужим адресом наружу.

База — один TSV на ~7 МБ в сжатом виде, обновляется раз в неделю и
живёт в отдельном SQLite (`data/asn.db`): в panel.db ей не место — она
не наша, её не надо ни бэкапить, ни возить между серверами.
"""

from __future__ import annotations

import gzip
import ipaddress
import logging
import os
import sqlite3
import time
from pathlib import Path

import httpx

from ..config import settings

log = logging.getLogger("panel.asn")

URL = "https://iptoasn.com/data/ip2asn-v4.tsv.gz"
KEEP_SECONDS = 7 * 24 * 3600

# Обрезки юридических форм: «PJSC MegaFon» и «MegaFon» — один провайдер.
_LEGAL = ("pjsc", "ojsc", "jsc", "llc", "ltd", "ooo", "zao", "oao", "pao", "ao", "inc", "co", "company")


def _path() -> Path:
    return Path(settings().data_dir) / "asn.db"


def stale() -> bool:
    try:
        return time.time() - _path().stat().st_mtime > KEEP_SECONDS
    except OSError:
        return True


def refresh(force: bool = False) -> bool:
    """Скачивает базу и пересобирает asn.db. Возвращает, было ли обновление."""
    if not force and not stale():
        return False
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_suffix(".db.new")
    try:
        with httpx.stream("GET", URL, timeout=90.0, follow_redirects=True) as response:
            response.raise_for_status()
            raw = b"".join(response.iter_bytes())
    except Exception as exc:  # noqa: BLE001 — база подождёт до следующего раза
        log.warning("база ASN не скачалась: %s", exc)
        return False

    try:
        text = gzip.decompress(raw).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        log.warning("база ASN не распаковалась: %s", exc)
        return False

    if fresh.exists():
        fresh.unlink()
    conn = sqlite3.connect(fresh)
    try:
        conn.execute("create table ranges (start integer not null, stop integer not null, asn integer not null, name text not null)")
        rows: list[tuple[int, int, int, str]] = []
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                start, stop, asn = int(ipaddress.IPv4Address(parts[0])), int(ipaddress.IPv4Address(parts[1])), int(parts[2])
            except (ValueError, ipaddress.AddressValueError):
                continue
            if asn == 0:
                continue
            rows.append((start, stop, asn, parts[4].strip()[:120]))
            if len(rows) >= 50_000:
                conn.executemany("insert into ranges values (?,?,?,?)", rows)
                rows.clear()
        if rows:
            conn.executemany("insert into ranges values (?,?,?,?)", rows)
        conn.execute("create index ranges_start on ranges(start)")
        conn.commit()
        count = conn.execute("select count(*) from ranges").fetchone()[0]
    finally:
        conn.close()

    if count < 100_000:
        log.warning("база ASN подозрительно мала (%d диапазонов) — оставляем прежнюю", count)
        fresh.unlink(missing_ok=True)
        return False
    os.replace(fresh, target)
    log.info("база ASN обновлена: %d диапазонов", count)
    return True


def refresh_if_stale() -> None:
    try:
        refresh()
    except Exception:  # noqa: BLE001
        log.exception("обновление базы ASN не удалось")


def lookup(ip: str | None) -> tuple[int, str] | None:
    """(ASN, описание) для адреса или None — нет базы, адрес не публичный, не нашли."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if addr.version != 4 or not addr.is_global:
        return None
    path = _path()
    if not path.exists():
        return None
    value = int(addr)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "select asn, name, stop from ranges where start <= ? order by start desc limit 1", (value,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("база ASN не читается: %s", exc)
        return None
    if row is None or row[2] < value:
        return None
    return int(row[0]), str(row[1])


def pretty(name: str) -> str:
    """«PJSC ROSTELECOM» → «Rostelecom»: без юридических форм и крика."""
    words = [w for w in name.replace(",", " ").split() if w.lower().strip(".") not in _LEGAL]
    text = " ".join(words) or name
    if text.isupper():
        text = text.title()
    return text[:64]


def isp_name(ip: str | None) -> str | None:
    found = lookup(ip)
    if found is None:
        return None
    return pretty(found[1])
