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
        # Именно в секундах: значение в минутах панель игнорирует, пока
        # traffic_sync_seconds больше нуля, и фоновый обходчик реально
        # запускался посреди тестов, делая их плавающими.
        "PANEL_TRAFFIC_SYNC_SECONDS": "0",
        "PANEL_TRAFFIC_SYNC_MINUTES": "0",
        "PANEL_DELIVERY_POLL_SECONDS": "0",
        "PANEL_ADMIN_LOGIN": "admin",
        "PANEL_ADMIN_PASSWORD": "admin",
        "PANEL_PAYMENT_PROVIDER": "mock",
        # Platega в тестах не активный провайдер, но её вебхук и подписки
        # проверяются напрямую — ключи нужны для сверки заголовков.
        "PANEL_PLATEGA_MERCHANT_ID": "11111111-2222-3333-4444-555555555555",
        "PANEL_PLATEGA_SECRET": "test-platega-secret",
        "PANEL_MAIL_PROVIDER": "console",
        "PANEL_SECRETS_KEY": "test-secrets-key-for-pytest",
        "PANEL_SITE_DIR": "",
        # Имитация оплаты не ждёт: вебхук в тестах отправляется вручную.
        "PANEL_MOCK_DELAY_SECONDS": "0",
        # Все запросы прогона идут с одного адреса, а заказов в нём больше
        # десятка. Сам ограничитель проверяется отдельным тестом на своих
        # числах — см. test_order_rate_limit_mechanism.
        "PANEL_ORDER_MAX_PER_HOUR": "500",
        # То же и с регистрацией: учёток за прогон заводится больше, чем
        # разрешает боевой лимит на один адрес, а сам ограничитель проверяется
        # отдельным тестом — см. test_register_is_rate_limited_per_address.
        "PANEL_SIGNUP_MAX_PER_IP": "500",
    }
)
