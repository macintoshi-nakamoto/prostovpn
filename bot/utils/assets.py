from pathlib import Path


ASSETS = Path(__file__).resolve().parent.parent / "assets"

WELCOME = ASSETS / "welcome.mp4"
MENU = ASSETS / "menu.mp4"
GATE = ASSETS / "splash.mp4"
LOGIN_LOGIN = ASSETS / "login_login.mp4"
LOGIN_PASSWORD = ASSETS / "login_password.mp4"
PASSWORD = ASSETS / "password.mp4"
CABINET_ACTIVE = ASSETS / "cabinet_active.mp4"
CABINET_INACTIVE = ASSETS / "cabinet_inactive.mp4"
PAYMENTS = ASSETS / "payments.mp4"
PLANS = ASSETS / "plans.mp4"
SUPPORT = ASSETS / "support.mp4"
ABOUT = ASSETS / "devices.mp4"
PROMO = ASSETS / "promo.mp4"
SUBSCRIBE = ASSETS / "subscribe.mp4"

AVATAR = ASSETS / "avatar.mp4"


SCREENS = (
    WELCOME,
    MENU,
    GATE,
    LOGIN_LOGIN,
    LOGIN_PASSWORD,
    PASSWORD,
    CABINET_ACTIVE,
    CABINET_INACTIVE,
    PAYMENTS,
    PLANS,
    SUPPORT,
    ABOUT,
    PROMO,
    SUBSCRIBE,
)


def cabinet(active: bool) -> Path:
    return CABINET_ACTIVE if active else CABINET_INACTIVE
