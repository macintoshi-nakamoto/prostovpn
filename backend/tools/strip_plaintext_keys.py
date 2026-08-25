from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import crypto, provisioning
from app.db import SessionLocal, init_db
from app.models import UserKey


def main() -> int:
    apply = "--apply" in sys.argv[1:]

    if not crypto.available():
        print("PANEL_SECRETS_KEY не задан или дефолтный — вычищать нечем и незачем", file=sys.stderr)
        return 2

    init_db()
    stripped = skipped_no_enc = skipped_mismatch = already = 0
    with SessionLocal() as db:
        keys = list(db.query(UserKey).all())
        for key in keys:
            interface = provisioning.interface_params(key.config or "")
            plain = interface.get("PrivateKey", "")
            if not plain or plain == provisioning.ENCRYPTED_PLACEHOLDER:
                already += 1
                continue
            if not key.private_key_enc:
                skipped_no_enc += 1
                print(f"  ключ {key.id}: нет шифра — сначала бэкфилл (шаг 1a), пропущен")
                continue
            try:
                decrypted = crypto.decrypt(key.private_key_enc)
            except crypto.SecretsUnavailable as exc:
                skipped_mismatch += 1
                print(f"  ключ {key.id}: шифр не читается ({exc}), пропущен")
                continue
            if decrypted != plain:
                skipped_mismatch += 1
                print(f"  ключ {key.id}: шифр не совпал с открытым текстом, пропущен")
                continue
            if apply:
                key.config = provisioning.with_private_key(
                    key.config, provisioning.ENCRYPTED_PLACEHOLDER
                )
            stripped += 1
        if apply and stripped:
            db.commit()

    verb = "вычищено" if apply else "готово к вычистке"
    print(f"\n{verb}: {stripped}")
    print(f"уже без открытого ключа: {already}")
    if skipped_no_enc:
        print(f"пропущено (нет шифра, нужен шаг 1a): {skipped_no_enc}")
    if skipped_mismatch:
        print(f"пропущено (шифр не сошёлся): {skipped_mismatch}")
    if not apply:
        print("\nэто сухой прогон — ничего не изменено. Для записи: --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
