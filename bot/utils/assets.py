"""Анимации разделов: свой файл на каждый экран.

Внутри одного раздела файл не меняется — Telegram правит только подпись и
кнопки, поэтому переходы мгновенные.
"""

from pathlib import Path


ASSETS = Path(__file__).resolve().parent.parent / "assets"

WELCOME = ASSETS / "welcome.mp4"                 # первый экран, до входа (старый)
MINIAPP = ASSETS / "miniapp.mp4"                 # первый экран: всё в мини-приложении
MENU = ASSETS / "menu.mp4"                       # главное меню
GATE = ASSETS / "splash.mp4"                     # вход и регистрация
LOGIN_LOGIN = ASSETS / "login_login.mp4"         # шаг «введите логин»
LOGIN_PASSWORD = ASSETS / "login_password.mp4"   # шаг «введите пароль»
PASSWORD = ASSETS / "password.mp4"               # смена пароля
CABINET_ACTIVE = ASSETS / "cabinet_active.mp4"   # кабинет с подпиской
CABINET_INACTIVE = ASSETS / "cabinet_inactive.mp4"  # кабинет без подписки
PAYMENTS = ASSETS / "payments.mp4"               # история платежей
PLANS = ASSETS / "plans.mp4"                     # тарифы и оплата
SUPPORT = ASSETS / "support.mp4"                 # поддержка
ABOUT = ASSETS / "devices.mp4"                   # о сервисе и приложения
PROMO = ASSETS / "promo.mp4"                     # переход по пригласительной ссылке
SUBSCRIBE = ASSETS / "subscribe.mp4"             # требование подписаться на канал
GIFT = ASSETS / "gift20.mp4"                     # письмо вдогонку: 20 дней в подарок
RENEW = ASSETS / "renew.mp4"                     # письмо вдогонку: продлить и получить неделю

# Не экран: аватар бота, ставится скриптом avatar.py
AVATAR = ASSETS / "avatar.mp4"


SCREENS = (
    WELCOME,
    MINIAPP,
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
    GIFT,
    RENEW,
)


def cabinet(active: bool) -> Path:
    return CABINET_ACTIVE if active else CABINET_INACTIVE
