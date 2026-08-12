"""
Убирает демонстрационные узлы из базы.

Зачем понадобилось. Демо-данные заводят узлы с адресами из RFC 5737
(`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) — они зарезервированы
под примеры в документации и не маршрутизируются никуда. Пока это тестовая
база, всё нормально. Но `PANEL_SEED_DEMO=1`, забытый на боевом сервере,
оставляет их среди настоящих узлов: панель показывает их включёнными,
клиент видит страну в списке, нажимает «подключиться» — и упирается в
тишину.

Панель их больше не отдаёт клиентам (см. `services/diagnostics.py`), но из
базы они не исчезают сами, мозолят глаза в разделе «Серверы» и портят
счётчики. Этот скрипт их убирает.

    cd backend
    .venv/Scripts/python.exe tools/purge_demo_servers.py            # показать
    .venv/Scripts/python.exe tools/purge_demo_servers.py --apply    # удалить

Выданные по ним ключи уходят вместе с узлом каскадом — они всё равно
никуда не вели.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Server, User  # noqa: E402
from app.services.diagnostics import is_documentation_address  # noqa: E402


def main() -> int:
    apply = "--apply" in sys.argv

    with SessionLocal() as db:
        servers = list(db.scalars(select(Server)))
        demo = [s for s in servers if is_documentation_address(s.host)]
        real = [s for s in servers if s not in demo]

        if not demo:
            print("Демонстрационных узлов нет.")
        else:
            print(f"Демонстрационных узлов: {len(demo)}")
            for s in demo:
                keys = len(s.keys)
                print(f"  [{s.id}] {s.name} — {s.host} (ключей: {keys})")

        print()
        if real:
            print(f"Настоящих узлов: {len(real)}")
            for s in real:
                mark = "включён" if s.is_active else "выключен"
                print(f"  [{s.id}] {s.name} — {s.host} ({mark}, {s.provisioning.value})")
        else:
            print("НАСТОЯЩИХ УЗЛОВ НЕТ.")
            print("Пока не добавлен хотя бы один рабочий сервер, оплатившие люди")
            print("не смогут подключиться. Заведите узел: deploy/setup-awg.sh")

        if not apply:
            if demo:
                print()
                print("Ничего не удалено. Чтобы удалить, запустите с --apply")
            return 0

        for s in demo:
            db.delete(s)
        db.commit()
        print()
        print(f"Удалено узлов: {len(demo)}")

        # Люди без единого рабочего узла — это те, кто заплатил и не может
        # подключиться. Про них надо знать поимённо.
        stranded = [u for u in db.scalars(select(User)) if u.has_access()]
        if stranded and not real:
            print()
            print(f"ВНИМАНИЕ: {len(stranded)} человек с действующей подпиской и без узлов:")
            for u in stranded[:10]:
                print(f"  {u.public_id}  {u.login}  {u.email or '—'}")
            if len(stranded) > 10:
                print(f"  … и ещё {len(stranded) - 10}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
