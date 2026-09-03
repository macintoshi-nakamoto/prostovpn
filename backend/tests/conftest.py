from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="panel-tests-")

os.environ.update(
    {
        "PANEL_DATABASE_URL": f"sqlite:///{_TMP}/tests.db",
        "PANEL_SEED_DEMO": "0",
        "PANEL_TRAFFIC_SYNC_SECONDS": "0",
        "PANEL_TRAFFIC_SYNC_MINUTES": "0",
        "PANEL_DELIVERY_POLL_SECONDS": "0",
        "PANEL_ADMIN_LOGIN": "admin",
        "PANEL_ADMIN_PASSWORD": "admin",
        "PANEL_PAYMENT_PROVIDER": "mock",
        "PANEL_PLATEGA_MERCHANT_ID": "11111111-2222-3333-4444-555555555555",
        "PANEL_PLATEGA_SECRET": "test-platega-secret",
        "PANEL_CRYPTOCLOUD_API_KEY": "test-cryptocloud-key",
        "PANEL_CRYPTOCLOUD_SHOP_ID": "test-shop",
        "PANEL_CRYPTOCLOUD_SECRET": "test-cryptocloud-secret",
        "PANEL_MAIL_PROVIDER": "console",
        "PANEL_SECRETS_KEY": "test-secrets-key-for-pytest",
        # TestClient приходит с адреса «testclient»; тесты подставляют
        # X-Forwarded-For, как это делает nginx.
        "PANEL_TRUSTED_PROXIES": "testclient,127.0.0.1,::1",
        "PANEL_SITE_DIR": "",
        "PANEL_MOCK_DELAY_SECONDS": "0",
        "PANEL_ORDER_MAX_PER_HOUR": "500",
        "PANEL_SIGNUP_MAX_PER_IP": "500",
    }
)
