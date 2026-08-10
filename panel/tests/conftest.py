"""
Общая настройка тестов.

Переменные окружения задаются здесь, а не в каждом модуле, по простой
причине: `settings()` кэшируется, а движок базы создаётся при первом
импорте `app.db`. Кто первым импортировал приложение, тот и определил
настройки для всего прогона — и модуль, выставивший свои переменные
секундой позже, тихо получал чужие. По отдельности такие тесты проходили,
вместе — падали, и виноватым выглядел последний добавленный.

conftest импортируется раньше любого тестового модуля, поэтому настройка
здесь действует на всех и одинаково.
"""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="panel-tests-")

os.environ.update(
    {
        "PANEL_DATABASE_URL": f"sqlite:///{_TMP}/tests.db",
        "PANEL_SEED_DEMO": "0",
        # Фоновые обходчики в тестах не нужны: они мешают воспроизводимости.
        "PANEL_TRAFFIC_SYNC_MINUTES": "0",
        "PANEL_DELIVERY_POLL_SECONDS": "0",
        "PANEL_ADMIN_LOGIN": "admin",
        "PANEL_ADMIN_PASSWORD": "admin",
        "PANEL_PAYMENT_PROVIDER": "mock",
        "PANEL_MAIL_PROVIDER": "console",
        "PANEL_SECRETS_KEY": "test-secrets-key-for-pytest",
        "PANEL_SITE_DIR": "",
        # Имитация оплаты не ждёт: вебхук в тестах отправляется вручную.
        "PANEL_MOCK_DELAY_SECONDS": "0",
        # Все запросы прогона идут с одного адреса, а заказов в нём больше
        # десятка. Сам ограничитель проверяется отдельным тестом на своих
        # числах — см. test_order_rate_limit_mechanism.
        "PANEL_ORDER_MAX_PER_HOUR": "500",
    }
)
