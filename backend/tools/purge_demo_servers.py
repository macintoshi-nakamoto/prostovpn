from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Server, User
from app.services.diagnostics import is_documentation_address


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
